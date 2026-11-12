import json, sys
from pathlib import Path
from certifind_common import compress_ea_codes, resolve_cert_number, ISO22003_TO_EA, write_certifind_csvs
BASE = "https://www.organismouruguayodeacreditacion.org"
raw = json.load(open(Path(__file__).with_name("raw_oua.json"), encoding="utf-8"))
B, A, S = [], [], []
for b in raw["bodies"]:
    B.append(dict(name=b["name"], country="Uruguay", registration_no=b["ids"]["ISO 9001"], phone=b["phone"], email="",
                  website=b["website"], address=b["address"], source_url=raw["register_url"], verified_at=""))
    for std, base in b["ids"].items():
        cert, acc = resolve_cert_number(base, std)
        A.append(dict(ab_code="OUA", certificate_number=cert, body_name=b["name"], accreditation_standard=acc, status="active",
                      issue_date=b["cycle"][0], expiry_date=b["cycle"][1], proof_url=BASE + b["pdf"]))
        if std == "ISO 22000":
            cats = b["cat22000"]; ea = {e for c in cats for e in ISO22003_TO_EA[c[0]]}
            note = "Classified to EA from ISO 22003-1 categories " + ", ".join(cats)
        else:
            ea, note = b["ea"][std], ""
        S.append(dict(certificate_number=cert, certification_standard=std, ea_codes=compress_ea_codes(ea), status="active", scope_note=note))
out = Path(__file__).resolve().parents[2] / "data" / "oua-uruguay"
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(out, B, A, S)
print(f"Bodies: {len(B)}\nAccreditations: {len(A)}\nScopes: {len(S)}\nExcluded: 2 (SGS Uruguay forestry-only; LSQA suspended)")
