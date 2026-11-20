"""Build CertiFind CSVs for NiNAS (Nigeria). Contacts from _raw/register.json; IDs, dates and scopes
transcribed from the five accreditation schedule PDFs (layouts too irregular for a generic parser)."""
import json, re
from pathlib import Path
from certifind_common import (ISO22003_TO_EA, classify_nace_to_ea, compress_ea_codes,
                              resolve_cert_number, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = HERE / "data" / "ninas-nigeria"
SRC = "https://ninas.ng/accreditation/accredited-management-system-bodies/"
reg = json.loads((HERE / "_raw" / "register.json").read_text(encoding="utf8"))
by_pdf = {Path(r["pdf"]).name: r for r in reg}

IAF = [3, 5, 9, 10, 13, 15, 18, 30, 31, 33, 34, 35]
# (pdf, name, country, base id, issue, expiry, {standard: ea list})
BODIES = [
    ("Systems-Certifications-Accreditation-Certificate.pdf", "Systems Certifications Limited", "Nigeria", "MSC0001",
     "2024-10-21", "2026-10-20", {"ISO 9001": [34], "ISO 14001": [34], "ISO 45001": [34]}),
    ("Interconformity-Accreditation-Certificate.pdf", "Interconformity Assessment & Certification Limited", "Nigeria", "MSC0002",
     "2025-04-30", "2027-04-29", {"ISO 9001": IAF, "ISO 14001": IAF, "ISO 45001": IAF, "ISO/IEC 27001": IAF,
                                  "ISO 22000": ISO22003_TO_EA["I"]}),
    ("CORE_QUALITY_Accreditation_Cert.pdf", "Corequality CB Limited", "Nigeria", "MSC0004",
     "2026-03-03", "2030-03-02", {"ISO 9001": [29, 30, 32, 33, 34, 35, 36, 37], "ISO 14001": [34], "ISO 45001": [34],
                                  "ISO/IEC 27001": [33], "ISO 22000": ISO22003_TO_EA["E"]}),
    ("Nicert-limited-Accreditation-Certificate.pdf", "Nicert Limited", "Nigeria", "MSC0005",
     "2025-03-10", "2027-03-09", {"ISO 22000": ISO22003_TO_EA["C"] + ISO22003_TO_EA["D"]}),
    ("WSR_Accreditation_Certificate.pdf", "WSR Certification Private Limited", "India", "MSC0006",
     "2026-10-21", "2030-10-20",
     {"ISO 9001": [1, 3, 30, 28, 34, 4, 5, 6, 14, 23, 32, 35, 29, 37, 36, 33, 38, 7, 9, 8, 24, 31, 39],
      "ISO 14001": [28, 34, 4, 5, 6, 23, 29, 36, 35, 7, 9, 8],
      "ISO 45001": [28, 34, 4, 5, 6, 23, 29, 32, 36, 35, 7, 9, 8]}),
]
NOTES = {"ISO 22000": {
    "MSC0002": "ISO 22003-1 category I (production of packaging material)",
    "MSC0004": "ISO 22003-1 category E (catering services), full category",
    "MSC0005": "ISO 22003-1 categories C and D (food and feed processing; subcategories CI-CIV)"}}

def fix_phone(raw):
    p = list(dict.fromkeys(x.strip() for x in raw.split(",")))[0]
    d = re.sub(r"\D", "", p)
    if p.startswith("+91"):
        return "+91 %s %s" % (d[2:7], d[7:])
    if len(d) == 11 and d.startswith("0"):
        return "+234 %s %s %s" % (d[1:4], d[4:7], d[7:])
    return ""

bodies, accs, scopes = [], [], []
for pdf, name, country, base, issue, exp, schemes in BODIES:
    r = by_pdf[pdf]
    bodies.append({"name": name, "country": country, "registration_no": base, "phone": fix_phone(r["phone"]),
                   "email": r["email"], "website": "", "address": r["address"].title(),
                   "source_url": SRC, "verified_at": ""})
    seen = set()
    for std, ea in schemes.items():
        cert, acc_std = resolve_cert_number(base, std)
        if cert not in seen:
            seen.add(cert)
            accs.append({"ab_code": "NINAS", "certificate_number": cert, "body_name": name,
                         "accreditation_standard": acc_std, "status": "active" if r["status"] == "Active" else "inactive",
                         "issue_date": issue, "expiry_date": exp, "proof_url": r["pdf"]})
        scopes.append({"certificate_number": cert, "certification_standard": std, "ea_codes": compress_ea_codes(ea),
                       "status": "active", "scope_note": NOTES.get(std, {}).get(base, "IAF codes as listed on the schedule")})

write_certifind_csvs(OUT, bodies, accs, scopes)
print("Excluded: 0")
