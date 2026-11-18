#!/usr/bin/env python3
"""JSM (Malaysia) 17065 scrape (jsm_17065/) -> certifind/data/jsm-malaysia-17065.

Programme PACB0003 "Product Certification Systems (PC)". Each body's accreditation schedule PDF can also list
management system programmes; only table rows inside a "PROGRAMME: PRODUCT CERTIFICATION" section are read
(columns from headers such as "Certification Standard | Title").
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "jsm_17065")


def product_rows(pdf: Path) -> list[list[str]]:
    rows, _ = c.pdf_rows(pdf)
    out, inside, seen_programme = [], False, False
    for r in rows:
        cells = [x for x in r if x]
        if len(cells) >= 2 and c.clean(cells[0]).upper().startswith("PROGRAMME"):
            seen_programme = True
            inside = "PRODUCT" in cells[1].upper()
            continue
        if (inside or not seen_programme) and len(cells) >= 2:
            out.append(cells)
    return out


bodies, notes = [], []
for r in json.loads((S / "register_records.json").read_text(encoding="utf-8")):
    addr = c.clean(r["address_raw"])
    b = c.Body(reg=r["registration_no"], name=r["name"], country=c.country_name(addr.rsplit(",", 1)[-1], "Malaysia"),
               phone=r["phone"], email=r["email"], website=r["website"], address=addr, proof_url=r["proof_url"],
               source_url=r["register_url"], active=r["programme_status"] == "ACCREDITED",
               status_note=r["programme_status"])
    pdf = S / "pdfs" / f"{r['registration_no']}.pdf"
    if pdf.exists():
        b.lines, _ = c.rows_to_lines(product_rows(pdf), strict=True)
    if not b.lines:
        notes.append(f"{b.reg} {b.name}: no product table found in the schedule PDF")
    bodies.append(b)
c.run("JSM", "jsm-malaysia-17065", "jsm-malaysia", "https://cab.jsm.gov.my/cab-directories/srchAcb",
      bodies, HERE / "jsm_17065_review.md", TODAY,
      "JSM CAB directory, scheme PACB0003 'Product Certification Systems (PC)', all statuses searched, and each "
      "body's accreditation schedule PDF (product certification section only). JSM gives no accreditation dates in "
      "the directory, so `issue_date` is the run date. Scraper `database/malaysia/17065/scrape_my_jsm_17065.py`; "
      "converter `prepare_certifind_17065.py`.", notes)
