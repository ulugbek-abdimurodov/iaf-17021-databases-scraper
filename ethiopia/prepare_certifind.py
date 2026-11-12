from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location("esyd_prepare", Path(__file__).resolve().parent.parent / "greece/prepare_certifind.py")
_esyd = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_esyd)
FOOD_CATEGORIES = _esyd.FOOD_CATEGORIES
def esyd_expand(spec): return [int(x) for x in spec.split(";")]
from certifind_common import compress_ea_codes, resolve_cert_number, ISO22003_TO_EA, write_certifind_csvs
SRC = "https://eas-eth.org/certification-bodies/"
UP = "https://eas-eth.org/wp-content/uploads/2026/02/"
BODY = "Ethiopian Conformity Assessment Enterprise"
# Extracted from scanned certificate OCR layers (issue 03, issued 2026-01-16, expires 2030-07-16)
CERTS = [
    ("QMS0003", "ISO 9001", [1,2,3,4,5,6,7,8,9,10,12,13,14,15,16,17,18,19,23,28,29,30,31,32,33,34,35,36,37], "QMS-Scanned-Certificate.pdf", ""),
    ("EMS0001", "ISO 14001", [2,3,12,13,14,15,16,17,27,28,30,34], "EMS-Scanned-Certificate.pdf", ""),
    ("OHSMS0001", "ISO 45001", [2,3,14,17,28,30,34], "OHSMS-Scanned-Certificate.pdf", ""),
    ("FSMS0001", "ISO 22000", sorted({e for c in "BCI" for e in esyd_expand(FOOD_CATEGORIES[c])}), "Fsms-scanned-certificate.pdf",
     "Classified to EA from ISO 22003-1 categories B, C, I"),
]
bodies = [dict(name=BODY, country="Ethiopia", registration_no="QMS0003", phone="+251 11 878 7517",
               email="info-ccmd@ecae.org.et", website="https://ecae.org.et",
               address="Bole Sub City, Megenagna, beside AMCE, P.O. Box 11145, Addis Ababa", source_url=SRC, verified_at="")]
accs, scopes = [], []
for cid, std, ea, pdf, note in CERTS:
    num, acc = resolve_cert_number(cid, std)
    if acc == "ISO/IEC 17021-1":
        num = "QMS0003"  # uq_cb_ab_standard: merge EMS/OHSMS registrations into the first 17021-1 row
        note = (note + "; " if note else "") + f"EAS certificate {cid}" if cid != num else note
    if any(a["certificate_number"] == num for a in accs):
        scopes.append(dict(certificate_number=num, certification_standard=std, ea_codes=compress_ea_codes(ea), status="ACTIVE", scope_note=note))
        continue
    accs.append(dict(ab_code="EAS", certificate_number=num, body_name=BODY, accreditation_standard=acc, status="ACTIVE",
                     issue_date="2026-01-16", expiry_date="2030-07-16", proof_url=UP + pdf))
    scopes.append(dict(certificate_number=num, certification_standard=std, ea_codes=compress_ea_codes(ea), status="ACTIVE", scope_note=note))
import sys
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "certifind/data/eas-ethiopia"
write_certifind_csvs(out, bodies, accs, scopes)
print("Excluded: 3 (EOMS0001 ISO 21001; CPr0001, CPr0002 ISO/IEC 17065)")
