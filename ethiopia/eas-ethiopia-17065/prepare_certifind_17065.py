"""EAS Ethiopia 17065 converter. Annexes are scans: lines come from annex_transcription.csv (read from rendered pages).
Usage: python prepare_certifind_17065.py <scrape out> <dataset dir>"""
import csv, json, re, sys
from pathlib import Path
here = Path(__file__).resolve().parent
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
raw = {r["registration_no"]: r for r in json.load(open(Path(sys.argv[1]) / "eas_17065_raw.json", encoding="utf8"))}
ms = list(csv.DictReader(open(out.parent / "eas-ethiopia/bodies.csv", encoding="utf8")))
ecae = next(b for b in ms if b["name"] == "Ethiopian Conformity Assessment Enterprise")  # reuse exactly
bless = dict(name="BLESS-AGRI-FOOD Laboratory PLC.", country="Ethiopia", registration_no="CPr0002", phone="+251 11 667 9231",
             email=raw["CPr0002"]["email"], website=raw["CPr0002"]["website"],
             address="Legetafo-Legedadi Sub-city, Sheger City Administration, Oromia, Ethiopia",
             source_url=raw["CPr0002"]["page"], verified_at="")
bodies = [ecae, bless]
H = dict(CPr0001=("Ethiopian Conformity Assessment Enterprise", "2025-09-30", "2030-03-30"),
         CPr0002=(bless["name"], "2026-04-02", "2030-10-02"))
accs = [dict(ab_code="EAS", certificate_number=k, body_name=n, accreditation_standard="ISO/IEC 17065", status="ACTIVE",
             issue_date=i, expiry_date=e, proof_url=raw[k]["annex_urls"][0]) for k, (n, i, e) in H.items()]
def refs(t):
    r = []
    for m in re.finditer(r"\b(CES|ES ISO|ES IEC|ES)\s?(\d+(?:-\d)?)(?::(\d{4}))?", t):
        s = f"{m.group(1)} {m.group(2)}" + (f":{m.group(3)}" if m.group(3) else "")
        if s not in r: r.append(s)
    return ";".join(r)
rows = []
for l in csv.DictReader(open(here / "annex_transcription.csv", encoding="utf8")):
    rows.append(dict(certificate_number=l["registration_no"], line_no=l["line_no"], scheme="", industry=l["industry"],
                     product_text=l["product_text"], product_text_en="", scheme_text=l["scheme_text"],
                     normative_docs=l["normative_docs"], standard_refs=refs(l["normative_docs"]), status="ACTIVE"))
def w(name, cols, data):
    with open(out / name, "w", newline="", encoding="utf8") as f:
        d = csv.DictWriter(f, cols); d.writeheader(); d.writerows(data)
w("bodies.csv", ["name","country","registration_no","phone","email","website","address","source_url","verified_at"], bodies)
w("accreditations.csv", ["ab_code","certificate_number","body_name","accreditation_standard","status","issue_date","expiry_date","proof_url"], accs)
w("scopes.csv", ["certificate_number","certification_standard","ea_codes","status","scope_note"], [])
w("product_scopes.csv", ["certificate_number","line_no","scheme","industry","product_text","product_text_en","scheme_text","normative_docs","standard_refs","status"], rows)
print(len(bodies), len(accs), len(rows))
