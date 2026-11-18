#!/usr/bin/env python3
"""DANAK (Denmark) 17065 scrape (danak_17065_output/) -> certifind/data/danak-denmark-17065.

Per scheme: item rows give product (column1) and procedure/module (column2 -> scheme_text); a scheme with no
item rows contributes its detail statement. normative_docs = scheme title.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "danak_17065_output")
bodies = {}
for r in c.rd(S / "bodies.csv"):
    addr = c.clean(r["address"])
    country = c.country_name(addr.rsplit(",", 1)[-1], "Denmark")
    bodies[r["ident"]] = c.Body(reg=r["ident"], name=r["company"], country=country, phone=r["phone"],
                                email=r["email"], website=r["website"],
                                address=addr.rsplit(",", 1)[0] if "," in addr else addr,
                                issued=r["started"], expiry=r["expires"], proof_url=r["url"], source_url=r["url"],
                                active=r["state"] == "Accredited", status_note=r["state"])
by_scheme = defaultdict(list)
for r in c.rd(S / "scopes.csv"):
    by_scheme[(r["ident"], r["scheme_id"])].append(r)
for (ident, _), rows in by_scheme.items():
    b = bodies.get(ident)
    if not b:
        continue
    items = [r for r in rows if r["row_type"] == "item"]
    for r in items or rows[:1]:
        b.lines.append(c.Line(product_text=r["column1"], scheme_text=r["column2"] if items else "",
                              normative_docs=r["scheme_title"]))
c.run("DANAK", "danak-denmark-17065", "danak-denmark", "https://registry.danak.dk/registry",
      list(bodies.values()), HERE / "danak_17065_review.md", TODAY,
      "DANAK registry GraphQL API, cases with standard group 15 (DS/EN ISO/IEC 17065:2012). Scraper "
      "`database/denmark/17065/scrape_dk_danak_17065.py`; converter `prepare_certifind_17065.py`.")
