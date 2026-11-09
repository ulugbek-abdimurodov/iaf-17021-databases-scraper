from pathlib import Path
import pandas as pd
from pypdf import PdfReader

root = Path(__file__).resolve().parent
out = root / "dpa_output"
df = pd.read_csv(out / "dpa_accredited_bodies.csv", dtype=str).fillna("")
print("records", len(df), "documents", sum(bool(x) for x in df.download_path))
for idx in [0, 1, 6, 12, 63, 65, 90, 97]:
    row = df.iloc[idx]
    print("\n===", row.accreditation_code, row.company_name, "===")
    print("scope:", row.sector_scope)
    if not row.download_path:
        continue
    try:
        reader = PdfReader(row.download_path)
        pages = [(p.extract_text() or "") for p in reader.pages]
        text = "\n".join(pages)
        print("pages", len(reader.pages), "chars", len(text))
        print(text[:6000])
    except Exception as exc:
        print(type(exc).__name__, exc)
