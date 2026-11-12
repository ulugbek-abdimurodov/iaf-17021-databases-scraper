"""Convert anab_raw.psv into the CertiFind dataset at data/anab-usa/."""
import re, sys
from datetime import datetime
from pathlib import Path
from certifind_common import (ISO22003_TO_EA, MD8_TO_EA, compress_ea_codes, resolve_cert_number,
                              write_certifind_csvs)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "data" / "anab-usa"
SOURCE_URL = "https://anabdirectory.remoteauditor.com/"
PDF = "https://anab.jadian.com/Certificate.mvc?PKey={}&useId=true&OrgId={}"
MD8_KEYS = {"1.1": "Non-active medical devices", "1.2": "Active (non-implantable) medical devices",
            "1.3": "Active implantable medical devices", "1.4": "In vitro diagnostic medical devices",
            "1.5": "Sterilization methods", "1.6": "Devices incorporating specific substances / technologies",
            "1.7": "Parts or services"}
COUNTRY = {"KOREA, REPUBLIC OF": "South Korea", "UNITED STATES": "United States", "UNITED KINGDOM": "United Kingdom",
           "UNITED ARAB EMIRATES": "United Arab Emirates", "CZECH REPUBLIC": "Czech Republic"}
TRAIL_COUNTRY = r"\s*,?\s*(United States|USA|United Kingdom|France|China|P\. R\. China|India|Israel|Australia|Mexico|México|Spain|Japan|Japa n|Canada|C anada|Korea \(Republic of\)|United Arab Emirates|Italy|Denmark|Jamaica|Czech Republic|Peru|Singapore)$"


def key(s): return re.sub(r"[^a-z0-9]", "", s.lower())


def expand(codes):
    out = []
    for c in filter(None, codes.split(",")):
        if re.fullmatch(r"\d+-\d+", c): a, b = map(int, c.split("-")); out += list(range(a, b + 1))
        else: out.append(c)
    return out


def iso(d):
    d = d.replace("Novemeber", "November")
    return datetime.strptime(d, "%d %B %Y").strftime("%Y-%m-%d")


def clean_addr(raw, name):
    parts = [p.strip() for p in raw.split(" ~ ") if p.strip()]
    nk = key(name)
    while parts and key(parts[0]) and (key(parts[0]) in nk or nk.startswith(key(parts[0])[:12])):
        parts.pop(0)
    parts = [p for p in parts if not re.search(r"www\.|\(virtual|^Virtual$", p)]
    s = ", ".join(parts)
    s = re.sub(r"(\d+), (st|nd|rd|th), ", r"\1\2 ", s)
    s = re.sub(r"\b([A-Z]) ([A-Z])\b(?= ?\d)", r"\1\2", s)                       # "O H 45402" -> "OH 45402"
    s = re.sub(r"\b([A-Z]) ([a-z]{2,})", r"\1\2", s)                               # "D istrict" -> "District"
    s = re.sub(r"(\d) (\d{1,3})\b(?= |$)", r"\1\2", s)                             # "4812 0" -> "48120"
    s = re.sub(r"\s+([,.])", r"\1", s); s = re.sub(r"\s*-\s*(?=\d)", "-", s); s = re.sub(r"\s+", " ", s)
    s = re.sub(r",\s*,", ",", s); s = re.sub(r"\b(Suite \d) (\d+)", r"\1\2", s)
    s = re.sub(r"\bJ r\.", "Jr.", s); s = s.replace("Dong c heng", "Dongcheng").replace(" - ku", "-ku").replace(" - shi", "-shi")
    s = re.sub(r"^N Y$", "NY", s)
    s = re.sub(TRAIL_COUNTRY, "", s).strip(" ,")
    s = re.sub(r"\b([A-Z]{3,})\b", lambda m: m[1].title() if len(m[1]) > 3 and m[1] not in ("ITPL", "CAP") else m[1], s)
    return s


def website(w):
    w = re.sub(r"^http://www\.(https?://)", r"\1", w.strip())
    return re.sub(r"^http://www\.www\.", "http://www.", w, flags=re.I).lower() if w else ""


def scope_row(cert, std, codes):
    if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
        ea = compress_ea_codes(int(c) for c in codes)
        return ea, "EA sectors per ANAB Accreditation Rule 20/21/30" if ea else "No sector list on the ANAB scope"
    if std == "ISO 13485":
        names = [MD8_KEYS[c] for c in codes if c in MD8_KEYS]
        ea = compress_ea_codes(e for n in names for e in MD8_TO_EA[n])
        return ea, f"Classified to EA from the IAF MD 8 main technical areas listed ({', '.join(names)})" if names else "No technical areas on the ANAB scope"
    if std in ("ISO 22000", "FSSC 22000"):
        ea = compress_ea_codes(e for c in codes for e in ISO22003_TO_EA.get(c, []))
        return ea, f"Classified to EA from the ISO 22003-1 food chain categories listed ({', '.join(codes)})" if codes else "No food chain categories on the ANAB scope"
    return "", "ANAB scope lists no sectors/technical areas for this scheme"


def main(raw=HERE / "anab_raw.psv"):
    bodies, accs, scopes, excluded = [], [], [], 0
    section = "inc"
    for line in Path(raw).read_text(encoding="utf-8").splitlines():
        if line.startswith("#EXCLUDED"): section = "exc"; continue
        if not line.strip() or line.startswith("#"): continue
        if section == "exc": excluded += 1; continue
        rid, name, since, exp, addr, ctry, web, phone, email, pk, org, sc, _other = line.split("|")
        reg = f"MS-{rid}"; proof = PDF.format(pk, org)
        bodies.append(dict(name=name, country=COUNTRY.get(ctry, ctry.title()), registration_no=reg, phone=phone,
                           email=email, website=website(web), address=clean_addr(addr, name),
                           source_url=SOURCE_URL, verified_at=""))
        seen = set()
        for part in sc.split(";"):
            std, codes = part.split("=")
            cert, acc_std = resolve_cert_number(reg, std)
            if cert not in seen:
                seen.add(cert)
                accs.append(dict(ab_code="ANAB", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                                 status="active", issue_date=iso(since), expiry_date=iso(exp), proof_url=proof))
            ea, note = scope_row(cert, std, expand(codes))
            scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea, status="active", scope_note=note))
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        write_certifind_csvs(OUT, bodies, accs, scopes)
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {excluded}")


if __name__ == "__main__":
    main(*sys.argv[1:])
