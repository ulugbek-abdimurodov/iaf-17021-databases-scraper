#!/usr/bin/env python3
"""PCA (Poland) 17065 scrape (pca_17065_bodies/) -> certifind/data/pca-poland-17065.

Scope rows: product_text = scheme description from the register (raw_text), normative_docs = standard.
Body name = organization (as in pca-poland). Lines flagged suspended by the register get status SUSPENDED.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "pca_17065_bodies")
bodies = {}
for r in c.rd(S / "bodies.csv"):
    bodies[r["accreditation_number"]] = c.Body(
        reg=r["accreditation_number"], name=r["organization"], country="Poland", phone=r["phone"],
        email=r["email"], website=r["website"], address=r["organization_address"].replace(";", ","),
        issued=r["granted_on"], expiry=r["valid_until"], proof_url=r["detail_url"], source_url=r["detail_url"])
for r in c.rd(S / "scopes.csv"):
    b = bodies.get(r["accreditation_number"])
    if b:
        b.lines.append(c.Line(product_text=r["raw_text"] or r["scheme"], normative_docs=r["standard"],
                              status="SUSPENDED" if r["flagged_suspended"] == "True" else "ACTIVE"))
c.run("PCA", "pca-poland-17065", "pca-poland",
      "https://www.pca.gov.pl/en/accredited-organizations/accredited-organizations/product-certification-bodies",
      list(bodies.values()), HERE / "pca_17065_review.md", TODAY,
      "PCA register, section Product certification bodies (that section's search endpoint). Scraper "
      "`database/poland/17065/scrape_pl_pca_17065.py`; converter `prepare_certifind_17065.py`.")
