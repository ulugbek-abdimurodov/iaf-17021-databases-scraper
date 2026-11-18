#!/usr/bin/env python3
"""NA (Norway) 17065 scrape (no_17065_output/) -> certifind/data/na-norway-17065.

Scope rows: normative_docs = scheme heading (directive / regulation / national rule), product_text = column1
(product group or module), scheme_text = remark column.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "no_17065_output")
bodies = {}
for r in c.rd(S / "bodies.csv"):
    addr = c.clean(r["address"])
    country = c.country_name(addr.rsplit(",", 1)[-1], "Norway")
    bodies[r["ident"]] = c.Body(reg=r["ident"], name=r["company"], country=country, phone=r["phone"],
                                email=r["email"], website=r["website"],
                                address=addr.rsplit(",", 1)[0] if addr.endswith(country) else addr,
                                issued=r["started"], expiry=r["expires"], proof_url=r["url"], source_url=r["url"],
                                active=r["state"] == "Active", status_note=r["state"])
for r in c.rd(S / "scopes.csv"):
    if r["ident"] in bodies:
        bodies[r["ident"]].lines.append(c.Line(product_text=r["column1"] or r["column2"],
                                               normative_docs=r["scheme_title"], scheme_text=r["comment"]))
c.run("NA", "na-norway-17065", "na-norway",
      "https://www.akkreditert.no/en/akkrediterte-organisasjoner/?scope=ProdCert",
      list(bodies.values()), HERE / "na_17065_review.md", TODAY,
      "Norsk Akkreditering register, scope ProdCert (Product certification), record pages `/produkt/?AkkId=`. "
      "Scraper `database/norway/17065/scrape_no_akkreditert_17065.py`; converter `prepare_certifind_17065.py`.")
