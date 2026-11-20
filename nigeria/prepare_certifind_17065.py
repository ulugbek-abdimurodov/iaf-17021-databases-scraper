"""NiNAS ISO/IEC 17065 dataset. One body (TGSB-CB), annex transcribed from _raw_17065/*.txt."""
import csv, json, sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent.parent / "certifind" / "data" / "ninas-nigeria-17065"
OUT.mkdir(parents=True, exist_ok=True)
raw = json.loads((HERE / "_raw_17065" / "ninas_17065_raw.json").read_text(encoding="utf8"))[0]
NAME = "The Gambia Standards Bureau Certification Body (TGSB-CB)"
SCHEME = "TGSB-PC-01: Scheme Rules for the ECOSTAND 100 - ECOWAS Standards for Good Practices in Agriculture and Processing. Certification of Dried Fruit Products (Type 5)"
LINES = [  # (standard/specification, product) in annex order
    ("ECOSTAND 100 - ECOWAS Standards for Good Practices in Agriculture and Processing", "Dried Mango", "ECOSTAND 100"),
    ("GAMS 26:2020 - Dried Fruits - Specification", "Dried Mango", "GAMS 26:2020"),
    ("GAMS 23:2022 - Food Hygiene and Processing Requirements", "Dried Mango", "GAMS 23:2022"),
]
def w(name, header, rows):
    with open(OUT / name, "w", encoding="utf8", newline="") as f:
        c = csv.writer(f, lineterminator="\n"); c.writerow(header); c.writerows(rows)
w("bodies.csv", "name,country,registration_no,phone,email,website,address,source_url,verified_at".split(","),
  [[NAME, "The Gambia", "", "", raw["email"], "", raw["address"], "https://ninas.ng/accreditation/accredited-product-bodies/", ""]])
w("accreditations.csv", "ab_code,certificate_number,body_name,accreditation_standard,status,issue_date,expiry_date,proof_url".split(","),
  [["NINAS", "PR0001", NAME, "ISO/IEC 17065", "ACTIVE", "2025-11-21", "2027-11-20", raw["pdf"]]])
w("scopes.csv", "certificate_number,certification_standard,ea_codes,status,scope_note".split(","), [])
w("product_scopes.csv", "certificate_number,line_no,scheme,industry,product_text,product_text_en,scheme_text,normative_docs,standard_refs,status".split(","),
  [["PR0001", i, "", "food", prod, "", SCHEME, std, ref, "ACTIVE"] for i, (std, prod, ref) in enumerate(LINES, 1)])
print("1 body, 1 accreditation,", len(LINES), "lines")
