#!/usr/bin/env python3
"""ANAB (USA) 17065 scrape (anab_17065/) -> certifind/data/anab-usa-17065.

Imported: statusID 4 (accredited) only. Applicant (3) and scope-extension (7) lists repeat or precede an
accreditation; lists 1/5/6 carry no label on the page (suspended / withdrawn style lists) and are not imported.
Lines: the register's "Accredited Scopes" headings, saved as "parent > child" paths. A heading that has children
becomes the scheme_text of its children and is not a line itself; a heading without children is a line.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "anab_17065")
REGISTER = "https://anabpd.ansi.org/Accreditation/product-certification/AllDirectoryListing?prgID=1&statusID=4"

paths = {}
for r in c.rd(S / "scope_lines.csv"):
    paths.setdefault(r["registration_no"], []).append(r["product_text_raw"])

bodies, notes = [], []
for r in json.loads((S / "anab_17065_raw.json").read_text(encoding="utf-8")):
    if r["status"] != "accredited":
        notes.append(f"{r['registration_no']} {r['name']}: register list '{r['status']}' (statusID "
                     f"{r['status_id']}); not imported")
        continue
    reg = r["registration_no"]
    b = c.Body(reg=reg, name=r["name"], country=c.country_name(r["address"].split(",")[-1], "United States"),
               website=r["website"], address=r["address"], proof_url=(r["annex_urls"] or [r["url"]])[0],
               source_url=r["url"])
    ps = paths.get(reg, [])
    for i, p in enumerate(ps):
        if i + 1 < len(ps) and ps[i + 1].startswith(p + " > "):
            continue  # heading with children
        parts = p.split(" > ")
        b.lines.append(c.Line(product_text=parts[-1], scheme_text=" > ".join(parts[:-1])))
    if not b.lines:
        notes.append(f"{reg} {b.name}: no accredited scope listed in the register")
    bodies.append(b)
c.run("ANAB", "anab-usa-17065", "anab-usa", REGISTER, bodies, HERE / "anab_17065_review.md", TODAY,
      "ANSI/ANAB product certification directory (anabpd.ansi.org, Product Certification Accreditation Program, "
      "accredited list) and each organization's detail page (address, letter code, website, accreditation "
      "certificate, accredited scopes). The directory publishes no accreditation dates, so `issue_date` is the run "
      "date. Collected in a browser (Cloudflare check) with the collector in "
      "`database/usa/anab-usa_certifind/17065/scrape_us_anab_17065.py`; converter `prepare_certifind_17065.py`.",
      notes)
