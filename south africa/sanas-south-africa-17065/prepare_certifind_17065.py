"""Convert the SANAS (South Africa) ISO/IEC 17065 scrape into certifind/data/sanas-south-africa-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_za_sanas_17065.py): sanas_17065/sanas_17065_raw.json and sanas_17065/scope_lines.csv.
Lines come from the annex PDF text (source "annex"): the certificate page is skipped; the scope is the text after
"... authorised to provide (product) certification for the following" up to "Original date of Accreditation".
Repeated page headers ("Facility Number", column titles, "Page x of y") are dropped.

Two layouts:
- Standards tables (most bodies): Product/Service/Process | Type | Standard/Spec | Description, wrapped over
  several text lines. Each line that cites a standard (SANS, IEC, ISO, EN, ...) starts a scope line: normative_docs =
  the cited standard, product_text = the description after it plus the wrapped continuation lines, scheme_text =
  the text before the standard (scheme / addendum / type). "IAF n: ..." rows are kept as a category prefix on
  scheme_text. A description fragment printed just above its standard row (row with no own description) is moved
  down to it.
- Scheme tables without standard numbers (GLOBALG.A.P., Halaal): the whole scope text becomes one line per body.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "SANAS", "sanas-south-africa-17065", "sanas-south-africa"
URL = "https://www.sanas.co.za/Pages/index.aspx"

START = re.compile(r"authori[sz]ed to .*(certification|for the follow)|for the following:?$|^the following schemes:|^schemes:$", re.I)
STOP = re.compile(r"^Original date of Accreditation", re.I)
SKIP = re.compile(r"^(Facility Number:|Page \d+ ?of ?\d+|_{5,}|ISSUED BY|Accreditation Manager|"
                  r"(Product/Service/Process|Certification Scheme|Standard/ ?Spec|Type Standard|Spec Version|"
                  r"Scheme Certification Scheme)\b.*$|(Type )?Standard/Spec\b.*|Description of Standard.*|"
                  r"Certification Scheme$|Product/Service/Process$|NB:.*|conditions$|schemes:$)", re.I)
STD = re.compile(r"\b(?:S\s?A\s?NS(?:/IEC)?|SABS|IEC|ISO(?:/IEC)?|EN|NRS|ASTM|BS|ARP|VC)\s*\d{2,5}(?:[-‑]\d+)*"
                 r"(?:[-,]\d)*(?:\s*(?:,\s*\d|&\s*\d|and\s+\d))*(?:\s*:\s*\d{4}|\s+\d{4}(?=\s|$))?"
                 r"(?:\s*Ed\.?\s*[\d.]+)?(?:\s*Edition\s*\d+)?", re.I)
HEADING_LAYOUT = re.compile(r"Standard/Spec Edition", re.I)
IAF = re.compile(r"^IAF\s*\d+\s*:", re.I)


def scope_text(lines):
    out, on = [], False
    for ln in lines:
        if not on:
            on = bool(START.search(ln))
            continue
        if STOP.match(ln):
            on = False
            continue
        if not SKIP.match(ln):
            out.append(ln)
    return out


def is_heading(ln):
    """A product-group heading such as 'Fabricated Metal Products' or 'Rubber and Plastic' / 'Products':
    short, no digits, every word longer than 3 letters capitalised."""
    t = cf.clean(ln)
    words = [w for w in re.findall(r"[A-Za-z]+", t) if len(w) > 3]
    return (0 < len(t) <= 40 and not re.search(r"\d|[,:;()]", t) and bool(words)
            and all(w[0].isupper() for w in words) and not re.match(r"Part\b", t))


LEAD_TYPE = re.compile(r"^(?:addendum\s*[\d.]+\s*)?Type\s*\d+\s*(?:\d{4}\s*)?(?:Ed\.?\s*[\d.]+\s*)?", re.I)


def split_pending(pending):
    """Text between two standard rows: [continuation of previous row][heading run][lead-in of next row]."""
    for i, ln in enumerate(pending):
        if not is_heading(ln):
            continue
        j = i
        while j < len(pending) and is_heading(pending[j]):
            j += 1
        head = pending[i:j]
        # a single capitalised word directly after a description is more likely its wrapped end
        if i > 0 and len(head) == 1 and len(head[0].split()) == 1:
            continue
        # the heading can share its line with the next row's type/edition cells: 'Fabricated Metal Products Type 5 ...'
        return pending[:i], cf.clean(" ".join(head)), pending[j:]
    for i, ln in enumerate(pending):  # 'Fabricated Metal Products Type 5 2024 Ed 3.00 Hot dip ...' on one line
        m = re.match(r"^((?:[A-Z][a-z]+|and|of|&)(?:\s+(?:[A-Z][a-z]+|and|of|&))+)\s+(Type\s*\d.*)$", cf.clean(ln))
        if m and is_heading(m.group(1)):
            return pending[:i], m.group(1), [m.group(2)] + pending[i + 1:]
    return pending, "", []


def std_lines(lines, headings=False):
    """headings=True: layout with product-group heading rows (header 'Product/Service/Process Type Standard/Spec
    Edition ...', SATAS C25). Text between two rows is then split into continuation / heading / lead-in."""
    items, pending, category = [], [], ""
    for ln in lines:
        if IAF.match(ln):
            if pending and items:
                items[-1]["desc"] += pending
            category, pending = cf.clean(ln), []
            continue
        stds = list(STD.finditer(ln))
        if not stds:
            if not headings and items and not pending:
                items[-1]["desc"].append(ln)
            else:
                pending.append(ln)
            continue
        if not headings:
            first, last = stds[0], stds[-1]
            pre = cf.clean(ln[: first.start()])
            desc = cf.clean(ln[last.end():]).lstrip("/ ").strip()
            norm = "; ".join(cf.clean(m.group(0)) for m in stds)
            # a fragment printed above a row without its own description belongs to that row
            if not desc and pending:
                desc, pending = " ".join(pending), []
            elif pending and items:
                items[-1]["desc"] += pending
                pending = []
            items.append({"pre": pre, "norm": norm, "desc": [desc] if desc else [], "cat": category})
            continue
        first, last = stds[0], stds[-1]
        pre = cf.clean(ln[: first.start()])
        desc = cf.clean(ln[last.end():]).lstrip("/ ").strip()
        norm = "; ".join(cf.clean(m.group(0)) for m in stds)
        prev, heading, lead = split_pending(pending) if items or pending else ([], "", [])
        if not items:  # before the first row: heading run, then lead-in
            prev, lead = [], (lead if heading else pending)
        if heading:
            category = heading
        lead = [cf.clean(LEAD_TYPE.sub("", x)) for x in lead]
        lead = [x for x in lead if x]
        if prev and items:
            if not desc and not heading and not lead:
                # a fragment printed above a row without its own description belongs to that row
                lead, prev = prev, []
            items[-1]["desc"] += prev
        desc_parts = lead + ([desc] if desc else [])
        pending = []
        items.append({"pre": pre, "norm": norm, "desc": desc_parts, "cat": category})
    if pending and items:
        items[-1]["desc"] += pending
    return [cf.Line(product_text=cf.clean(" ".join(i["desc"])) or i["norm"], normative_docs=i["norm"],
                    scheme_text=" - ".join(x for x in (i["cat"], i["pre"]) if x)) for i in items]


def main():
    scrape, today = cf.cli(HERE / "sanas_17065")
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "sanas_17065_raw.json", encoding="utf-8"))
    annex = defaultdict(list)
    for r in cf.rd(scrape / "scope_lines.csv"):
        if r["source"] == "annex":
            annex[r["registration_no"]].append(r["product_text_raw"])
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        b = cf.Body(reg=reg, name=r["name"], country="South Africa", phone=r.get("phone") or "",
                    email=r.get("email") or "", address=r.get("address") or "", issued=r.get("issued") or "",
                    expiry=r.get("expiry") or "", proof_url=(r.get("annex_urls") or [URL])[0], source_url=URL,
                    active=r.get("status") == "Accredited", status_note=r.get("status") or "")
        sc = scope_text(annex.get(reg, []))
        if any(STD.search(x) for x in sc):
            b.lines = std_lines(sc, headings=any(HEADING_LAYOUT.search(x) for x in annex.get(reg, [])))
        elif sc:
            b.lines = [cf.Line(product_text=cf.clean(" ".join(sc)))]
            notes.append(f"{reg}: scheme table without standard numbers; whole scope kept as one line")
        if reg in debug:
            for ln in b.lines:
                print(reg, "|", ln.scheme_text[:40], "|", ln.normative_docs[:40], "|", ln.product_text[:90])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "sanas_17065_review.md", today,
           sources_extra="SANAS register (SharePoint list 'Legal Entity (Published)', Field of Accreditation = "
                         "Certification Body, discipline ISO/IEC 17065). Lines from the scope of accreditation "
                         "(Annexure A) in the latest published certificate PDF: description in product_text, cited "
                         "standard in normative_docs, scheme / type / IAF sector in scheme_text.",
           pre_notes=notes)


if __name__ == "__main__":
    main()
