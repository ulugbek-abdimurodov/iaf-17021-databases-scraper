#!/usr/bin/env python3
"""NABCB (India) 17065 scrape (nabcb_17065_output/) -> certifind/data/nabcb-india-17065.

scope_rows.csv: header rows define the columns (products / scheme / normative documents); "IAF Scope NN" rows
and section rows are headings, not lines. The "(Accreditation was not valid during ...)" note is removed
from body names.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "nabcb_17065_output")
bodies = {}
for r in c.rd(S / "accreditations.csv"):
    addr = c.clean(r["address"])
    bodies[r["certificate_no"]] = c.Body(
        reg=r["certificate_no"], name=re.sub(r"\s*\(\s*accreditation was not valid.*$", "", r["name"], flags=re.I),
        country=c.country_name(addr.rsplit(",", 1)[-1], "India"), phone=r["tel"], email=r["email"],
        website=r["website"], address=addr, issued=c.iso_date(r["initial_issue_date"]),
        expiry=c.iso_date(r["valid_upto"] or r["listing_valid_upto"]), proof_url=r["detail_url"],
        source_url=r["detail_url"], active=r["status"] == "Active", status_note=r["status"])
rows = defaultdict(list)
for r in c.rd(S / "scope_rows.csv"):
    rows[r["certificate_no"]].append([r["col1"], r["col2"], r["col3"], r["col4"]])
for reg, rr in rows.items():
    if reg in bodies:
        lines, _ = c.rows_to_lines(rr, {0: "product", 1: "norm"})
        bodies[reg].lines += [l for l in lines if not re.match(r"^(IAF Scope\s*\d|●)", l.product_text)]
c.run("NABCB", "nabcb-india-17065", "nabcb-india", "https://nabcb.qci.org.in/product-certification/",
      list(bodies.values()), HERE / "nabcb_17065_review.md", TODAY,
      "NABCB directory page Product Certification Bodies and each body's detail page (scope table). Scraper "
      "`database/india/17065/scrape_in_nabcb_17065.py`; converter `prepare_certifind_17065.py`.")
