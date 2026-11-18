#!/usr/bin/env python3
"""FINAS (Finland) 17065 scrape (fi_17065_output/) -> certifind/data/finas-finland-17065.

scopes.csv holds the text lines of each scope PDF (S0xx_Mxx_yyyy.pdf). Lines kept: those after
"SCOPE OF ACCREDITATION", without column headers ("Sertifiointikohde ...", "Certification category ..."), page
furniture (S-number/decision lines, dates, page numbers) and the Finnish copy of a bilingual pair (a line with
Finnish letters followed by a line without them is taken to be the Finnish half; the English half is kept).
Lines wrapped by the PDF ("Products – Requirements") are joined to the previous line when they start
lower-case or with a dash/en dash.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "fi_17065_output")
START = re.compile(r"^SCOPE OF ACCREDITATION$", re.I)
HEADER = re.compile(r"^(Sertifiointikohde|Certification (category|object|scheme)|Tuote|Product\b.*specifications|"
                    r"Akkreditoitu|Accredited|PÄTEVYYSALUE|Liite|Annex|FINAS|S\d{3}\b|M\d+/|\d{1,2}\.\d{1,2}\.\d{4}|"
                    r"Sivu|Page|www\.|Pätevyysalueen|Scope of accreditation)", re.I)
FINNISH = re.compile(r"[äöÄÖ]")
lines_by = defaultdict(list)
for r in c.rd(S / "scopes.csv"):
    lines_by[r["ident"]].append(c.clean(r["column1"]))


def scope_lines(raw: list[str]) -> list[c.Line]:
    start = next((i for i, t in enumerate(raw) if START.match(t)), None)
    if start is None:
        return []
    body = [t for t in raw[start + 1:] if t and not HEADER.match(t)]
    joined: list[str] = []
    for t in body:
        if joined and (t[:1].islower() or t[:1] in "–-") and not FINNISH.search(joined[-1]) == (not FINNISH.search(t)):
            joined[-1] += " " + t
        elif joined and (t[:1].islower() or t[:1] in "–-"):
            joined[-1] += " " + t
        else:
            joined.append(t)
    out = []
    for i, t in enumerate(joined):
        nxt = joined[i + 1] if i + 1 < len(joined) else ""
        if FINNISH.search(t) and nxt and not FINNISH.search(nxt):
            continue  # Finnish half of a bilingual pair
        out.append(c.Line(product_text=t))
    return out


bodies = []
for r in c.rd(S / "bodies.csv"):
    b = c.Body(reg=r["ident"], name=r["company"], country="Finland", address=r["address"], issued=r["renewed"],
               expiry=r["expires"], proof_url=r["url"], source_url="https://www.finas.fi/sites/en/operators/Pages/default.aspx")
    b.lines = scope_lines(lines_by.get(r["ident"], []))
    bodies.append(b)
c.run("FINAS", "finas-finland-17065", "finas-finland", "https://www.finas.fi/sites/en/operators/Pages/default.aspx",
      bodies, HERE / "finas_17065_review.md", TODAY,
      "FINAS operator search (SharePoint search over https://www.finas.fi/Scopes), scope PDFs naming ISO/IEC 17065. "
      "Lines are the PDF's text lines (English half of bilingual pairs), not table cells. Scraper "
      "`database/finland/17065/scrape_fi_finas_17065.py`; converter `prepare_certifind_17065.py`.")
