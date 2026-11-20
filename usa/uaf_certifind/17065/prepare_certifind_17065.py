#!/usr/bin/env python3
"""UAF (USA) 17065 scrape (uaf_17065/) -> certifind/data/uaf-united-states-17065.

Lines: the scope table of the "Certificate and Schedule" PDF (S. No | Certification Standard / Scheme | Product /
Process / Service Category | IAF code | Normative document | Conditions); without a table, the register clusters.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "uaf_17065")
REGISTER = "https://www.uafaccreditation.org/directory/listofAccreditedCabs"
bodies, notes = [], []
for r in json.loads((S / "uaf_17065_raw.json").read_text(encoding="utf-8")):
    b = c.Body(reg=r["registration_no"], name=r["name"], country=c.country_name(r["address"].split(",")[-1]),
               phone=r["phone"], email=r["email"], website=r["website"], address=r["address"], issued=r["issued"],
               expiry=r["expiry"], proof_url=(r["annex_urls"] or [""])[0], source_url=REGISTER,
               active=r.get("status") == "active", status_note=r.get("status", ""))
    for pdf in sorted(S.glob("annexes/*.pdf")):
        if pdf.name.split("_")[0].lower() in r["name"].lower():
            b.lines += c.pdf_lines(pdf)[0]
    if not b.lines:
        notes.append(f"{b.reg} {b.name}: no scope table in the PDF; register clusters used")
        b.lines = [c.Line(product_text=cl, scheme_text=s["scheme"]) for s in r["schemes"] for cl in s["clusters"]]
    bodies.append(b)
c.run("UAF", "uaf-united-states-17065", "uaf-united-states", REGISTER, bodies, HERE / "uaf_17065_review.md", TODAY,
      "UAF API, programme \"Product Certification Bodies\" (271dd4e3-...), all statuses, and each CAB's product "
      "\"Certificate and Schedule\" PDF. `issue_date` / `expiry_date` are the schedule's accreditation valid "
      "date / valid up to. Scraper `database/usa/uaf_certifind/17065/scrape_us_uaf_17065.py`; converter "
      "`prepare_certifind_17065.py`.", notes)
