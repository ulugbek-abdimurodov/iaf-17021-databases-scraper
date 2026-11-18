#!/usr/bin/env python3
"""COFRAC (France) 17065 scrape (cofrac_17065_output/) -> certifind/data/cofrac-france-17065.

Bodies: easysearch hits for "17065" (accreditation numbers 5-xxxx, section 5 = product certification).
Lines: tables of each body's annex https://tools.cofrac.fr/annexes/sect5/<number>.pdf (downloaded to
annexes_sect5/; columns from the header: category / product or process / certification programme). Bilingual
section headings ("Certification de produits ... /", "Consumer goods and associated services") are not lines.
Only easysearch hits (active) are imported; the suspension list is not used.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "cofrac_17065_output")
HEADING = re.compile(r"(/\s*$|^(Certification d[eu]s? |Autres certifications|Product and service certification|"
                     r"Certification of |Consumer goods|Biens de grande consommation))", re.I)
bodies, notes = [], []
for r in c.rd(S / "bodies.csv"):
    parts = [p.strip() for p in r["address"].split("|") if p.strip()]
    country = c.country_name(parts[-1] if parts else "", r["country"] or "France")
    pdf_url = f"https://tools.cofrac.fr/annexes/sect5/{r['ident']}.pdf"
    b = c.Body(reg=r["ident"], name=r["company"], country=country, phone=r["phone"], email=r["email"],
               website=r["website"], address=", ".join(parts[:-1]) if len(parts) > 1 else r["address"],
               issued=r["started"], expiry=r["expires"], proof_url=pdf_url,
               source_url="https://tools.cofrac.fr/en/easysearch/", active=r["state"] == "Active",
               status_note=r["state"])
    for pdf in (S / "annexes_sect5" / f"{r['ident']}.pdf", S / "documents" / r["ident"] / f"{r['ident']}.pdf"):
        if pdf.exists():
            lines, mode = c.pdf_lines(pdf)
            b.lines = [l for l in lines if not (HEADING.search(l.product_text) and not l.scheme_text
                                                and not l.normative_docs)]
            if b.lines:
                break
    if not b.lines:
        notes.append(f"{b.reg} {b.name}: no table line in the annex")
    bodies.append(b)
c.run("COFRAC", "cofrac-france-17065", "cofrac-france", "https://tools.cofrac.fr/en/easysearch/",
      bodies, HERE / "cofrac_17065_review.md", TODAY,
      "COFRAC easysearch, keyword \"17065\" (accreditations 5-xxxx), and each accreditation's technical annex "
      "`/annexes/sect5/<number>.pdf`. COFRAC gives no accreditation dates in the search result, so `issue_date` is "
      "the run date. Scraper `database/france/17065/scrape_fr_cofrac_17065.py`; converter `prepare_certifind_17065.py`.",
      notes)
