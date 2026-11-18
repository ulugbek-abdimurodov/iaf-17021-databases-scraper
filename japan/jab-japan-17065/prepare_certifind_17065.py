#!/usr/bin/env python3
"""JAB (Japan) 17065 scrape (jab_17065_raw.txt) -> certifind/data/jab-japan-17065.

jab_17065_raw.txt (pipe separated): cert_num|name|location|tel|url|init|renew|exp|pdf|sec|rst|scope text.
The English scope text repeats blocks "Field of accreditation (Product classification) : X ... Certification
standard(s) : Y". Each block is one line: product_text = X, normative_docs = Y, scheme_text = the current
"Name of product certification scheme".
Usage: python prepare_certifind_17065.py [raw_file] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

RAW, TODAY = c.cli(HERE / "jab_17065_raw.txt")
LABELS = r"(Accreditation sub-scheme|Name of product certification scheme|Scheme type|Field of accreditation \(Product classification\)|Applicable accreditation criteria specific to the following certification|Certification standard\(s\)|Product/process/service category\(ies\))\s*[:：]"


def blocks(text: str) -> list[c.Line]:
    parts = re.split(LABELS, text)
    out, scheme, cur = [], "", None
    for label, value in zip(parts[1::2], parts[2::2]):
        value = c.clean(value)
        if label.startswith("Name of product"):
            scheme = value
        elif label.startswith("Field of accreditation"):
            cur = c.Line(product_text=value, scheme_text=scheme)
            out.append(cur)
        elif label.startswith("Certification standard") and cur is not None:
            cur.normative_docs = value
    if not out and scheme:
        out.append(c.Line(product_text=scheme))
    return out


bodies = []
for row in RAW.read_text(encoding="utf-8").splitlines():
    f = row.split("|")
    if len(f) < 12:
        continue
    addr = c.clean(f[2])
    b = c.Body(reg=f[0], name=f[1], country=c.country_name(addr.rsplit(",", 1)[-1], "Japan"), phone=f[3],
               website=f[4], address=re.sub(r",\s*Japan$", "", addr), issued=f[5], expiry=f[7],
               proof_url="https://www.jab.or.jp/en/certification_institutions",
               source_url="https://www.jab.or.jp/en/certification_institutions")
    b.lines = blocks(f[11])
    bodies.append(b)
c.run("JAB", "jab-japan-17065", "jab-japan", "https://www.jab.or.jp/en/certification_institutions",
      bodies, HERE / "jab_17065_review.md", TODAY,
      "JAB Strapi API `/cms/api/certifications`, certificate numbers P + digit (product certification; PTP = "
      "proficiency testing providers excluded). Scraper `database/japan/jab-japan-17065/scrape_jp_jab_17065.py`; "
      "converter `prepare_certifind_17065.py`.")
