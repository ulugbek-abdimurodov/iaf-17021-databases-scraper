#!/usr/bin/env python3
"""NAAU (Ukraine) 17065 scrape (naau_17065_bodies/) -> certifind/data/naau-ukraine-17065.

Register XLSX "17065": one row per body with a scope summary (Ukrainian; English when the English DOC matched).
Lines: the scope summary split on ';' / new lines (verbatim). Annex PDFs (Google Drive links) are mostly scans
and are not read. Only status "active" is imported. Name: English when given, else Ukrainian.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "naau_17065_bodies")
URL = "https://naau.org.ua/3-reiestr-akreditovanikh-oov"
bodies = []
for r in c.rd(S / "bodies.csv"):
    b = c.Body(reg=r["certificate_no"], name=r["name_en"] or r["name_uk"], country="Ukraine",
               phone=(r["phones"] or "").split(",")[0], issued=r["current_valid_from"] or r["first_accredited"],
               expiry=r["current_valid_to"], proof_url=r["scope_url"] or URL, source_url=URL,
               active=r["status"] == "active", status_note=r["status"])
    text = r["scope_summary_uk"]
    en = r["scope_summary_en"]
    parts = [p for p in re.split(r";\s*|\n+", text) if c.clean(p)]
    b.lines = [c.Line(product_text=p, product_text_en=en if len(parts) == 1 else "") for p in parts]
    bodies.append(b)
c.run("NAAU", "naau-ukraine-17065", "naau-ukraine", URL, bodies, HERE / "naau_17065_review.md", TODAY,
      "NAAU register page, row 'Органи з сертифікації продукції, процесів та послуг (ДСТУ EN ISO/IEC 17065)': "
      "Ukrainian XLSX (17065_18_11_2026.xlsx) and English DOC. Scope = the register's scope summary column. "
      "Scraper `database/ukraine/17065/scrape_ua_naau_17065.py`; converter `prepare_certifind_17065.py`.")
