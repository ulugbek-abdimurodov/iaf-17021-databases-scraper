#!/usr/bin/env python3
"""IOAS (USA) 17065 scrape (ioas_17065/) -> certifind/data/ioas-usa-17065.

One accreditation per body (IOAS contract number). Lines: the annex table "STANDARD | CATEGORIES | GEOGRAPHICAL
SCOPE": product_text = category, normative_docs = standard (an empty standard cell repeats the one above),
geographical scope appended to product_text in brackets. The "CB OFFICES | ADDRESS | STANDARDS | KEY ACTIVITIES"
tables are ignored. Without an annex table, the 17065 scheme headings of the body page are the lines.
Status: register "Suspended Schemes" / "Applicant" holding 17065 (and not accredited) -> not imported.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "ioas_17065")
REGISTER = "https://ioas.org/accredited-certification-bodies/"


def annex_lines(pdf: Path) -> list:
    rows, _ = c.pdf_rows(pdf)
    out, section, std = [], None, ""
    for r in rows:
        head = [x.upper() for x in r]
        if head and head[0] == "STANDARD":
            section = "scope"
            continue
        if head and head[0].startswith("CB OFFICE"):
            section = None
            continue
        if section != "scope" or len(r) < 2:
            continue
        std = r[0] or std
        cat = c.clean(r[1])
        geo = c.clean(r[2]) if len(r) > 2 else ""
        for part in [p for p in re.split(r";\s*(?=[A-Z]\s*[-:]|Option)", cat) if c.clean(p)] or ([std] if std else []):
            out.append(c.Line(product_text=c.clean(part) + (f" ({geo})" if geo else ""), normative_docs=std,
                              scheme_text=std))
    return out


bodies, notes = [], []
for r in json.loads((S / "ioas_17065_raw.json").read_text(encoding="utf-8")):
    reg = r["registration_no"]
    cert = next((u for u in r["annex_urls"] if "annex" not in u.lower()), (r["annex_urls"] or [""])[0])
    b = c.Body(reg=reg, name=r["name"], country=c.country_name(r["country"]), phone=r["phone"], email=r["email"],
               website=r["website"], address=r["address"], issued=r["issued"], expiry=r["expiry"], proof_url=cert,
               source_url=r["url"], active=r["status"] == "accredited", status_note=r["status"])
    for pdf in sorted(S.glob(f"annexes/{reg}_*.pdf")):
        if "annex" in pdf.name.lower():
            b.lines += annex_lines(pdf)
    if not b.lines:
        notes.append(f"{reg} {b.name}: no annex scope table; accreditation headings used")
        b.lines = [c.Line(product_text=re.sub(r"^ISO/IEC 17065,?\s*", "", s) or s) for s in r["schemes"]]
    bodies.append(b)
c.run("IOAS", "ioas-usa-17065", None, REGISTER, bodies, HERE / "ioas_17065_review.md", TODAY,
      "IOAS accredited-body pages (sitemap), the 17065 sections of each page, the register status table and each "
      "body's ISO/IEC 17065 accreditation certificate (effective date, renewal date) and certificate annex "
      "(standard / categories / geographical scope). Bodies holding only COR, NATRUE, IFOAM, GOTS or Textile "
      "Exchange recognition are not 17065 and are left out by the scraper. Scraper "
      "`database/usa/ioas-usa-17065/scrape_us_ioas_17065.py`; converter `prepare_certifind_17065.py`.", notes)
