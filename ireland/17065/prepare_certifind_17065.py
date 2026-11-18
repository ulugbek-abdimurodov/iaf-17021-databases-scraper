#!/usr/bin/env python3
"""INAB (Ireland) 17065 scrape (inab_17065_output/) -> certifind/data/inab-ireland-17065.

Lines: the scope table of each body's scope PDF (columns from its header: category / standard or scheme /
product details); the sites table is ignored. When the PDF gives no table line, the register summary is the line.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "inab_17065_output")
bodies, notes = [], []
for r in c.rd(S / "bodies.csv"):
    b = c.Body(reg=r["accreditation_number"], name=r["name"], country="Ireland", phone=r["phone"], email=r["email"],
               website=r["website"], address=r["address"], proof_url=r["detail_url"], source_url=r["detail_url"])
    pdfs = sorted(S.glob(f"documents/{r['accreditation_number']}-*/*_scope.pdf"))
    for pdf in pdfs:
        lines, mode = c.pdf_lines(pdf)
        b.lines += lines
    if not b.lines:
        notes.append(f"{b.reg} {b.name}: no table line in the scope PDF; register summary used")
        b.lines = [c.Line(product_text=r["summary"])] if c.clean(r["summary"]) else []
    bodies.append(b)
c.run("INAB", "inab-ireland-17065", "inab-ireland",
      "https://www.inab.ie/inab-directory/certification-bodies/product-certification/",
      bodies, HERE / "inab_17065_review.md", TODAY,
      "INAB directory, Certification Bodies > Product Certification, and each body's scope PDF. INAB publishes no "
      "accreditation dates on the directory, so `issue_date` is the run date. Scraper "
      "`database/ireland/17065/scrape_ie_inab_17065.py`; converter `prepare_certifind_17065.py`.", notes)
