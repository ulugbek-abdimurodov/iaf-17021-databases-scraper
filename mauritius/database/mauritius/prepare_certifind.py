import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import *
REG = "https://www.mauritas.org/entities.php"
OUT = Path(__file__).resolve().parents[2] / "data/mauritas-mauritius"
# Register snapshot 2026-11-10 (CB001.pdf, issue 25 May 2026, expiry 23 July 2029)
CBS = [{
    "id": "CB001", "name": "Mauritius Standards Bureau - Quality Assurance Unit",
    "phone": "+230 433 3648", "email": "msb@intnet.mu", "website": "http://msb.intnet.mu",
    "address": "Villa Road, Moka", "pdf": "https://www.mauritas.org/files/CB001.pdf",
    "issue": "2026-05-25", "expiry": "2029-07-23",
    # IAF ID1 sector -> excluded NACE codes (partial scope)
    "qms": {1: ["02"], 3: ["12"], 4: [], 12: [], 14: [], 17: ["24.46", "25.4", "33.11"], 29: ["95.2"],
            31: ["49", "50", "51", "61"], 32: ["68", "77"], 33: ["58.2"], 34: ["74.2", "74.3"],
            35: ["73", "74.2", "74.3"], 36: [], 37: [], 38: []},
    "fsms_cats": ["C"], "isms": True, "excluded": ["HACCP (not an ISO/IEC 17021-1 MS scheme in CertiFind)"],
}]
bodies, accs, scopes, excl = [], [], [], 0
for c in CBS:
    bodies.append(dict(name=c["name"], country="Mauritius", registration_no=c["id"], phone=c["phone"],
                       email=c["email"], website=c["website"], address=c["address"], source_url=REG, verified_at=""))
    def add(std, ea, note):
        cert, acc = resolve_cert_number(c["id"], std)
        if not any(a["certificate_number"] == cert for a in accs):
            accs.append(dict(ab_code="MAURITAS", certificate_number=cert, body_name=c["name"], accreditation_standard=acc,
                             status="ACTIVE", issue_date=c["issue"], expiry_date=c["expiry"], proof_url=c["pdf"]))
        scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea, status="ACTIVE", scope_note=note))
    partial = "; ".join(f"EA {k}: except NACE {', '.join(v)}" for k, v in c["qms"].items() if v)
    add("ISO 9001", compress_ea_codes(c["qms"]), f"IAF ID1 sectors per schedule. Partial: {partial}")
    ea = sorted({e for k in c["fsms_cats"] for e in ISO22003_TO_EA[k]})
    add("ISO 22000", compress_ea_codes(ea), "ISO 22003-1 category C (C0, CI-CIV) mapped to EA")
    if c["isms"]:
        add("ISO/IEC 27001", "1-39", "No sector list in the MAURITAS register; recorded for all EA sectors (ISO/IEC 27001:2022)")
    excl += len(c["excluded"])
write_certifind_csvs(OUT, bodies, accs, scopes)
print(f"Excluded: {excl}")
