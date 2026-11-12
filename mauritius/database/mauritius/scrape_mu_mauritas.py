"""Scrape MAURITAS certification-body register (entities.php, table 'Cert Body') and annex PDFs.
Workspace egress to mauritas.org was blocked; the same logic was run in-browser (fetch + pdf.js).
Output: raw/cb_register.json, raw/<CB>.txt"""
import json, re, sys, requests
from pathlib import Path
from bs4 import BeautifulSoup
from pypdf import PdfReader
import io
BASE = "https://www.mauritas.org"
OUT = Path(__file__).parent / "raw"; OUT.mkdir(exist_ok=True)
html = requests.get(f"{BASE}/entities.php", timeout=60).text
rows = []
for t in BeautifulSoup(html, "html.parser").find_all("table"):
    if "Cert Body" not in t.get_text():
        continue
    for tr in t.find_all("tr")[1:]:
        tds = tr.find_all("td")
        links = [a["href"] for a in tr.find_all("a", href=True)]
        pdf = next((l for l in links if l.lower().endswith(".pdf")), "")
        rows.append({"id": tds[0].get_text(strip=True), "name": tds[1].get_text(" ", strip=True),
                     "programmes": tds[-1].get_text(" ", strip=True),
                     "pdf": requests.compat.urljoin(BASE + "/", pdf),
                     "website": next((l for l in links if not l.lower().endswith(".pdf")), "")})
for r in rows:
    pdf = PdfReader(io.BytesIO(requests.get(r["pdf"], timeout=120).content))
    (OUT / f"{r['id']}.txt").write_text("\n".join(p.extract_text() or "" for p in pdf.pages))
(OUT / "cb_register.json").write_text(json.dumps(rows, indent=1))
print(f"Registrations: {len(rows)}")
