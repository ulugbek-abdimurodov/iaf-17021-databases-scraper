"""Convert the ONAC (Colombia) ISO/IEC 17065 scrape into certifind/data/onac-colombia-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_co_onac_17065.py): onac_17065/onac_17065_raw.json (register detail pages) and onac_17065/pdf/<code>.pdf
(certificate + scope annex). Lines come from the annex tables, which all share the header
"División NACE | Categoría o Producto / Proceso / Servicio a certificar | Documento Normativo | Esquema de
Certificación | Vigente a partir de". One line per table row: product = category column, normative_docs = normative
document column. The "Esquema de Certificación" column (the body's own procedure + ISO/IEC 17067 scheme type) is not
imported; it is only read to recognise private schemes (GLOBALG.A.P. ...). Industry from the NACE division.
Body rows are reused from data/onac-colombia (MS, same name or alias) or any other dataset.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parent))
import certifind_17065_common as cf  # noqa: E402
import prepare_certifind as ms  # noqa: E402  (ONAC MS converter: Colombian phone rules)

AB, FOLDER, MS = "ONAC", "onac-colombia-17065", "onac-colombia"
URL = "https://onac.org.co/directorio-de-acreditados/"
ms.CITY_PREFIX.update({"Barranquilla": "605", "Pereira": "606", "Envigado": "604", "Zipaquirá": "601",
                       "Rionegro": "604", "Cartago": "602", "Neiva": "608", "Marinilla": "604"})
FOREIGN = {"Quito": "Ecuador", "Lima": "Peru", "Mexico": "Mexico", "Santiago de Chile": "Chile"}
# Register name -> name in data/onac-colombia (same body, punctuation or sigla differs).
ALIASES = {"NYCE COLOMBIA S.A.S.": "NYCE COLOMBIA S.A.S",
           "KIWA CQR SAS Sigla: CQR SAS": "KIWA CQR SAS Sigla: KIWA CQR",
           "SERVIMETERS S.A.S.": "SERVIMETERS S.A.S",
           "BVQI COLOMBIA LTDA": "BVQI COLOMBIA LTDA."}
# NACE division -> V70 industry.
NACE = [((1, 3), "agriculture"), ((5, 9), "energy"), ((10, 12), "food"), ((13, 15), "textiles"),
        ((16, 18), "wood_paper"), ((19, 19), "energy"), ((20, 21), "chemicals"), ((22, 22), "rubber_plastics"),
        ((23, 23), "construction"), ((24, 25), "metals"), ((26, 27), "electrical"), ((28, 28), "machinery"),
        ((29, 30), "transport_equipment"), ((31, 33), "other_manufacturing"), ((35, 35), "energy"),
        ((36, 39), "energy"), ((41, 43), "construction"), ((45, 47), "trade_logistics"),
        ((49, 53), "trade_logistics"), ((55, 56), "tourism"), ((58, 63), "ict"), ((64, 82), "professional"),
        ((84, 85), "public_education"), ((86, 88), "health"), ((90, 99), "professional")]
DIV = re.compile(r"^\d{1,2}(\.\d+)*$")
HEADER = re.compile(r"^(División NACE|CAMPO (REGLAMENTARIO|VOLUNTARIO)|ALCANCE\b)", re.I)


def industry(div: str) -> str:
    n = int(div.split(".")[0])
    return next((ind for (a, b), ind in NACE if a <= n <= b), "")


def first_phone(raw: str, country: str, city: str, notes: list, who: str) -> str:
    one = re.split(r"\s*(?:[;,/–]|\s-\s|-(?=\s*\+?\(?\d{6,})|\by\b)\s*", raw.strip())[0]
    if country == "Colombia":
        one = re.sub(r"^\(\+?57\)\s*|^\+57\s*", "", one)
        one = re.sub(r"^\(60-?(\d)\)\s*", r"60\1", one)
        one = re.sub(r"^\((\d{1,3})\)\s*", r"\1", one)
        if re.fullmatch(r"57\s?\d\s?\d{7}", one):  # "574 3116478": old country code 57 + area 4
            one = re.sub(r"\D", "", one)[2:]
        out = ms.phone(one, country, city, notes)
        if notes and notes[-1].startswith("phone"):
            notes[-1] = f"{who}: {notes[-1]}"
        return out
    return cf.phone(one, country, notes, who)


EU_SCHEMES = set((HERE / "eu_schemes.txt").read_text(encoding="utf-8").splitlines()) - {""}
EU_ACT = re.compile(r"\((?:UE|EU|CE)\)|\b(?:Reglamento|Directiva|Regulation|Directive)\s+(?:\(\w+\)\s*)?"
                    r"(?:N[°ºo.]*\s*)?\d{2,4}/\d{2,4}", re.I)


def scheme(product: str, norm: str, scheme_col: str) -> str:
    """Scheme from the product and norm columns. The procedure column (ONAC's own "CPR" codes, 17067 types) only
    counts for private schemes. An EU regulation scheme needs the text to cite an EU act: Colombian decrees and
    resolutions are national (eu_schemes.txt = SELECT code FROM schemes WHERE kind = 'EU_REGULATION')."""
    text = f"{product} {norm}"
    sch = cf.scheme_of(text)
    if not sch:
        col = cf.scheme_of(scheme_col)
        sch = "" if col in EU_SCHEMES else col
    if sch in EU_SCHEMES and not EU_ACT.search(text):
        return ""
    return sch


def annex_lines(pdf: Path) -> tuple[list[cf.Line], list[str]]:
    rows, mode = cf.pdf_rows(pdf)
    out, skipped = [], []
    for r in rows:
        cells = [c for c in (cf.clean(x) for x in r) if c]
        if len(r) < 4 or not cells or HEADER.match(cells[0]):
            continue
        if not DIV.match(cells[0]):
            skipped.append(" | ".join(cells)[:120])
            continue
        div, rest = cells[0], cells[1:]
        if rest and re.fullmatch(r"\d{4}-\d\d-\d\d", rest[-1]):
            rest = rest[:-1]
        product = rest[0] if rest else ""
        norm = rest[1] if len(rest) > 1 else ""
        scheme_col = " ".join(rest[2:])
        sch = scheme(product, norm, scheme_col)
        out.append(cf.Line(product_text=product, normative_docs=norm, scheme=sch or "",
                           industry=None if sch else (industry(div) or None)))
    if mode != "tables":
        skipped.append(f"PDF read as {mode}")
    return out, skipped


def main():
    scrape, today = cf.cli(HERE / "onac_17065")
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "onac_17065_raw.json", encoding="utf-8"))
    notes, bodies = [], []
    for r in raw:
        reg, name = r["registration_no"], cf.clean(r["name"])
        name = ALIASES.get(name, name)
        country = FOREIGN.get(r["city"], "Colombia")
        b = cf.Body(reg=reg, name=name, country=country,
                    phone=first_phone(r["phone"], country, r["city"], notes, name) if r["phone"] else "",
                    email=r["email"].split(";")[0].strip(), website=r["website"], address=r["address"],
                    issued=r["issued"], expiry=r["expiry"], proof_url=(r["annex_urls"] or [URL])[0],
                    source_url=URL, active=r["status"] == "Acreditado", status_note=r["status"])
        b.lines, skipped = annex_lines(scrape / "pdf" / f"{reg}.pdf")
        for s in skipped:
            notes.append(f"{reg}: annex row not read: {s}")
        if reg in debug:
            for ln in b.lines:
                print(reg, "|", ln.scheme or ln.industry, "|", ln.product_text[:80], "|", ln.normative_docs[:80])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "onac_17065_review.md", today,
           sources_extra="Register listing: scheme \"Organismos de Certificación de Producto (CPR)\" (browser export "
                         "onac_17065_list.tsv). Lines: one per annex table row (category -> product_text, documento "
                         "normativo -> normative_docs); the \"Esquema de Certificación\" column (own procedure + "
                         "ISO/IEC 17067 type) is read only to detect private schemes. Industry from the NACE division.",
           pre_notes=notes)


if __name__ == "__main__":
    main()
