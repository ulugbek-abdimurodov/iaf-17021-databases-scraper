#!/usr/bin/env python3
"""IAS (USA) 17065 scrape (raw/ias_17065_raw.txt) -> certifind/data/ias-usa-17065.

Input line: num|expiry|name|cc|status|pdf|address|website|effective|since|...
Lines: the scope tables of the certificate PDF (https://www.iasonline.org/wp-content/uploads/<pdf>), downloaded to
raw/pdfs/ when missing; an empty scheme cell repeats the one above.
Usage: python prepare_certifind_17065.py [scrape_dir] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import certifind_17065_common as c  # noqa: E402

S, TODAY = c.cli(HERE / "raw")
REGISTER = "https://www.iasonline.org/search-accredited-organizations-2/"
PDF_BASE = "https://www.iasonline.org/wp-content/uploads/"


def nd(s: str) -> str:  # "Jun1,2027" / "June11,2026" -> "Jun 1, 2027"
    m = re.match(r"([A-Za-z]+)\s*(\d{1,2}),?\s*(\d{4})", s or "")
    return c.iso_date(f"{m[2]} {m[1]} {m[3]}") if m else ""


def scope_lines(pdf: Path) -> list:
    """Two-column scope tables "Products Category and Sub-Category | Certification Scheme and Scheme Owner /
    Standard". A row with a product cell starts a line; a row with only the right cell continues the current
    line's scheme / standard text (before the first product it is carried to the next line)."""
    rows, _ = c.pdf_rows(pdf)
    out, cur, pending, on = [], None, [], False
    for r in rows:
        if len(r) < 2:
            continue
        left, right = c.clean(r[0]), c.clean(" ".join(r[1:]))
        if re.match(r"Products?( and Process)? Category|GLOBALG\.A\.P\. STAND", left, re.I):
            on, cur, pending = True, None, []
            continue
        if re.search(r"ARDS/SCOPES|NORMATIVE DOCUMENT|STANDARD / CPCC|^REGULATIONS$", " | ".join(r)):
            continue  # wrapped header rows of the GLOBALG.A.P. table
        if not on:
            continue
        if left:
            cur = c.Line(product_text=left, normative_docs="; ".join(pending + ([right] if right else [])))
            pending = []
            out.append(cur)
        elif right:
            if cur is None:
                pending.append(right)
            else:
                cur.normative_docs = "; ".join(x for x in [cur.normative_docs, right] if x)
    for ln in out:
        ln.scheme_text = ln.normative_docs
    return out


bodies, notes = [], []
for raw in (S / "ias_17065_raw.txt").read_text(encoding="utf-8").splitlines():
    f = raw.split("|")
    if len(f) < 9 or not f[0].startswith("PCA"):
        continue
    num, exp, name, cc, status, pdf, addr, web, eff = f[:9]
    address = addr.split("; Product Certification Agency")[0].replace("; ", ", ")
    b = c.Body(reg=num, name=name, country=c.country_name(cc) if len(cc) > 2 else c.country_name(
               {"US": "United States", "GB": "United Kingdom", "KR": "South Korea", "AE": "United Arab Emirates"}
               .get(cc, cc)), website=web, address=address, issued=nd(eff), expiry=nd(exp),
               proof_url=PDF_BASE + pdf, source_url=REGISTER,
               active=status.strip().lower() in ("", "active", "accredited"), status_note=status)
    local = S / "pdfs" / Path(pdf).name
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(PDF_BASE + pdf, timeout=60, headers={"User-Agent": "Mozilla/5.0 CertiFind"})
            r.raise_for_status()
            local.write_bytes(r.content)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{num} {name}: certificate PDF not downloaded ({e.__class__.__name__})")
    if local.exists():
        b.lines += scope_lines(local)
    if not b.lines:
        notes.append(f"{num} {name}: no scope table in the certificate PDF")
    bodies.append(b)
c.run("IAS", "ias-usa-17065", "ias-usa", REGISTER, bodies, HERE / "ias_17065_review.md", TODAY,
      "IAS register, program \"Product Certification Agencies\" (service=13573), and each agency's certificate "
      "PDF (address, effective date, scope tables). `issue_date` is the effective date, `expiry_date` the register "
      "expiry. Scraper `database/usa/ias_certifind/17065/scrape_us_ias_17065.py`; converter "
      "`prepare_certifind_17065.py`.", notes)
