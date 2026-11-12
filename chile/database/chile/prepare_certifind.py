import csv, re, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import resolve_cert_number, write_certifind_csvs

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "inn-chile"
SRC = "https://directorio.inn.cl/"
PDF = "https://directorio.inn.cl/Directorio/DisplayPDF/"
STD = {"ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001:2018": "ISO 45001",
       "NCh-ISO IEC 27001:2023": "ISO/IEC 27001", "ISO 50001": "ISO 50001"}
NAMES = {"SGS CHILE LTDA.": "SGS Chile Ltda.", "Lgai Chile S.A": "LGAI Chile S.A.",
         "Bureau Veritas Certification Chile S.A": "Bureau Veritas Certification Chile S.A.",
         "SCI CERTIFICACIONES LIMITADA": "SCI Certificaciones Limitada",
         "ASR CERTIFICACIONES LIMITADA": "ASR Certificaciones Limitada"}
d = lambda s: datetime.strptime(s, "%d-%m-%Y").strftime("%Y-%m-%d")

bodies, accs, scopes, excl = {}, [], [], []
for code, name, city, area, phone, f, t, st, tok in csv.reader(open(HERE / "inn_raw.tsv", encoding="utf-8"), delimiter="\t"):
    name = NAMES.get(name, name); area = area.strip(); reg = code.replace(" ", "")
    if area not in STD:
        excl.append((code, name, area)); continue
    cs = STD[area]
    cert, acc_std = resolve_cert_number(reg, cs)
    status = "active" if st == "Vigente" else "suspended"
    bodies.setdefault(name, dict(name=name, country="Chile", registration_no=reg, phone=phone,
                      email="", website="", address=f"{city}, Chile", source_url=SRC, verified_at=""))
    accs.append(dict(ab_code="INN", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                     status=status, issue_date=d(f), expiry_date=d(t), proof_url=PDF + tok if tok else SRC))
    scopes.append(dict(certificate_number=cert, certification_standard=cs, ea_codes="", status=status,
                       scope_note="EA codes not published in INN register listing; see accreditation certificate PDF"))
excluded_bodies = sorted({n for _, n, _ in excl} - set(bodies))
with open(HERE / "inn_review.md", "w", encoding="utf-8") as fh:
    fh.write("# INN Chile review\n\n## Skipped schemes (out of ISO/IEC 17021-1 MS scope)\n\n| Code | Body | Scheme |\n|---|---|---|\n")
    fh.writelines(f"| {c} | {n} | {a} |\n" for c, n, a in excl)
    fh.write("\n## Bodies excluded (only out-of-scope schemes)\n\n" + "".join(f"- {n}\n" for n in excluded_bodies))
    fh.write("\n## Notes\n\n- Register gives commune only (no street address/email/website); EA codes left empty (annex PDFs not parsed: workspace cannot reach directorio.inn.cl).\n- SC 048 (IRAM) shows Vigente with expiry 2025-05-10 — out of scope anyway.\n")
write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
print(f"Excluded: {len(excl)} schemes, {len(excluded_bodies)} bodies")
