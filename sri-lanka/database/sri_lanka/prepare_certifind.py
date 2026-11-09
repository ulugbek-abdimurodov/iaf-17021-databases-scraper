"""Convert slab_raw.tsv -> data/slab-sri_lanka CertiFind CSVs."""
from pathlib import Path
from certifind_common import resolve_cert_number, write_certifind_csvs
HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "slab-sri_lanka"
SRC = "https://www.slab.lk/directory/registry/"
SCHEME = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001", "FMS": "ISO 22000",
          "ENS": "ISO 50001", "IMS": "ISO/IEC 27001"}
bodies, accs, scopes = {}, [], []
for line in (HERE / "slab_raw.tsv").read_text().splitlines():
    acc, name, web, issue, exp, pdf = line.split("\t")
    prog, num = acc.split(" ")
    reg = num.split("-")[0]
    b = bodies.setdefault(name, {"name": name, "country": "Sri Lanka", "registration_no": reg, "phone": "",
                                 "email": "", "website": "", "address": "", "source_url": SRC + acc.replace(" ", "+"),
                                 "verified_at": ""})
    b["website"] = b["website"] or web
    std = SCHEME[prog]
    cert, acc_std = resolve_cert_number(acc, std)
    accs.append({"ab_code": "SLAB", "certificate_number": cert, "body_name": name, "accreditation_standard": acc_std,
                 "status": "active", "issue_date": issue, "expiry_date": exp,
                 "proof_url": f"https://www.slab.lk/media/file/{pdf}" if pdf else ""})
    scopes.append({"certificate_number": cert, "certification_standard": std, "ea_codes": "", "status": "active",
                   "scope_note": "Sector codes not extracted: scope schedule PDF not machine-read (see slab_review.md)"})
write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
print("Excluded: 0")
