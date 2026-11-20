"""Convert the MAFF JAS registered certifying bodies (ISO/IEC 17065) into certifind/data/maff-japan-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_jp_jasaff_17065.py): jasaff_17065/jasaff_17065_raw.json and scope_lines.csv, built from MAFF's three
PDF lists: JAS (excluding organic), organic JAS domestic CBs, organic JAS overseas CBs. MAFF registers these bodies
(ISO/IEC 17065 is the registration standard); AB code MAFF. The lists publish no registration numbers or dates, so
the certificate number is <list>-<row #> and issue_date is the conversion date (--today). A body on several lists
keeps one accreditation (the first) with the lines of all lists (common module merge).
Lines: one per product category (JAS) or organic scope row; scheme_text = the list. JAS and organic JAS are
Japanese national standards: no catalogue scheme, industry only.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER = "MAFF", "maff-japan-17065"
URL = "https://www.maff.go.jp/e/policies/standard/"
COUNTRIES = [(r"Australia", "Australia"), (r"Germany", "Germany"), (r"Netherlands", "Netherlands"),
             (r"Ital(y|ia)\b", "Italy"), (r"New Zealand", "New Zealand"), (r"India", "India"),
             (r"M[ée]xico", "Mexico"), (r"Spain|España", "Spain"), (r"Guatemala", "Guatemala"), (r"China", "China"),
             (r"Vietnam|Viet Nam", "Vietnam"), (r"Armenia", "Armenia"), (r"Korea", "South Korea"),
             (r"Thailand", "Thailand"), (r"Taiwan", "Taiwan"), (r"United States|U\.S\.A|\bUSA\b", "United States")]
INDUSTRY = [(re.compile(p, re.I), ind) for p, ind in [
    (r"pellet", "energy"),
    (r"lumber|timber|plywood|flooring|structural panel|veneer", "wood_paper"),
    (r"organic|agricultural products|aquaculture|fish|eggs|beef|pork|chicken|ornamental plants", "agriculture"),
    (r".", "food"),
]]


def country_of(address: str) -> str:
    return next((c for pat, c in COUNTRIES if re.search(pat, address or "", re.I)), "Japan")


def main():
    scrape, today = cf.cli(HERE / "jasaff_17065")
    raw = json.load(open(scrape / "jasaff_17065_raw.json", encoding="utf-8"))
    lines = defaultdict(list)
    for r in cf.rd(scrape / "scope_lines.csv"):
        lines[r["registration_no"]].append(r["product_text_raw"])
    notes, bodies = [], []
    # The JAS list restarts its row numbers on every page, and the lists spell one body differently
    # ("Co., Ltd" / "Co., Ltd." / "Co. Ltd"): one display name per punctuation-free key, and certificate numbers
    # renumbered per list in order of first appearance of each body.
    display, numbers, seq = {}, {}, defaultdict(int)
    for r in raw:
        k = re.sub(r"[^a-z0-9]", "", r["name"].lower())
        display.setdefault(k, r["name"].strip())
        lst = r["registration_no"].split("-")[0]
        if (lst, k) not in numbers:
            seq[lst] += 1
            numbers[(lst, k)] = f"{lst}-{seq[lst]}"
    by_reg: dict[str, cf.Body] = {}
    for r in raw:
        if not r["name"].strip():
            notes.append(f"{r['registration_no']}: list row without a name (layout fragment) skipped")
            continue
        k = re.sub(r"[^a-z0-9]", "", r["name"].lower())
        reg = numbers[(r["registration_no"].split("-")[0], k)]
        b = by_reg.get(reg)
        if b is None:  # one body per list: later rows of the same body only add their product lines
            b = by_reg[reg] = cf.Body(reg=reg, name=display[k], country=country_of(r["address"]), phone=r["phone"],
                                      email=r["email"], website=r["website"], address=r["address"], issued=today,
                                      expiry="", proof_url=(r["annex_urls"] or [URL])[0], source_url=URL)
            bodies.append(b)
        for text in lines.get(r["registration_no"], []):
            ind = next(i for rx, i in INDUSTRY if rx.search(text))
            b.lines.append(cf.Line(product_text=text, scheme_text=r["scheme"], scheme="", industry=ind))
    cf.run(AB, FOLDER, None, URL, bodies, HERE / "jasaff_17065_review.md", today,
           sources_extra="MAFF lists of registered certifying bodies: JAS (excluding organic) system-27.pdf, organic "
                         "JAS domestic CBs organic_JAS-114.pdf, organic JAS overseas CBs organic_JAS-115.pdf. No "
                         "numbers or dates are published: certificate = <list>-<row #>, issue_date = conversion date.",
           pre_notes=notes)


if __name__ == "__main__":
    main()
