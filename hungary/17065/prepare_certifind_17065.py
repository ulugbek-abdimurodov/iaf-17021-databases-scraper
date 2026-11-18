#!/usr/bin/env python3
"""NAH (Hungary) 17065 scrape (nah_17065_output/) -> certifind/data/nah-hungary-17065.

Scope = the register's "scope_and_notes" text (Hungarian). The opening "... szerint akkreditálva:" statement is
dropped; a line ending with ':' is a heading carried down as scheme_text of the items under it. Only ACTIVE
accreditations are imported.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

import re  # noqa: E402

S, TODAY = c.cli(HERE / "nah_17065_output")
NOTES = re.compile(r"Nemzeti Akkreditáló Hatóság|határozatával|címváltozás|névváltozás|átvezetése|státusz|"
                   r"akkreditált (terület|tanúsítási).{0,40}megnevezése|^\d{4}\. \w+ \d+\.", re.I)
bodies = []
for r in c.rd(S / "organizations.csv"):
    b = c.Body(reg=r["nah_number"], name=r["name"], country="Hungary", phone=r["phone"], email=r["email"],
               website=r["web"], address=r["location"], issued=r["valid_from"], expiry=r["valid_to"],
               proof_url=r["page_url"], source_url=r["page_url"], active=r["status"] == "ACTIVE",
               status_note=r["status"])
    # register history notes ("... Nemzeti Akkreditáló Hatóság által ... kiadott határozatával elrendelt ...",
    # name/address change, status) are not scope
    b.lines = [l for l in c.text_to_lines(r["scope_and_notes"])
               if not NOTES.search(f"{l.scheme_text} {l.product_text}")]
    bodies.append(b)
c.run("NAH", "nah-hungary-17065", "nah-hungary", "https://nah.gov.hu/hu/kategoriak/termektanusitas--product-certification/",
      bodies, HERE / "nah_17065_review.md", TODAY,
      "NAH register category Terméktanúsítás / Product certification (API `/admin/api/content/hu/kategoriak/"
      "termektanusitas--product-certification/`), each organisation's scope text. Scraper "
      "`database/hungary/17065/scrape_hu_nah_17065.py`; converter `prepare_certifind_17065.py`.")
