#!/usr/bin/env python3
"""IARM (North Macedonia) 17065 scrape (iarm_17065_products/) -> certifind/data/iarm-north-macedonia-17065.

English register pages only (category cb_products). Scope = the register's scope text (scopes.csv `standard`
column, one or more paragraphs per body). The suffix "Product certification body" is removed from names.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "iarm_17065_products")
scopes = defaultdict(list)
for r in c.rd(S / "scopes.csv"):
    for part in re.split(r"\n+|;\s*(?=[A-Z])", r["standard"] + ("\n" + r["description"] if r["description"] else "")):
        if c.clean(part):
            scopes[r["certificate"]].append(c.Line(product_text=part))
bodies = []
for r in c.rd(S / "bodies.csv"):
    name = re.sub(r"\s*product certification body\s*$", "", r["name_en"], flags=re.I)
    b = c.Body(reg=r["certificate"], name=name, country="North Macedonia", website=r["website"],
               address=r["address_en"], issued=r["first_accreditation"], expiry=r["valid_until"],
               proof_url=r["page_en"], source_url=r["page_en"], active=r["status"] == "active",
               status_note=r["status"])
    b.lines = scopes.get(r["certificate"], [])
    bodies.append(b)
c.run("IARM", "iarm-north-macedonia-17065", "iarm-north-macedonia", "https://iarm.gov.mk/en/category/cb_products/",
      bodies, HERE / "iarm_17065_review.md", TODAY,
      "IARM register, English category 'CB for products, processes and services' (cb_products). The Macedonian and "
      "Albanian lists were not read. Scraper `database/macedonia/17065/scrape_mk_iarm_17065.py`; converter "
      "`prepare_certifind_17065.py`.")
