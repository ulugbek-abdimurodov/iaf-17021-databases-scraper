"""Convert OSA scope data to CertiFind CSVs. Values extracted from scope PDFs (F 9.1.29 V1)."""
from pathlib import Path
from certifind_common import compress_ea_codes, resolve_cert_number, write_certifind_csvs, SCHEME_ACCREDITATION_MAP

SRC = "https://www.osa.gob.sv/organismos-de-certificacion-acreditados/"
OUT = Path(__file__).resolve().parents[2] / "data" / "osa-el_salvador"

RECORDS = [
    {"name": "AENOR CONFÍA, S.A.U.", "reg": "OCA-01:07", "phone": "+503 2564 6507",
     "email": "aenorcentroamerica@aenor.com", "website": "https://www.aenorcentroamerica.com",
     "address": "Urb. Madre Selva II, Calle Conchagua Poniente #7, Antiguo Cuscatlán, La Libertad",
     "proof": "https://www.osa.gob.sv/descarga/aenor/", "issue": "2025-10-24", "expiry": "2028-10-23",
     "schemes": [("ISO 9001", [25, 28, 36])]},
    {"name": "Organismo Salvadoreño de Normalización", "reg": "OCA-01:15", "phone": "", "email": "",
     "website": "https://www.osn.gob.sv",
     "address": "Boulevard San Bartolo y Calle Lempa, Edificio CNC, Ilopango, San Salvador",
     "proof": "https://www.osa.gob.sv/descarga/osn/", "issue": "2024-07-31", "expiry": "2027-07-30",
     "schemes": [("ISO 9001", [17, 35, 36]), ("ISO 37001", [])]},
]

bodies, accs, scopes, excluded = [], [], [], []
for r in RECORDS:
    bodies.append({"name": r["name"], "country": "El Salvador", "registration_no": r["reg"], "phone": r["phone"],
                   "email": r["email"], "website": r["website"], "address": r["address"], "source_url": SRC, "verified_at": ""})
    seen = set()
    for std, ea in r["schemes"]:
        if std not in SCHEME_ACCREDITATION_MAP:
            excluded.append((r["name"], std)); continue
        cert, acc_std = resolve_cert_number(r["reg"], std)
        if cert not in seen:
            seen.add(cert)
            accs.append({"ab_code": "OSA", "certificate_number": cert, "body_name": r["name"], "accreditation_standard": acc_std,
                         "status": "active", "issue_date": r["issue"], "expiry_date": r["expiry"], "proof_url": r["proof"]})
        scopes.append({"certificate_number": cert, "certification_standard": std, "ea_codes": compress_ea_codes(ea),
                       "status": "active", "scope_note": "IAF/EA sectors as listed in the OSA scope annex"})

import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, accs, scopes)
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excluded)}")
