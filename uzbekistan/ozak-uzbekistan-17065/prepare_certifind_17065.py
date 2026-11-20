"""Convert the O'ZAK (Uzbekistan) ISO/IEC 17065 scrape into certifind/data/ozak-uzbekistan-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_uz_ozak_17065.py): ozak_17065/ozak_17065_raw.json (register API, one record per accreditation) and
ozak_17065/pdfs/<number>/ (certificate, "Oblast" scope PDF and later scope-update PDFs).

Lines come from the scope PDFs. Each body has the original scope ("file_oblast") and often a newer scope edition
("file_scopes"); they repeat the same table, so only the most recent one (by upload month in its URL) is read.
Table columns: № | economic sector code | certification object code | TN VED (HS) codes | product name |
normative documents. One line per row: product_text = product name (Russian, verbatim), normative_docs = documents.
Industry from the HS chapter of the first TN VED code. Only bodies with register status "active" are imported.
Body names / phones follow the O'ZAK MS converter (../prepare_certifind.py); MS rows are reused by TIN.
"""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parent))
import certifind_17065_common as cf  # noqa: E402
import prepare_certifind as ms  # noqa: E402  (O'ZAK MS converter: names, country, phone, website)

AB, FOLDER, MS = "OZAK", "ozak-uzbekistan-17065", "ozak-uzbekistan"
URL = "https://akkred.uz/uz/reestr"
DATA = HERE.parents[2] / "certifind" / "data"
ROWNO = re.compile(r"^\d+(\.\d+)*\.?$")
CODES = re.compile(r"[\d\s,.;:–-]*")
HS = re.compile(r"\b(\d{4})\d{0,6}\b")
# HS chapter -> V70 industry.
HS_INDUSTRY = [((1, 14), "agriculture"), ((15, 24), "food"), ((25, 26), "construction"), ((27, 27), "energy"),
               ((28, 38), "chemicals"), ((39, 40), "rubber_plastics"), ((41, 43), "textiles"), ((44, 49), "wood_paper"),
               ((50, 67), "textiles"), ((68, 70), "construction"), ((71, 71), "other_manufacturing"),
               ((72, 83), "metals"), ((84, 84), "machinery"), ((85, 85), "electrical"),
               ((86, 89), "transport_equipment"), ((90, 90), "health"), ((91, 97), "other_manufacturing")]


def hs_industry(codes: str) -> str:
    m = HS.search(codes or "")
    if not m:
        return ""
    ch = int(m[1][:2])
    if m[1].startswith("9405"):  # lamps and lighting fittings sit in the furniture chapter
        return "electrical"
    if ch == 90 and not m[1].startswith(("9018", "9019", "9021", "9022")):
        return "electrical"  # optical / measuring instruments; 9018-9022 are medical
    return next((ind for (a, b), ind in HS_INDUSTRY if a <= ch <= b), "")


def scope_pdfs(folder: Path, rec: dict) -> list[tuple[str, Path]]:
    """Scope documents with their upload month (annex URLs carry /pdf/YYYY-MM/), newest first."""
    out = []
    for u in rec.get("annex_urls") or []:
        hit = next(iter(folder.glob(f"*__{u.rsplit('/', 1)[-1]}")), None)
        if hit:
            out.append(((re.search(r"/(\d{4}-\d\d)/", u) or [None, ""])[1], hit))
    return sorted(out, reverse=True)


def best_scope(folder: Path, rec: dict) -> tuple[Path | None, list[cf.Line], list[str]]:
    """The scope document whose table gives the most numbered rows; the newest wins a tie. Some newer scope
    editions are partly untabulated (text only), while the original Oblast PDF has the full table."""
    best = (None, [], [])
    for _, pdf in scope_pdfs(folder, rec):
        lines, notes = table_lines(pdf)
        if len(lines) > len(best[1]):
            best = (pdf, lines, notes)
    return best


