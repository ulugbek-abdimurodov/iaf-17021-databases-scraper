"""Convert the EIAC (UAE) ISO/IEC 17065 scrape into certifind/data/eiac-uae-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_ae_eiac_17065.py): eiac_17065/eiac_17065_raw.json (directory main field "CB Products certification",
CB-PRD-xxx) and eiac_17065/scope_lines.csv. Lines come from the register scope table rows (source "register"):
Certification Type/Scheme | Product Category | Type of Product | Applicable Standard | Status. Merged (row-spanning)
cells come through as shorter rows: missing leading cells carry down from the row above. The "Product Certification
based on ISO/IEC 17065" title rows are dropped. product_text = "<category>: <type of product>", scheme_text =
the certification type / scheme cell, normative_docs = applicable standard. The PDF annex text is not used (the
register table is the same scope, already structured).
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "EIAC", "eiac-uae-17065", "eiac-uae"
URL = "https://eiac.gov.ae/directory/"
TITLE = re.compile(r"^Product Certification based on ISO/ ?IEC 17065$", re.I)


def iso(s: str) -> str:
    s = re.sub(r"\s+,", ",", cf.clean(s))
    for fmt in ("%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def main():
    scrape, today = cf.cli(HERE / "eiac_17065")
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "eiac_17065_raw.json", encoding="utf-8"))
    rows = defaultdict(list)
    for r in cf.rd(scrape / "scope_lines.csv"):
        if r["source"] == "register":
            rows[r["registration_no"]].append(r["product_text_raw"])
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        if r.get("status") != "Active":
            notes.append(f"{reg} {r['name']}: register status {r.get('status')}; left out")
            continue
        b = cf.Body(reg=reg, name=r["name"], country="United Arab Emirates", phone=r.get("phone") or "",
                    email=r.get("email") or "", website=r.get("website") or "", address=r.get("address") or "",
                    issued=iso(r.get("initial_accreditation") or r.get("issued") or ""), expiry=iso(r["expiry"]),
                    proof_url=r.get("detail_url") or URL, source_url=URL)
        scheme = category = ""
        for text in rows.get(reg, []):
            parts = [cf.clean(p) for p in text.split(" | ")]
            if parts and parts[-1] in ("Active", "Suspended", "Withdrawn"):
                status = parts.pop()
            else:
                status = "Active"
            if not parts or TITLE.match(parts[0]):
                continue
            if status != "Active":
                notes.append(f"{reg}: row with status {status} dropped: {text[:80]}")
                continue
            if len(parts) >= 4:
                scheme, category, product, std = parts[0], parts[1], " ".join(parts[2:-1]), parts[-1]
            elif len(parts) == 3:
                category, product, std = parts
            elif len(parts) == 2:
                product, std = parts
            else:
                product, std = parts[0], ""
            prod = f"{category}: {product}" if category and product and category != product else (product or category)
            sch = cf.scheme_of(f"{prod} {std} {scheme}")
            b.lines.append(cf.Line(product_text=prod, normative_docs=std, scheme_text=scheme, scheme=sch,
                                   industry=None if sch else (cf.industry_of(f"{prod} {scheme}")
                                                              or cf.industry_of(std) or "other_manufacturing")))
        if reg in debug:
            for ln in b.lines:
                print(reg, "|", ln.scheme or ln.industry, "|", ln.product_text[:60], "|", ln.normative_docs[:40], "|",
                      ln.scheme_text[:40])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "eiac_17065_review.md", today,
           sources_extra="EIAC directory, main field \"CB Products certification\" (CB-PRD-xxx). Lines from the register "
                         "scope table (category: product; applicable standard; certification type / scheme in "
                         "scheme_text).", pre_notes=notes)


if __name__ == "__main__":
    main()
