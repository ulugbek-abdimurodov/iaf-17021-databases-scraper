"""Convert the GAC (GCC Accreditation Center) ISO/IEC 17065 scrape into certifind/data/gac-saudi-arabia-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_gcc_gac_17065.py): gac_17065/gac_17065_raw.json (register cards: Product Certification APC ####,
Halal Product Certification HPC ####) and gac_17065/scopes/<code>.pdf (certificate page + scope tables, text layer).
Only register status "Accredited" is imported (Suspended / Withdrawn / Expired are logged).

Scope tables (one GAC template):
- APC: blocks headed "Technical Regulation: ..." (GCC / GSO technical regulation -> scheme_text), table
  Product Category | Items, Materials or Products | Standards | Remarks. One line per item row; the category
  carries down. EU directives cited as test methods do NOT make the line an EU scheme (GCC regulations).
- HPC: Category code | Subcategory | Products | Scheme / Standard. Every line gets the catalogue scheme "Halal".
  Rows of the "Date Suspended" table get status SUSPENDED; rows of the "Date Withdrawn" table are dropped.
Contact person row / e-mail / website / telephone come from the certificate page of the scope PDF.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "GAC", "gac-saudi-arabia-17065", "gac-saudi-arabia"
URL = "https://gac.org.sa/accredited-bodies/"
STD = re.compile(r"\b(EN|ISO|IEC|GSO|SASO|ASTM|ASME|UL|ANSI|BS|DIN|JIS|GB|SAE|NFPA|CISPR|UNECE|ECE|OIML|API|AS|NZS|"
                 r"CSA|SNI|KS|IS|UAE\.S|OS|QS|KWS|BSI|IEEE|ETSI|NSF|ASHRAE|AHRI|CEN|FCC|Regulation|Directive|"
                 r"GSO/IEC|Codex|CAC)\b[^\n]*\d", re.I)
CODE = re.compile(r"^[A-Z]{1,2}(?:[IV]{1,4})?(?:\s*-\s*[IVX]+)?$")  # halal category / subcategory codes
SKIP = re.compile(r"^(Schemes? Owner|Technical Regulation|Scheme Type|the Scheme owner|as stated|by the Scheme|"
                  r"Product Category|Items, Materials|Products$|Standards$|Remarks|\(if any\)|Category|codes$|"
                  r"Subcategory|Scheme / Standard|Location|Contact Person|Email|Scope Issue|Details of scope|"
                  r"Date of Inclusion|This conformity|END$|Version|Approved by|AC \d)", re.I)
HEADER_NOISE = re.compile(r"^(Schemes? Owner|Scheme Type|as stated by|(the )?Scheme owner\)|by the Scheme|"
                          r"ISO/IEC 17067 or|owner\):|Type:? ?\d|Remarks)", re.I)
REG_JUNK = re.compile(r"\s*(owner\):|Type\s*:?\s*\d[a-z]?(\s*(&|,)\s*\d[a-z]?)*|Scheme Type[^)]*\)?)\s*", re.I)
# industry from the GCC technical regulation first (its products are often generic words like "Part 2-14")
TELECOM = re.compile(r"communications? and information|information technology|telecommunication", re.I)
REG_INDUSTRY = [(re.compile(p, re.I), ind) for p, ind in [
    (r"low voltage|electrical|energy efficiency|lighting|lamp|air.?condition", "electrical"),
    (r"toy", "other_manufacturing"), (r"water.?(consumption|conservation)|sanitary", "construction"),
    (r"vehicle|tyre|tire|automotive", "transport_equipment"), (r"construction|building|cement|steel bar", "construction"),
    (r"gas appliance|fuel|lubricant|oil", "energy"), (r"cosmetic|detergent|chemical", "chemicals"),
    (r"food|feed|halal", "food"), (r"textile|apparel", "textiles"), (r"personal protective|PPE", "other_manufacturing"),
]]
EU = set()  # filled in main() from the catalogue: EU_REGULATION codes are never assigned to GAC lines


def iso(s: str) -> str:
    s = cf.clean(s)
    for fmt in ("%d %B %Y", "%B %d, %Y", "%d.%m.%Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def read_scope(pdf: Path, halal: bool) -> tuple[dict, list[cf.Line], list[str]]:
    import pdfplumber
    info, lines, notes = {}, [], []
    regulation, category, status, in_reg = "", "", "ACTIVE", False
    with pdfplumber.open(pdf) as doc:
        first = doc.pages[0].extract_text() or ""
        m = re.search(r"Initial Accreditation Date:\s*([^\n]+)", first)
        info["initial"] = iso(m[1]) if m else ""
        m = re.search(r"Certificate Issue Date:\s*([^\n]+)", first)
        info["issue"] = iso(m[1]) if m else ""
        for page in doc.pages:
            for table in page.extract_tables():
                for row in table:
                    raw = [cf.clean(c) for c in row]
                    cells = [c for c in raw if c]
                    if not cells:
                        continue
                    joined = " | ".join(cells)
                    for key, pat in (("phone", r"Telephone/Mobile:"), ("email", r"Email:"), ("website", r"Website:")):
                        if key not in info and re.search(pat, joined):
                            after = [c for c in cells[cells.index(next(c for c in cells if re.search(pat, c))) + 1:]]
                            info[key] = after[0] if after else ""
                    if re.search(r"Date Suspended", joined):
                        status = "SUSPENDED"
                        continue
                    if re.search(r"Date Withdrawn", joined):
                        status = "WITHDRAWN"
                        continue
                    head = next((c for c in cells if c.startswith("Technical Regulation")), None)
                    if head is not None:
                        regulation = re.sub(r"^Technical Regulation:?\s*", "", head)
                        in_reg = True  # following non-table rows continue the regulation name
                        continue
                    if HEADER_NOISE.search(cells[0]) and not STD.search(joined.replace("17067", "")):
                        continue
                    if re.match(r"(Product Category|Category|Items, Materials)", cells[0], re.I):
                        in_reg = False
                        continue
                    if in_reg and not STD.search(joined):
                        regulation = f"{regulation} {' '.join(cells)}".strip()
                        continue
                    if SKIP.match(cells[0]) and not STD.search(joined):
                        continue
                    i = next((k for k, c in enumerate(cells) if STD.search(c) and not CODE.match(c)), None)
                    if i is None:
                        continue
                    prefix, std = cells[:i], cells[i]
                    codes = [c for c in prefix if CODE.match(c)]
                    prefix = [c for c in prefix if not CODE.match(c)]
                    if halal:
                        text = " ".join(prefix)
                        if codes:
                            text = f"{codes[-1]}: {text}" if text else codes[-1]
                    else:
                        if len(prefix) >= 2:
                            category, item = prefix[0], " ".join(prefix[1:])
                        elif len(prefix) == 1 and raw[0]:
                            category, item = prefix[0], ""
                        else:
                            item = prefix[0] if prefix else ""
                        text = f"{category}: {item}" if category and item else (item or category)
                    if not text:
                        continue
                    if status == "WITHDRAWN":
                        notes.append(f"withdrawn scope row dropped: {text[:80]}")
                        continue
                    ln = cf.Line(product_text=text, normative_docs=std, scheme_text=regulation, status=status)
                    lines.append(ln)
    for ln in lines:
        ln.scheme_text = cf.clean(REG_JUNK.sub(" ", ln.scheme_text))
        if halal:
            ln.scheme, ln.industry = "Halal", None
            continue
        sch = cf.scheme_of(f"{ln.product_text} {ln.normative_docs} {ln.scheme_text}")
        if sch and sch not in EU:
            ln.scheme, ln.industry = sch, None
        else:
            ln.scheme = ""
            # ICT / telecom devices: the common keyword table reads "information" as education
            ln.industry = ("electrical" if TELECOM.search(f"{ln.product_text} {ln.scheme_text}") else "") or (
                           next((ind for rx, ind in REG_INDUSTRY if rx.search(ln.scheme_text)), "")
                           or cf.industry_of(f"{ln.product_text} {ln.scheme_text}")
                           or cf.industry_of(ln.normative_docs) or "other_manufacturing")
    return info, lines, notes


def main():
    scrape, today = cf.cli(HERE / "gac_17065")
    EU.update(cf.EU_CODES)
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "gac_17065_raw.json", encoding="utf-8"))
    notes, bodies, seen = [], [], {}
    for r in raw:
        reg = r["registration_no"]
        if r["status"] != "Accredited":
            notes.append(f"{reg} {r['name']}: register status {r['status']}; left out")
            continue
        pdf = scrape / "scopes" / f"{reg.replace(' ', '_')}.pdf"
        info, lines, n = read_scope(pdf, reg.startswith("HPC")) if pdf.exists() else ({}, [], ["no scope PDF"])
        notes += [f"{reg}: {x}" for x in n[:20]]
        expiry = iso(r.get("expiry") or "")
        if expiry and expiry < today:
            notes.append(f"{reg}: expiry {expiry} passed although listed Accredited; left out")
            continue
        name, country = cf.clean(r["name"]), r.get("country") or ""
        if seen.setdefault(name.casefold(), country) != country:  # same name, different company in another country
            notes.append(f"{reg}: name '{name}' also used by a body in {seen[name.casefold()]}; recorded as "
                         f"'{name} ({country})'")
            name = f"{name} ({country})"
        b = cf.Body(reg=reg, name=name, country=country, phone=info.get("phone", ""),
                    email=info.get("email", ""), website=info.get("website", ""), address=r.get("address") or "",
                    issued=info.get("initial") or info.get("issue") or today, expiry=expiry,
                    proof_url=r.get("certificate_url") or URL, source_url=URL)
        b.lines = lines
        if reg in debug:
            for ln in lines:
                print(reg, "|", ln.scheme or ln.industry, "|", ln.status, "|", ln.product_text[:70], "|",
                      ln.normative_docs[:50], "|", ln.scheme_text[:40])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "gac_17065_review.md", today,
           sources_extra="GAC register https://gac.org.sa/accredited-bodies/ (scopes 8 Product Certification APC, "
                         "5 Halal Product Certification HPC). Lines from the scope PDFs (item rows with their standards; "
                         "GCC technical regulation in scheme_text; halal rows -> scheme Halal, suspended rows "
                         "SUSPENDED, withdrawn rows dropped). Only register status Accredited.", pre_notes=notes)


if __name__ == "__main__":
    main()
