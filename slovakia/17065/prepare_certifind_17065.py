#!/usr/bin/env python3
"""SNAS (Slovakia) 17065 scrape (snas_17065_output/) -> certifind/data/snas-slovakia-17065.

Field 6 "CAB Certifying Products". Lines: tables of the certificate's annex PDF (English file when published,
else Slovak; columns from the header). When no table line is found, the register's "accredited for" text
(English, else Slovak) is the single line. Only certificates on the valid list are imported.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "snas_17065_output")
files = defaultdict(list)
for f in c.rd(S / "files.csv"):
    if f["status"] == "downloaded" and f["path"].lower().endswith(".pdf"):
        files[f["certificate_no"]].append((0 if f["language"] == "en" else 1, S / f["path"]))
bodies, notes = [], []
for r in c.rd(S / "certificates.csv"):
    url = "https://ais.snas.sk/web-report"
    b = c.Body(reg=r["certificate_no"], name=r["body"], country="Slovakia", website=r["web"],
               address=r["address"].replace(", Slovenská republika", ""), issued=r["valid_from"], expiry=r["valid_to"],
               proof_url=url, source_url=url, active=r["status"] == "valid", status_note=r["status"])
    for _, pdf in sorted(files.get(r["certificate_no"], []))[:1]:
        b.lines, mode = c.pdf_lines(pdf)
    if not b.lines:
        text = r["accredited_for_en"] or r["accredited_for_sk"]
        if c.clean(text):
            notes.append(f"{b.reg} {b.name}: no annex table line; register 'accredited for' text used")
            b.lines = [c.Line(product_text=text)]
    bodies.append(b)
c.run("SNAS", "snas-slovakia-17065", "snas-slovakia", "https://ais.snas.sk/web-report",
      bodies, HERE / "snas_17065_review.md", TODAY,
      "SNAS register (ais.snas.sk web-report API), field 6 'CAB Certifying Products', and each certificate's "
      "published annex. Scraper `database/slovakia/17065/scrape_sk_snas_17065.py`; converter "
      "`prepare_certifind_17065.py`.", notes)
