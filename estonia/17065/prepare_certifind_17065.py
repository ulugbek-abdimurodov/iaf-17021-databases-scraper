#!/usr/bin/env python3
"""EAK (Estonia) 17065 scrape (eak_17065_data/) -> certifind/data/eak-estonia-17065.

Annex tables (scope_tables.csv) are bilingual Estonian/English; columns are mapped from each table header
(product / normative document / scheme or AVCP system) and carried to continuation tables. Bodies with no
annex on the register are not imported.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "eak_17065_data")
bodies = {}
for r in c.rd(S / "bodies.csv"):
    bodies[r["certificate_no"]] = c.Body(
        reg=r["certificate_no"], name=r["name"], country="Estonia", phone=r["phone"], email=r["email"],
        address=r["address"], issued=r["accreditation_effective"], expiry=r["accreditation_valid_until"],
        proof_url=r["source_url"], source_url=r["source_url"])
tables = defaultdict(list)
for r in c.rd(S / "scope_tables.csv"):
    tables[r["certificate_no"]].append(((r["annex"], int(r["page"]), int(r["table"]), int(r["row"])),
                                        [r[f"col{i}"] for i in range(1, 8)]))
for reg, tt in tables.items():
    if reg in bodies:
        lines, _ = c.rows_to_lines([cells for _, cells in sorted(tt)])
        bodies[reg].lines += lines
c.run("EAK", "eak-estonia-17065", "eak-estonia", "https://eak.ee/index_eng.php?pageId=32",
      list(bodies.values()), HERE / "eak_17065_review.md", TODAY,
      "EAK register list 'Product, process and service certification bodies' (pageId 32) and each body's annex PDF "
      "(tables extracted with pdfplumber). Scraper `database/estonia/17065/scrape_ee_eak_17065.py`; converter "
      "`prepare_certifind_17065.py`.")
