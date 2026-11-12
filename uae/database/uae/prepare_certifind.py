"""Convert eiac_raw.json (scrape_ae_eiac.py) into the CertiFind dataset data/eiac-uae/."""
import json
import re
from datetime import date
from pathlib import Path

from certifind_common import ISO22003_TO_EA, compress_ea_codes, resolve_cert_number, write_certifind_csvs

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "eiac-uae"
TODAY = date(2026, 11, 9)
SOURCE_URL = "https://eiac.gov.ae/directory/"
PDF_URL = "https://accreditation.eiac.gov.ae/api/return_pdf_file?file_name="

SCHEMES = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHSMS": "ISO 45001", "FSMS": "ISO 22000",
           "ISMS": "ISO/IEC 27001", "BCMS": "ISO 22301"}
EXCLUDED = {"HACCP": "HACCP (not an ISO management-system standard)",
            "PRD": "Product certification (ISO/IEC 17065)",
            "FMMS": "ISO 41001 facility management (no CertiFind mapping)"}
# Directory address missing or wrong country → corrected from website/annex/country list
COUNTRY_FIX = {"BULGYO ASSESSMENT INDIA PRIVATE LIMITED": "India", "ROBUST CERTIFICATIONS PRIVATE LIMITED": "India",
               "Elite Quality and Standardization Certificates LLC - SPC": "United Arab Emirates",
               "Horn of Africa Livestock Improvement and Conformity Services (HALICS)": "Somalia",
               "KBS Certification Services Limited": "India", "NQA Certification Limited": "United Kingdom",
               "Sheq National Cert International (PTY) LTD": "South Africa"}
CITY_FIX = {"AbuDhabi": "Abu Dhabi"}


def norm_id(raw_id: str) -> str:
    return re.sub(r"[\s_]+", "", raw_id).rstrip("-")


def parse_validity(val: str):
    v = re.sub(r"\s+", "", val)
    m = re.findall(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v)
    if len(m) < 2:
        return "", ""
    f = lambda t: date(int(t[2]), int(t[1]), int(t[0])).isoformat()
    return f(m[0]), f(m[1])


def clean_address(addr: str, country: str) -> str:
    parts, seen = [], set()
    for p in re.split(r"\s*[,|]\s*", addr):
        p = CITY_FIX.get(p.strip(), p.strip())
        if p.isupper() and len(p) > 3:
            p = p.title()
        k = p.lower()
        if not p or k in seen or k in {country.lower(), "uae", "u.a.e.", "united arab emirates"}:
            continue
        seen.add(k)
        parts.append(p)
    return ", ".join(parts)


def first_email(s: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", s)
    return m.group(0) if m else ""


def clean_web(s: str) -> str:
    s = s.strip().rstrip("/")
    if not s or "." not in s:
        return ""
    return s if s.startswith("http") else "https://" + s


def clean_phone(s: str) -> str:
    s = s.split("Mobile No.")[0].strip()
    return "" if "undefined" in s else s


def main():
    raw = json.loads((HERE / "eiac_raw.json").read_text(encoding="utf-8"))
    review, best = [], {}
    for r in raw:
        cid = norm_id(r["id"])
        if r["nm"].startswith("Sheq") and cid in ("CB-EMS", "CB-EMS-114"):
            if not r["ttl"]:
                review.append(f"- {r['nm']} CB-EMS-114 (directory ID {r['dir']}): duplicate entry with unreadable PDF; used directory ID 1016.")
                continue
            cid = "CB-EMS-114"
        m = re.match(r"CB-([A-Z]+)-(\d+)$", cid)
        if not m:
            review.append(f"- {r['nm']} `{r['id']}` (directory ID {r['dir']}): {r['ttl'].strip() or 'unrecognised file'} — HACCP scope file, skipped.")
            continue
        code, num = m.groups()
        if code not in SCHEMES:
            review.append(f"- {r['nm']} {cid}: {EXCLUDED.get(code, code)} — skipped.")
            continue
        r["cid"], r["code"], r["num"] = cid, code, num
        issue = int(re.search(r"IssueNo\.:(\d+)", r["iss"]).group(1)) if "IssueNo" in r["iss"] else 0
        if cid in best and best[cid][0] >= issue:
            review.append(f"- {cid}: older duplicate directory entry (ID {r['dir']}) dropped.")
            continue
        if cid in best:
            review.append(f"- {cid}: older duplicate directory entry (ID {best[cid][1]['dir']}) dropped.")
        best[cid] = (issue, r)

    bodies, accs, scopes, info = {}, [], [], {}
    for r in raw:
        if r.get("addr") is not None and r["nm"] not in info:
            info[r["nm"]] = r
    for cid, (_, r) in sorted(best.items()):
        b = info[r["nm"]]
        country = COUNTRY_FIX.get(r["nm"]) or (b["addr"].split(",")[-1].strip() if b["addr"] else "United Arab Emirates")
        if r["nm"] not in bodies:
            bodies[r["nm"]] = dict(name=r["nm"], country=country, registration_no=f"CB-{r['num']}",
                                   phone=clean_phone(b.get("ph", "")), email=first_email(b.get("em", "")),
                                   website=clean_web(b.get("web", "")), address=clean_address(b.get("addr", ""), country),
                                   source_url=SOURCE_URL, verified_at="")
        std = SCHEMES[r["code"]]
        cert_no, acc_std = resolve_cert_number(cid, std)
        issue, expiry = parse_validity(r["val"])
        status = "active" if expiry and expiry >= TODAY.isoformat() else "expired"
        accs.append(dict(ab_code="EIAC", certificate_number=cert_no, body_name=r["nm"], accreditation_standard=acc_std,
                         status=status, issue_date=issue, expiry_date=expiry, proof_url=PDF_URL + r["f"]))
        if r["code"] == "FSMS":
            cats = list(r["cat"])
            ea = compress_ea_codes(c for k in cats for c in ISO22003_TO_EA.get(k, []))
            note = f"Classified to EA from the ISO 22003-1 categories listed ({', '.join(cats)})" if cats else ""
        else:
            ea = compress_ea_codes(int(x) for x in r["ea"].split())
            note = "IAF/EA codes as listed in the EIAC scope annex"
        if not ea:
            note = "No sector codes in the scope annex"
            review.append(f"- {cert_no} ({r['nm']}): no EA codes/categories readable in the annex; scope imported without codes.")
        if r["nm"].startswith("TÜV NORD") and r["code"] == "EMS":
            review.append(f"- {cert_no}: the published EMS PDF carries the ISO 9001 scope title; codes taken as printed.")
        scopes.append(dict(certificate_number=cert_no, certification_standard=std, ea_codes=ea, status=status, scope_note=note))

    write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
    (HERE / "eiac_review.md").write_text(
        "# EIAC review log\n\nSkipped or adjusted registrations from the EIAC directory "
        f"({SOURCE_URL}, management-system CBs, retrieved {TODAY}).\n\n"
        "## Country corrections\n" + "\n".join(f"- {k}: {v}" for k, v in COUNTRY_FIX.items()) +
        "\n\n## Registrations\n" + "\n".join(review) + "\n", encoding="utf-8")
    print(f"Excluded: {len(review)}")


if __name__ == "__main__":
    main()