def table_lines(pdf: Path) -> tuple[list[cf.Line], list[str]]:
    rows, mode = cf.pdf_rows(pdf)
    out, notes, cols = [], [], None
    for r in rows:
        cells = [cf.clean(x) for x in r]
        joined = " ".join(cells)
        if re.search(r"obyektining nomi|ob.ektining nomi", joined, re.I):  # header row: find the columns
            cols = {"product": next(i for i, c in enumerate(cells) if re.search(r"nomi", c, re.I)),
                    "norm": next((i for i, c in enumerate(cells) if re.search(r"hujjat", c, re.I)), len(cells) - 1),
                    "hs": next((i for i, c in enumerate(cells) if re.search(r"TIF|TN", c)), None)}
            continue
        if not cols or len(cells) <= cols["product"]:
            continue
        nonempty = [c for c in cells if c]
        if nonempty and all(re.fullmatch(r"\d+", c) for c in nonempty):  # column numbering row "1 2 3 4 5 6"
            continue
        numbered = bool(nonempty) and bool(ROWNO.match(nonempty[0]))
        product = cells[cols["product"]] if cols["product"] < len(cells) else ""
        norm = cells[cols["norm"]] if cols["norm"] < len(cells) and cols["norm"] != cols["product"] else ""
        hs = cells[cols["hs"]] if cols["hs"] is not None and cols["hs"] < len(cells) else ""
        if CODES.fullmatch(product):  # shifted row: the product cell holds HS codes only
            hs, product = f"{hs} {product}".strip(), ""
        if not product and not norm:
            continue
        if not numbered:  # a wrapped row continues the line above (product name and documents)
            if out:
                last = out[-1]
                last.product_text = f"{last.product_text} {product}".strip()
                last.normative_docs = f"{last.normative_docs} {norm}".strip()
            continue
        out.append(cf.Line(product_text=product, normative_docs=norm, scheme="", industry=hs_industry(hs) or None))
    for ln in out:  # schemes once the wrapped text is complete
        if re.search(r"программн|информационн|межсетев|криптограф", ln.product_text, re.I):
            ln.industry = "ict"  # software / IT security products have no HS code
        sch = cf.scheme_of(f"{ln.product_text} {ln.normative_docs}")
        if sch:
            ln.scheme, ln.industry = sch, None
    if mode != "tables":
        notes.append(f"{pdf.name}: read as {mode}")
    return out, notes


def main():
    scrape, today = cf.cli(HERE / "ozak_17065")
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "ozak_17065_raw.json", encoding="utf-8"))
    by_tin = {r["registration_no"]: r for r in csv.DictReader(open(DATA / MS / "bodies.csv", encoding="utf-8"))}
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        country = ms.country_of(r["address"] or "")
        row = by_tin.get(r.get("tin") or "")
        name = row["name"] if row else ms.body_name(reg, r.get("legal_entity") or r["name"])
        if row:
            country = row["country"]
        b = cf.Body(reg=reg, name=name, country=country, phone=ms.phone(r["phone"], country),
                    email=(r["email"] or "").split(",")[0].strip(), website=ms.website(r["website"]),
                    address=r["address"] or "", issued=r["issued"] or "", expiry=r["expiry"] or "",
                    proof_url=r.get("certificate_url") or URL, source_url=URL,
                    active=r["status"] == "active", status_note=r["status"])
        if b.active:
            pdf, b.lines, n = best_scope(scrape / "pdfs" / reg.replace("'", "_"), r)
            if pdf is None:
                notes.append(f"{reg} {name}: no scope PDF with a readable table")
            else:
                notes += [f"{reg}: {x}" for x in n]
                notes.append(f"{reg}: lines from {pdf.name}")
                if reg in debug:
                    for ln in b.lines:
                        print(reg, "|", ln.scheme or ln.industry, "|", ln.product_text[:70], "|", ln.normative_docs[:60])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "ozak_17065_review.md", today,
           sources_extra="Register API https://api-e.akkred.uz/apps/registries/main/?type_std=17 (Mahsulot "
                         "sertifikatlash organi, O'z DSt ISO/IEC 17065). Lines from the most recent scope PDF per body "
                         "(product name and normative documents columns, Russian verbatim); industry from the HS "
                         "chapter of the TN VED codes. Only register status 'active' is imported.", pre_notes=notes)


if __name__ == "__main__":
    main()
