"""Convert accredia_raw.json -> CertiFind CSVs (data/accredia-italy)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (compress_ea_codes, resolve_cert_number, classify_nace_to_ea,
                              write_certifind_csvs, ISO22003_TO_EA, ISO50003_TO_EA, MD8_TO_EA)

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "accredia-italy"
SRC = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_STANDARDS=1"
DET = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG="
EXP = ("1087:040427 1107:150729 1108:141229 1109:141229 2483:240329 2559:190529 2633:290930 2722:141227 2730:261126 "
       "2851:150629 2883:210628 2886:160427 2887:041127 2972:250928 3052:280528 3362:190431 3592:061128 3634:220428 "
       "3667:261126 3668:240927 3715:120429 3812:121226 3836:280527 4214:240527 4380:200730 4382:131227 4450:210429 "
       "4476:031128 4543:041028 4625:190427 4633:270529 4650:240927 4705:041128 4765:080429 4838:121229 4927:071127 "
       "4962:181228 5056:131227 5120:151229 5314:120730 5428:140229 5470:220627 5586:280129 0973:101227 0792:170327 "
       "0866:150629 0004:080729 0005:190927 0895:140927 0945:081129 0663:300727 0011:220728 0959:101228 0904:160427 "
       "0016:300727 0022:120627 0010:040427 0948:131226 0540:140628 0796:161227 0027:161226 0842:190728 0967:220227 "
       "0744:191229 0862:101227 0940:170528 0961:160427 0030:161229 0952:020428 0920:160427 0813:100228 0788:200727 "
       "0035:041029 0034:170327 0036:090728 0037:121227 0038:041129 0040:071127 0006:171027 0899:270230 0042:130327 "
       "0619:181228 0808:030528 0014:300727 0043:080729 0936:300727 0939:171027 0041:190127 0644:181228 0774:211027 "
       "0753:151226 0915:270230 0049:141227 0867:251029 0612:251028 0051:071028 0053:300527 0054:100629 0787:250227 "
       "0055:100228 0864:280229 0058:200727")
EXPIRY = {k: f"20{v[4:6]}-{v[2:4]}-{v[0:2]}" for k, v in (x.split(":") for x in EXP.split())}
COUNTRIES = {"Bosnia and Herzegovina": 5, "Italy": 5, "Kosovo": 5, "India": 6, "Liechtenstein": 4,
             "Israel": 0, "Switzerland": 4, "Indonesia": 5}
STD_KEY = {"ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001": "ISO 45001", "ISO 13485": "ISO 13485",
           "ISO 3834": "ISO 3834", "EN 15224": "EN 15224", "ISO 22000": "ISO 22000", "FSSC 22000": "FSSC 22000",
           "ISO 50001": "ISO 50001", "ISO/IEC 27001": "ISO/IEC 27001", "ISO/IEC 27701": "ISO/IEC 27701",
           "ISO/IEC 20000-1": "ISO/IEC 20000-1", "ISO 22301": "ISO 22301"}
EN50003 = {"1.1": "C", "1.2": "D", "2.1": "A", "2.2": "B", "3.0": "E", "4.0": "F", "5.0": "G", "6.0": "H"}
MD8 = {"1.1": "Non-active medical devices", "1.2": "Active (non-implantable) medical devices",
       "1.3": "Active implantable medical devices", "1.4": "In vitro diagnostic medical devices",
       "1.5": "Sterilization methods", "1.6": "Devices incorporating specific substances / technologies",
       "1.7": "Parts or services"}


def iso_date(d):
    return f"{d[6:]}-{d[3:5]}-{d[:2]}" if d else ""


def split_address(a):
    country = next((c for c in COUNTRIES if a.endswith(c)), "")
    body = a[: -len(country)].strip() if country else a
    body = re.sub(r"CH (\d{4})", r"\1", body)
    m = re.match(r"(.*?)(\d{4,})\s*-\s*([A-Z].+)$", body)
    if not m:
        m2 = re.match(r"(.*?\d+)\s*([A-Z][A-Z ]+)$", body)  # no postcode (Israel)
        return (f"{m2.group(1).strip()}, {m2.group(2).title()}" if m2 else body), country
    street, digits, rest = m.groups()
    n = COUNTRIES.get(country, 5)
    if n and len(digits) > n:
        street, digits = street + digits[:-n], digits[-n:]
    street = street.rstrip(" ,")
    if re.search(r"\([A-Z]{2}\)", rest):
        city = re.sub(r"\s*\([A-Z]{2}\).*$", "", rest)
    else:
        city = re.sub(r"(?<=[A-Z])[A-Z][a-z].*$", "", rest).strip()  # e.g. 'NEW DELHINew Delhi'
    city = city if "(" in rest else re.sub(r"\s+(ABRUZZO|SICILIA|SARDEGNA|LAZIO|LOMBARDIA|PIEMONTE|CAMPANIA|BASILICATA|EMILIA ROMAGNA|LIGURIA|TOSCANA|VENETO|PUGLIA|CALABRIA|MARCHE|FRIULI VENEZIA GIULIA)$", "", city)
    return f"{street}, {digits} {city.title()}", country


def sector_codes(raw):
    """IAF list like '01-07b,09,24*' -> (ea ints, limited codes)."""
    ea, lim = set(), []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.endswith("*"):
            tok = tok[:-1]
            lim.append(tok)
        nums = [int(re.match(r"\d+", p).group()) for p in tok.split("-")]
        ea.update(range(nums[0], nums[-1] + 1))
    return ea, lim


def scope_row(cert_base, std, label, codes):
    cert, acc = resolve_cert_number(cert_base, std)
    note, ea = "", ""
    if label == "I":
        s, lim = sector_codes(codes)
        ea = compress_ea_codes(s)
        note = "Limited scope for IAF " + ", ".join(lim) if lim else ""
    elif label == "C":
        cats = sorted({c[0] for c in codes.split(",") if c})
        ea = compress_ea_codes(e for c in cats for e in ISO22003_TO_EA.get(c, []))
        note = "Classified to EA from ISO 22003-1 categories " + ", ".join(cats)
    elif label == "T" and std == "ISO 50001":
        areas = [EN50003[c] for c in codes.split(",") if c in EN50003]
        ea = compress_ea_codes(e for a in areas for e in ISO50003_TO_EA[a])
        note = "Classified to EA from ISO 50003 technical areas " + codes.replace(",", ", ")
    elif label == "T" and std == "ISO 13485":
        mains = sorted({".".join(c.split(".")[:2]) for c in codes.split(",")})
        ea = compress_ea_codes(e for m in mains for e in MD8_TO_EA[MD8[m]])
        note = "Classified to EA from IAF MD 8 main technical areas " + ", ".join(mains)
    elif label == "N":
        ea, note = classify_nace_to_ea(codes.split(","))
    elif label == "S":
        note = "ISO 22301 sectors " + codes.replace(",", ", ") + " (no EA mapping)"
    else:
        note = "No sector restriction listed in the register"
    return {"certificate_number": cert, "certification_standard": std, "ea_codes": ea,
            "status": "active", "scope_note": note}, (cert, acc)


def main():
    raw = json.load(open(HERE / "accredia_raw.json", encoding="utf-8"))
    bodies, accs, scopes, excluded = [], {}, [], []
    for (oid, name, web, addr, tel, email, no, issue, _, items, skipped) in raw:
        if not items:
            excluded.append((oid, name, no, skipped))
            continue
        address, country = split_address(addr)
        base = no
        bodies.append({"name": name, "country": country, "registration_no": base, "phone": tel,
                       "email": email.split(";")[0].strip(), "website": f"https://{web}" if web else "",
                       "address": address, "source_url": SRC, "verified_at": ""})
        seen = {}
        for it in items:
            std = STD_KEY[it[0]]
            label, codes = (it[1], it[2]) if len(it) > 1 else ("", "")
            if std in seen and not label:
                continue  # duplicate bare mention (e.g. FSSC/ISO 22000 sub-scheme already listed)
            row, (cert, acc) = scope_row(base, std, label, codes)
            if std in seen:
                continue
            if std == "FSSC 22000" and not label:
                row["ea_codes"] = next((r["ea_codes"] for r in scopes if r["certificate_number"] == cert and r["certification_standard"] == "ISO 22000"), "")
                row["scope_note"] = "Same ISO 22003-1 categories as the ISO 22000 scope" if row["ea_codes"] else row["scope_note"]
            seen[std] = True
            scopes.append(row)
            accs.setdefault(cert, {"ab_code": "ACCREDIA", "certificate_number": cert, "body_name": name,
                                   "accreditation_standard": acc, "status": "active",
                                   "issue_date": iso_date(issue), "expiry_date": EXPIRY.get(oid, ""),
                                   "proof_url": DET + oid})
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        write_certifind_csvs(OUT, bodies, list(accs.values()), scopes)
    json.dump(excluded, open(HERE / "excluded.json", "w"), ensure_ascii=False)
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excluded)}")


if __name__ == "__main__":
    main()
