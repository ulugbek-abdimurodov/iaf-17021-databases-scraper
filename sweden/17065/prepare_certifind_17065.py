#!/usr/bin/env python3
"""Swedac ISO/IEC 17065 scrape (se_17065_output/) -> certifind/data/swedac-sweden-17065.

Scope rows: only rows under SS-EN ISO/IEC 17065 (`in_17065_scope` = yes).
- "Certification of products": product_text = product group (column1) + product (column4) when different,
  normative_docs = standard (column2), scheme_text = certification rules (column3).
- "Notification, Notified/Designated body": normative_docs = directive/regulation (column1), scheme_text =
  module (column3), product_text = product group and product (column4, column5). Article rows collapse.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import csv, sys
from datetime import date
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--today"]
SCRAPE = Path(args[0]) if args else HERE / "se_17065_output"
TODAY = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else date.today().isoformat()
rd = lambda n: list(csv.DictReader(open(SCRAPE / n, encoding="utf-8-sig")))

bodies = {}
for r in rd("bodies.csv"):
    addr = c.clean(r["address"])
    country = c.country_name(addr.rsplit(",", 1)[-1], "Sweden")
    bodies[r["ident"]] = c.Body(reg=r["ident"], name=r["company"], country=country, phone=r["phone"],
                                email=r["email"], website=r["website"], address=addr.rsplit(",", 1)[0] if country else addr,
                                issued=c.iso_date(r["started"]) or r["latest_decision_date"], expiry=c.iso_date(r["expires"]), proof_url=r["url"],
                                source_url=r["url"], active=r["state"].lower() == "active", status_note=r["state"])
for r in rd("scopes.csv"):
    if r["in_17065_scope"] != "yes" or r["ident"] not in bodies:
        continue
    g = lambda k: c.clean(r.get(k, ""))
    if r["control_form_code"] == "cert-produkter":
        prod = g("column1") if g("column4") in ("", g("column1")) else f"{g('column1')}: {g('column4')}"
        ln = c.Line(product_text=prod, normative_docs=g("column2"), scheme_text=g("column3"))
    else:
        prod = " - ".join(x for x in (g("column4"), g("column5")) if x)
        ln = c.Line(product_text=prod or g("scheme_title"), normative_docs=g("column1"), scheme_text=g("column3"))
    bodies[r["ident"]].lines.append(ln)

c.run("SWEDAC", "swedac-sweden-17065", "swedac-sweden", "https://ackrediteringar.swedac.se/en",
      list(bodies.values()), HERE / "swedac_17065_review.md", TODAY,
      "Swedac register JSON API, standard filter `iso-17065-2012` (SS-EN ISO/IEC 17065:2012). Scraper "
      "`database/sweden/17065/scrape_se_swedac_17065.py`; converter `prepare_certifind_17065.py` next to it. Scope rows "
      "outside ISO/IEC 17065 (17021-1 lines of the same accreditation) are ignored.")
