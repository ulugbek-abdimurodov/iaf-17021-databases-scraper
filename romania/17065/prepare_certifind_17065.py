#!/usr/bin/env python3
"""RENAR (Romania) 17065 scrape (renar_17065_output/) -> certifind/data/renar-romania-17065.

Category 4 "Organisme de certificare produse". Lines: tables of each body's annex PDF (Anexa; columns from
the header). Status "Acreditat" and "Acreditare restrânsă" (restricted at the body's request) are imported.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "renar_17065_output")
bodies, notes = [], []
for r in c.rd(S / "companies.csv"):
    b = c.Body(reg=r["certificate_no"], name=r["name"], country="Romania", phone=r["phone"], email=r["email"],
               website=r["website"], address=r["address"], issued=r["issue_date"], expiry=r["expiration_date"],
               proof_url=r["detail_url"], source_url=r["detail_url"],
               # "Acreditare restrânsă ... la solicitarea OEC" = scope restricted at the body's request: still accredited
               active=r["status"] == "Acreditat" or r["status"].startswith("Acreditare restr"),
               status_note=r["status"])
    pdf = S / r["annex_pdf_file"] if c.clean(r["annex_pdf_file"]) else None
    if pdf and pdf.exists():
        b.lines, mode = c.pdf_lines(pdf)
        if not b.lines:
            notes.append(f"{b.reg} {b.name}: no table line in the annex ({mode})")
    else:
        notes.append(f"{b.reg} {b.name}: no annex PDF")
    bodies.append(b)
c.run("RENAR", "renar-romania-17065", "renar-romania", "https://www.renar.ro/index.php/oec",
      bodies, HERE / "renar_17065_review.md", TODAY,
      "RENAR register (DataTables API), category 6 = '4 Organisme de certificare produse', and each body's annex "
      "PDF. Scraper `database/romania/17065/scrape_ro_renar_17065.py`; converter `prepare_certifind_17065.py`.", notes)
