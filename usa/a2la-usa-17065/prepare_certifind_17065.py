#!/usr/bin/env python3
"""A2LA (USA) 17065 scrape (a2la_17065/) -> certifind/data/a2la-usa-17065.

One accreditation per A2LA certificate number (e.g. 3297.01). Lines: the "Certification Scheme | Product Type /
Category | Standards / Requirements" table of the "Accreditation Scope & Certificate" PDF (pdfplumber tables; an
empty scheme cell repeats the one above). Without a table, the PDF text lines from scope_lines.csv are used.
A2LA has no management-system program, so there is no MS dataset to share numbers with.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "a2la_17065")
REGISTER = "https://customer.a2la.org/index.cfm?event=directory.index"


def fill_down(lines):
    last = ""
    for ln in lines:
        ln.scheme_text = ln.scheme_text or last
        last = ln.scheme_text
    return lines


scope = {}
for r in c.rd(S / "scope_lines.csv"):
    scope.setdefault(r["registration_no"], []).append(r["product_text_raw"])

bodies, notes = [], []
for r in json.loads((S / "a2la_17065_raw.json").read_text(encoding="utf-8")):
    reg = r["registration_no"]
    b = c.Body(reg=reg, name=r["name"], country=c.country_name(r.get("country", ""), "United States"),
               phone=r["phone"], email=r["email"], website=r["website"], address=r["address"], issued=r["issued"],
               expiry=r["expiry"], proof_url=(r["annex_urls"] or [""])[0],
               source_url=f"https://customer.a2la.org/index.cfm?event=directory.detail&labPID={r['id']}")
    if "C1" not in r.get("status", "") and "C2" not in r.get("status", "") and "Available" not in r.get("status", ""):
        notes.append(f"{reg} {r['name']}: commercial code '{r.get('status')}'")
    for pdf in sorted(S.glob(f"annexes/{reg}_*.pdf")):
        lines, mode = c.pdf_lines(pdf)
        b.lines += fill_down(lines)
    if not b.lines:
        notes.append(f"{reg} {b.name}: no scope table in the PDF; text lines used")
        b.lines = c.text_to_lines("\n".join(scope.get(reg, [])))
    bodies.append(b)

c.run("A2LA", "a2la-usa-17065", None, REGISTER, bodies, HERE / "a2la_17065_review.md", TODAY,
      "A2LA directory, program 87 \"ISO/IEC 17065:2012 Product Certification Bodies\" (all commercial statuses), "
      "each lab's detail page and its \"Accreditation Scope & Certificate\" PDF. `issue_date` is the certificate's "
      "\"Presented this ... day of\" date, `expiry_date` the directory expiration date. Scraper "
      "`database/usa/a2la-usa-17065/scrape_us_a2la_17065.py`; converter `prepare_certifind_17065.py`.", notes)
