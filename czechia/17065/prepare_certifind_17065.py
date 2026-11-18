#!/usr/bin/env python3
"""CAI (Czechia) 17065 scrape (cai_17065_output/) -> certifind/data/cai-czechia-17065.

Lines: tables of the English annex PDF (<certificate>_EN.pdf; columns from the table header: product /
certification scheme / standards). When the annex gives no table line (missing or failed download), the
register's Czech scope summary is the single line.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "cai_17065_output")
info = {r["entry_slug"]: r for r in c.rd(S / "bodies.csv")}
bodies, notes = [], []
for r in c.rd(S / "certificates.csv"):
    b0 = info.get(r["entry_slug"], {})
    url = f"https://www.cai.cz/?page_id=4499&kategorie_subjektu=certifikacni-organy-certifikujici-produkty"
    b = c.Body(reg=r["cab_number"], name=r["name"], country="Czechia", address=b0.get("address", ""),
               website=b0.get("website", ""), issued=r["issued"], expiry=r["valid_until"], proof_url=url,
               source_url=url)
    pdf = S / "pdfs" / r["entry_slug"] / (r["certificate_number"].replace("/", "_") + "_EN.pdf")
    if pdf.exists():
        b.lines, mode = c.pdf_lines(pdf)
        if not b.lines:
            notes.append(f"{b.reg} {b.name}: no table line in {pdf.name} ({mode}); register summary used")
    else:
        notes.append(f"{b.reg} {b.name}: English annex not downloaded; register summary used")
    if not b.lines and c.clean(r["scope_summary_cs"]):
        b.lines = [c.Line(product_text=r["scope_summary_cs"])]
    bodies.append(b)
c.run("CAI", "cai-czechia-17065", "cai-czechia",
      "https://www.cai.cz/?page_id=4499&kategorie_subjektu=certifikacni-organy-certifikujici-produkty",
      bodies, HERE / "cai_17065_review.md", TODAY,
      "CAI register category 'Certifikační orgány certifikující produkty' and each certificate's English annex PDF "
      "(tables read with pdfplumber). Scraper `database/czechia/17065/scrape_cz_cai_17065.py`; converter "
      "`prepare_certifind_17065.py`.", notes)
