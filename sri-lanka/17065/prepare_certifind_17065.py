#!/usr/bin/env python3
"""SLAB (Sri Lanka) 17065 scrape (slab_17065_raw.tsv + pdfs/) -> certifind/data/slab-sri-lanka-17065.

slab_17065_raw.tsv: accreditation no, name, website, issue, expiry, scope file (directory tag 7,
"Certification bodies - Product", active only). Lines: tables of the scope PDF (columns from the header).
When only the accreditation certificate is published, its "accredited ... under the fields of" text is the line.
Usage: python prepare_certifind_17065.py [raw_tsv] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

RAW, TODAY = c.cli(HERE / "slab_17065_raw.tsv")
URL = "https://www.slab.lk/directory?selectedTags[1]=7&selectedStatus=active"
bodies, notes = [], []
for row in RAW.read_text(encoding="utf-8").splitlines():
    f = row.split("\t")
    if len(f) < 6:
        continue
    acc, name, web, issued, expiry, scope = f[:6]
    fname = scope if scope.lower().endswith(".pdf") else scope + ".pdf"
    pdf = HERE / "pdfs" / fname
    b = c.Body(reg=acc, name=name, country="Sri Lanka", website=web, issued=issued, expiry=expiry,
               proof_url=f"https://www.slab.lk/media/file/{fname}", source_url=URL)
    if pdf.exists():
        b.lines, mode = c.pdf_lines(pdf)
        if not b.lines:
            rows, _ = c.pdf_rows(pdf)
            text = [r[0] for r in rows if r]
            i = next((k for k, t in enumerate(text) if re.search(r"under the fields? of", t, re.I)), None)
            if i is not None:
                field = []
                for t in text[i + 1:i + 4]:
                    if re.match(r"(and has been|Type \d)", t, re.I):
                        continue
                    if re.match(r"(and has been assigned|This certificate)", t, re.I):
                        break
                    field.append(t)
                if field:
                    b.lines = [c.Line(product_text=field[0], normative_docs=" ".join(field[1:]).strip("()"))]
                    notes.append(f"{acc} {name}: no scope table; accredited field taken from the certificate")
    if not b.lines:
        notes.append(f"{acc} {name}: no scope line found")
    bodies.append(b)
c.run("SLAB", "slab-sri-lanka-17065", "slab-sri-lanka", URL, bodies, HERE / "slab_17065_review.md", TODAY,
      "SLAB directory, tag 7 'Certification bodies - Product (CP)', active records, and each record's scope PDF. "
      "Scraper `database/sri-lanka/17065/scrape_lk_slab_17065.py`; converter `prepare_certifind_17065.py`.", notes)
