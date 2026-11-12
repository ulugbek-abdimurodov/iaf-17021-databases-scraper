"""Convert caeq_raw.json to CertiFind CSVs. CAEQ accredits organic/appellation PRODUCT
certification bodies (ISO/IEC 17065, CAAQ/COR, EU 2018/848) only; no ISO/IEC 17021-1
schemes exist, so every body is excluded and logged in caeq_review.md."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import SCHEME_ACCREDITATION_MAP, write_certifind_csvs

OUT = Path(__file__).resolve().parents[2] / "data" / "caeq-canada"
raw = json.load(open(Path(__file__).parent / "caeq_raw.json", encoding="utf-8"))
bodies, accs, scopes, excluded = [], [], [], []
for r in raw:
    schemes = [a for a in r.get("APPELLATION(S)", []) if a in SCHEME_ACCREDITATION_MAP]
    if not schemes:
        excluded.append(r["name"]); continue
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, accs, scopes)
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excluded)}")
