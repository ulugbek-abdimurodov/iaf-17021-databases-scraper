#!/usr/bin/env python3
"""IPAC (Portugal) 17065 scrape (ipac_17065_data/) -> certifind/data/ipac-portugal-17065.

Scope rows with certification criteria (extent) are lines: product_text = description, normative_docs = extent.
Rows without criteria are IPAC sector headings ("Produtos alimentares...") and are not imported; the column
header row "Produto (Product)" is skipped.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "ipac_17065_data")
bodies = {}
for r in c.rd(S / "bodies.csv"):
    bodies[r["accreditation_no"]] = c.Body(
        reg=r["accreditation_no"], name=r["legal_name"], country="Portugal", phone=r["phone"], email=r["email"],
        address=r["address"], issued=r["granted"], proof_url=r["profile_url"], source_url=r["profile_url"])
headings = 0
for r in c.rd(S / "scope.csv"):
    b = bodies.get(r["accreditation_no"])
    if not b or r["description"].startswith("Produto (Product)"):
        continue
    if not c.clean(r["extent"]):
        headings += 1
        continue
    b.lines.append(c.Line(product_text=r["description"], normative_docs=r["extent"]))
c.run("IPAC", "ipac-portugal-17065", "ipac-portugal", "https://www.ipac.pt/pesquisa/acredita.asp",
      list(bodies.values()), HERE / "ipac_17065_review.md", TODAY,
      "IPAC register, scheme filter 17065 (Products, Processes and Services Certification Bodies), profile pages "
      "`ficha_ocp.asp`. Scraper `database/portugal/17065/scrape_pt_ipac_17065.py` (runs ipac_scraper.py "
      f"--scheme 17065); converter `prepare_certifind_17065.py`. {headings} sector heading rows (no criteria) are "
      "not imported.")
