"""Scrape OUA (Uruguay) ISO/IEC 17065 product certification bodies (OCP) into raw_oua_17065.json.

Page: /organismos-de-certificacion-de-productos-ocp/ (the MS scraper reads the OCS page).
The MS scope parser expects management system columns (9001/14001/...), which product scopes
do not have, so this saves each OUAIMP034 scope PDF and its text lines instead.
"""
import io, json, re
from pathlib import Path
import pdfplumber, requests

BASE = "https://www.organismouruguayodeacreditacion.org"
PAGE = BASE + "/organismos-de-certificacion-de-productos-ocp/"
HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    html = requests.get(PAGE, timeout=60).text
    pdfs = sorted(set(re.findall(r'href="([^"]*\.pdf)"', html)))
    (HERE / "pdfs").mkdir(exist_ok=True)
    out = []
    for u in pdfs:
        b = requests.get(u, timeout=60).content
        name = u.rsplit("/", 1)[-1]
        (HERE / "pdfs" / name).write_bytes(b)
        lines = []
        if "OUAIMP034" in name:
            with pdfplumber.open(io.BytesIO(b)) as pdf:
                lines = [l.strip() for p in pdf.pages for l in (p.extract_text() or "").splitlines() if l.strip()]
        out.append({"url": u, "file": name, "kind": "scope" if "OUAIMP034" in name else "history", "lines": lines})
    (HERE / "raw_oua_17065.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"PDFs: {len(out)}  scope PDFs: {sum(o['kind']=='scope' for o in out)}  scope lines: {sum(len(o['lines']) for o in out)}")
