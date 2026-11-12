"""Convert GAC register + parsed scope data into CertiFind CSVs."""
import json, re, sys
from datetime import date
from datetime import datetime
from pathlib import Path
from certifind_common import (ISO22003_TO_EA, compress_ea_codes, resolve_cert_number, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[4] / "certifind" / "data" / "gac-saudi-arabia"
sys.path.insert(0, str(HERE.parents[3]))
from prune_inactive import prune

CC = {"China": "86", "Qatar": "974", "Oman": "968", "Saudi Arabia": "966", "Pakistan": "92", "Spain": "34", "Turkey": "90", "United Arab Emirates": "971", "India": "91", "Bahrain": "973"}
LEN = {"86": (10, 11), "974": (8, 8), "968": (8, 8), "966": (8, 9), "92": (9, 10), "34": (9, 9), "90": (10, 10), "971": (8, 9), "91": (10, 10), "973": (8, 8)}
NOTES = []

def phone(raw, country, who):
    """Return '+<cc> <national>' or '' (with a review note) if the number can't be fixed."""
    d = re.sub(r"\D", "", raw)
    if not d:
        return ""
    cc = CC[country]
    if raw.strip().startswith("+"):
        if not d.startswith(cc):
            other = next((c for c in LEN if d.startswith(c) and LEN[c][0] <= len(d) - len(c) <= LEN[c][1]), None)
            if other is None:
                NOTES.append(f"- {who}: phone `{raw}` does not start with +{cc} ({country}); left empty.")
                return ""
            NOTES.append(f"- {who}: phone `{raw}` is a +{other} number although the body is in {country}; kept.")
            cc = other
        d = d[len(cc):]
    nat = d.lstrip("0")
    lo, hi = LEN[cc]
    if not lo <= len(nat) <= hi:
        NOTES.append(f"- {who}: phone `{raw}` has the wrong length for +{cc}; left empty.")
        return ""
    return f"+{cc} {nat}"

REGISTER = "https://gac.org.sa/accredited-bodies/"
PDF = "https://api.gac.org.sa/public/uploads/cab_request/scopes/{}.pdf"

def iso(d: str) -> str:
    return datetime.strptime(d.strip(), "%d %b %Y" if len(d.split()[1]) == 3 else "%d %B %Y").strftime("%Y-%m-%d") if d else ""

raw = json.load(open(HERE / "gac_raw.json", encoding="utf-8"))
bodies, accs, scopes, excluded = [], [], [], 0
for line in open(HERE / "gac_register.txt", encoding="utf-8"):
    code, name, country, valid, _cert, scope_id = line.rstrip("\n").split("|")
    r = raw[code]
    if "excluded" in r:
        excluded += 1
        continue
    base = f"MSC {code}"
    bodies.append(dict(name=name, country=country, registration_no=base, phone=phone(r["tel"], country, base + " " + name), email=r["em"],
                       website=(r["web"] if r["web"].lower().startswith("http") else "https://" + r["web"]) if r["web"] else "", address=r["loc"], source_url=REGISTER, verified_at=""))
    seen = set()
    for std, val in r["sc"].items():
        cert_no, acc_std = resolve_cert_number(base, std)
        if cert_no not in seen:
            seen.add(cert_no)
            accs.append(dict(ab_code="GAC", certificate_number=cert_no, body_name=name, accreditation_standard=acc_std,
                             status="ACTIVE", issue_date=iso(r["iss"]), expiry_date=iso(valid), proof_url=PDF.format(scope_id)))
        if "22000" in std:
            ea = compress_ea_codes(e for c in val for e in ISO22003_TO_EA[c])
            note = f"Classified to EA from ISO 22003-1 categories {', '.join(val)}"
        elif "13485" in std:
            ea, note = "1-39", "No sector list in the GAC register; recorded for all EA sectors"
        else:
            ea = compress_ea_codes(int(x) for x in val.split(",") if x)
            note = r.get("note", {}).get(std, "IAF codes as listed in the GAC scope of accreditation")
        scopes.append(dict(certificate_number=cert_no, certification_standard=std, ea_codes=ea, status="ACTIVE", scope_note=note))

write_certifind_csvs(OUT, bodies, accs, scopes)
print("Pruned:", prune(OUT, date(2026, 11, 9)))
print("\n".join(NOTES))
rv = HERE / "gac_review.md"
rv.write_text(rv.read_text(encoding="utf-8").split("\n## Phone fixes")[0].rstrip() + "\n\n## Phone fixes (prepare_certifind.py)\n"
              + "\n".join(NOTES) + "\n- MSC 0018 United Quality Assurance Services LLC: only ISO 22000 (no ISO/IEC 17021-1 row); dropped by prune_inactive.\n",
              encoding="utf-8")
print(f"Excluded: {excluded}")
