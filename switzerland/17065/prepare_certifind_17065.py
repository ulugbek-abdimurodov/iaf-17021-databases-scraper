#!/usr/bin/env python3
"""Convert SAS (Switzerland) SCESp directories into CertiFind ISO/IEC 17065 dataset CSVs.

Input : the scrape folder written by scrape_ch_sas_17065.py (sas_17065_data/), i.e.
        SCESp/bodies.csv, SCESp/documents.csv, SCESp/pdf/*.pdf, SCESp/text/*.txt
Output: <dataset dir>/bodies.csv, accreditations.csv, scopes.csv (header only),
        product_scopes.csv   (SOURCES.md and the review are written by hand)

Usage:
    python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug SCESp_NNNN ...]

Rules (see SOURCES.md of the dataset):
- One accreditation per SCESp directory, standard ISO/IEC 17065, certificate "SCESp NNNN".
- The prevailing language version is used: the one named in the directory ("gilt die deutsche
  Fassung" / "la version française fait foi" / ...), otherwise de > fr > it > en.
- Every table row of the scope column becomes one product_scopes row. A row is a paragraph of
  the scope column (paragraphs are split by vertical gaps). normative_docs is the text of the
  "Normen / Standards" cell that governs the paragraph; remarks ("Bemerkungen") are appended to
  product_text in brackets. Footnote-only fragments such as "(*1, *2)" are merged into the
  previous paragraph.
- scheme comes from SCHEMES (regex on the normative text) only; ISO and national standards get
  no scheme but keep their text and an industry from INDUSTRY_RULES.
- Bodies that are already in another dataset of the same AB (sas-switzerland, the 17021 dataset)
  reuse that dataset's bodies.csv row exactly (REUSED).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

import pdfplumber

AB_CODE = "SAS"
STANDARD = "ISO/IEC 17065"
REG_URL = "https://www.seco.admin.ch/en/search-accredited-bodies-sas"
MS_DATASET = Path(__file__).resolve().parents[3] / "certifind" / "data" / "sas-switzerland" / "bodies.csv"

# Body rows already in sas-switzerland/bodies.csv (same legal entity): reuse them exactly.
REUSED = {
    "SCESp 0049": "Schweizerische Vereinigung für Qualitäts- und Managementsysteme (SQS)",
    "SCESp 0092": "SGS Société Générale de Surveillance SA",
    "SCESp 0038": "ProCert AG",
    "SCESp 0063": "Swiss Safety Center AG",
    "SCESp 0127": "KPMG AG",
}

# Display names for new bodies (legal entity; the department printed after it is dropped).
NEW_NAMES = {
    "SCESp 0006": "bio.inspecta AG",
    "SCESp 0086": "BIO TEST AGRO AG",
    "SCESp 0129": "CertX SA",
    "SCESp 0125": "COSC Contrôle Officiel Suisse des Chronomètres",
    "SCESp 0113": "Dynamic Test Center AG",
    "SCESp 0004": "Ecocert Swiss AG",
    "SCESp 0121": "Eidgenössisches Institut für Metrologie METAS",
    "SCESp 0033": "Eidgenössisches Starkstrominspektorat ESTI",
    "SCESp 0022": "Empa",
    "SCESp 0035": "Eurofins Electric & Electronic Product Testing AG",
    "SCESp 0120": "International Certification Bio Suisse AG",
    "SCESp 0054": "OIC - Organisme Intercantonal de Certification Sàrl",
    "SCESp 0104": "Pronovo AG",
    "SCESp 0107": "q.inspecta GmbH",
    "SCESp 0094": "S-Cert AG",
    "SCESp 0093": "Schweizerischer Überwachungsverband für Gesteinsbaustoffe (SÜGB)",
    "SCESp 0123": "Schweizerischer Verein für Schweisstechnik SVS",
    "SCESp 0101": "SCONRAIL AG",
    "SCESp 0124": "SIPIZ AG",
    "SCESp 0008": "Suva",
    "SCESp 0028": "SVGW Fachverband für Wasser, Gas und Wärme",
    "SCESp 0119": "TIMELAB Fondation du laboratoire d'horlogerie et de microtechnique de Genève",
    "SCESp 0132": "tytec AG",
    "SCESp 0046": "Zertifizierungsstelle SIBE Schweiz",
}

# Certification body scheme catalogue (SELECT code FROM schemes). Regex on the normative text.
# Only directives/regulations and standards whose code is in the catalogue.
SCHEMES = [
    (r"2018/848", "EU Organic Regulation (EU) 2018/848"),
    (r"2006/42", "Machinery Directive 2006/42/EC"),
    (r"2023/1230", "Machinery Regulation (EU) 2023/1230"),
    (r"2014/33", "Lifts Directive 2014/33/EU"),
    (r"2014/68", "Pressure Equipment Directive 2014/68/EU"),
    (r"2014/29", "Simple Pressure Vessels Directive 2014/29/EU"),
    (r"2014/34", "ATEX Directive 2014/34/EU"),
    (r"2014/30", "EMC Directive 2014/30/EU"),
    (r"2014/53", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/32", "Measuring Instruments Directive 2014/32/EU"),
    (r"2014/31", "Non-automatic Weighing Instruments Directive 2014/31/EU"),
    (r"2009/48", "Toy Safety Directive 2009/48/EC"),
    (r"2000/14", "Outdoor Noise Directive 2000/14/EC"),
    (r"92/42", "Hot-water Boilers Directive 92/42/EEC"),
    (r"2016/425", "PPE Regulation (EU) 2016/425"),
    (r"2016/426", "Gas Appliances Regulation (EU) 2016/426"),
    (r"2016/424", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2016/797", "Rail Interoperability Directive (EU) 2016/797"),
    (r"305/2011", "Construction Products Regulation (EU) 305/2011"),
    (r"2013/53", "Recreational Craft Directive 2013/53/EU"),
    (r"2014/90", "Marine Equipment Directive 2014/90/EU"),
    (r"2019/779", "ECM Regulation (EU) 2019/779"),
    (r"\b910/2014\b|eIDAS", "eIDAS"),
    (r"BIO SUISSE|Bio Suisse", "Bio Suisse Standard"),
    (r"ISO 3834", "ISO 3834"),
    (r"ISO 22005", "ISO 22005"),
    (r"EN 15085", "EN 15085-2"),
    (r"EN 15343", "EN 15343"),
    (r"EN 50126|EN 50128|EN 50129", "EN 50126 / 50128 / 50129"),
    (r"IEC 61508", "IEC 61508"),
    (r"IEC 62443", "IEC 62443"),
    (r"ISO 26262", "ISO 26262"),
    (r"ISO/IEC 15408", "Common Criteria (ISO/IEC 15408)"),
    (r"IEC 61215|IEC 61730", "IEC 61215 / IEC 61730"),
    (r"IEC 61400-22", "IEC 61400-22 / IECRE"),
    (r"ISO 13009", "ISO 13009"),
    (r"ISO 18295", "ISO 18295"),
    (r"ISO 22222", "ISO 22222"),
    (r"ISO 29993", "ISO 29993"),
]

# Industry for lines without a scheme (first match wins; V70 codes only).
INDUSTRY_RULES = [
    (r"Appellation|Indication G|AOP|IGP|Emmentaler|Safran|Saucisse|Saucisson|Käse|Fromage|Wurst|Lebensmittel|Nahrungsmittel|aliment|food|Getränk|boisson|beverage|Fleisch|Milch|Käse|Brot|Speise|Zucker", "food"),
    (r"Landwirt|agricult|agricol|Bio[\s\-–]|Bio$|Biolog|organi[qk]|Pflanz|plant|Saatgut|Tier|animal|Futter|feed|Aquakult|Honig|Bienen|Imker|Wein|Hopfen|Hefe|Ernte|Obst|Gemüse", "agriculture"),
    (r"Holz|wood|Papier|paper|Karton|carton", "wood_paper"),
    (r"Kunststoff|plastic|Gummi|rubber|Verpackung|packag|Folie|film", "rubber_plastics"),
    (r"Textil|textile|Bekleid|Schuh|Leder|cuir|Garn|fibre|Faser", "textiles"),
    (r"Schmierstoff|lubricant|Chemi|chimi|Farb|peinture|Lack|Reinig|Kosmet|cosmet|Dünger|Pflanzenschutz|Biozid|Lösemittel|Tenside", "chemicals"),
    (r"Schwei|welding|soud|Stahl|steel|acier|Metall|metal|Aluminium|Guss|Eisen", "metals"),
    (r"Ventil|valve|Armatur|Brause|Ausl[aä]ufe|\bBau\b|Bauprodukt|Baustoff|Bauwerk|construction|bâtiment|Beton|béton|Stein|Gestein|Zement|Ciment|Bauprodukt|produits? de construction|Fenster|Dach|Isolier|Gips|Wasser|eau|water|Gas\b|gaz|Rohr|tuyau|Sanitär|Armatur|Heizkessel|Baustoff", "construction"),
    (r"Schienen|rail|Bahn|ferroviaire|Fahrzeug|véhicule|vehicle|Automobil|automotive|Seilbahn|câble|cableway|Luft|aviation|Schiff|marine|Boot|craft|plaisance|Lokomotive|Wagen|transport", "transport_equipment"),
    (r"Elektr|electr|Strom|Leuchte|lampe|Kabel|câble|Schalter|Stecker|Solar|photovolt|Photovolt|Batterie|batter|Lampen|Haushalt|Ladegerät|Netz", "electrical"),
    (r"Energie|energy|énergie|Biogas|Brennstoff|combustible|Heiz|Wärme|chaleur|Kälte|F-Gas|Kältemittel|Druckgerät|appareil à pression|Druckbehälter", "energy"),
    (r"Maschin|machine|Anlage|installation|Förder|Kran|grue|Aufzug|ascenseur|lift|Pressen|Roboter|robot|Sicherheitsfunktion|Druckluft", "machinery"),
    (r"Informationstech|IT\b|IKT|ICT|Cyber|Software|PKI|Daten|donnée|data|digital|Signatur|signature|Sicherheit der Informationen|Informationssicherheit|Kryptograph", "ict"),
    (r"Gesundheit|health|santé|Medizin|médic|medical|Pflege|soins|Patient|Klinik|Hygiene|Arzneimittel|Pharma|Ärzt|Labor", "health"),
    (r"Mess|metrolog|mesur|Waage|balance|Gewicht|poids|Uhr|Chronom|chronom|horlog|watch|Zeitmess|Schmuck|bijou|jewel|Spielzeug|jouet|toy|Möbel|meuble|furniture|Sport|Spiel", "other_manufacturing"),
    (r"Bildung|éducation|education|Ausbildung|formation|Schulung|training|Dienstleist|service|Reinigungsdienst|Versicherung", "professional"),
    (r"Transport|logist|Lager|storage|entrepôt|Handel|trade", "trade_logistics"),
]
DEFAULT_INDUSTRY = "other_manufacturing"

# Words that mark the scope-column header of a table (any language) and the remarks column.
SCOPE_HEADERS = {"Zugelassene", "Approved", "Domaines", "Ambiti", "Aprobados", "Zugelassene"}
REMARK_HEADERS = {"Bemerkungen", "Remarks", "Remarques", "Osservazioni", "Bemerkung", "Remark"}
HEADER_WORDS = {"Bereiche", "Bereich", "technische", "technique", "techniques", "accordés", "approuvés", "Domaines", "Zugelassene", "Approved", "technical", "scopes", "Remarks", "Bemerkungen", "Remarques", "Osservazioni", "Normen", "Standards", "Norme", "Normes", "ambiti", "approvati", "tecnici", "Ambiti", "Aprobados", "accredited", "Remark", "Bemerkung"}
NORMEN_HEADERS = {"Normen", "Standards", "Norme", "Normes", "Norm"}

LANG_ORDER = ["de", "fr", "it", "en"]
PREVAIL_RE = re.compile(
    r"gilt die (deutsche|französische|italienische|englische) Fassung"
    r"|(version|la version) (allemande|française|italienne|anglaise) fait foi"
    r"|versione (tedesca|francese|italiana|inglese) fa fede",
    re.IGNORECASE,
)
PREVAIL_LANG = {
    "deutsche": "de", "allemande": "de", "tedesca": "de",
    "französische": "fr", "française": "fr", "francese": "fr",
    "italienische": "it", "italienne": "it", "italiana": "it",
    "englische": "en", "anglaise": "en", "inglese": "en",
}
BOILER_RE = re.compile(
    r"Widersprüchen|Sprachversionen|Verzeichnisse gilt|contradictions|versions linguistiques|fait foi|"
    r"fa fede|in caso di contraddizione|^\*|accredited body is designated|harmonised product standard|Diese Veröffentlichung betrifft|Norm im Entwurf|Keine Zertifizierung|no certification|pas de certification|"
    r"Abkürzung|Abréviation|^Bedeutung|^Signification|^Verordnung vom \d",
    re.IGNORECASE,
)
PHONE_TEXT_RE = re.compile(r"(?:Telefon|Téléphone|Telefono|Telephone|Phone)\s*:\s*(\+\d{2}[\d ]{6,})")
# Phone grouping fixed by hand: the directory prints "+41 71 626 0 626" (9 national digits).
PHONE_FIX = {"SCESp 0004": "+41 71 626 06 26"}
DATE_RANGE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*(?:bis|to|au|al|a)\s*(\d{2}\.\d{2}\.\d{4})")

# Standard identifiers in the normative text (for standard_refs).
STD_RE = re.compile(r"\b(?:ISO/IEC|ISO|IEC|SN EN ISO/IEC|SN EN ISO|SN EN|EN ISO|EN|DIN EN|ETSI|CEN/TS|AS)\s?\d[\d\-.:/]*(?::\d{4})?")
REG_RE = re.compile(r"\(EU\)\s*(?:No\.?\s*|Nr\.\s*)?(\d{2,4}/\d{1,4})")
DIR_RE = re.compile(r"\b(\d{4}/\d{2,3}/(?:EU|EC)|\d{4}/\d{2,3}(?:/EU|/EC|/EEC)?)\b")


def iso_date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})$", s)
    if not m:
        raise ValueError(f"bad date {s!r}")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def join_words(parts: list[str]) -> str:
    """Join wrapped lines; a hyphen at a line end joins the word (German hyphenation)."""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif out.endswith(("-", "‐")) and p[:1].islower():
            out = out[:-1] + p
        else:
            out = out + " " + p
    return clean_ws(out)


def read_bodies(scrape_dir: Path) -> list[dict]:
    with (scrape_dir / "SCESp" / "bodies.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_documents(scrape_dir: Path) -> dict[str, list[dict]]:
    by_acc: dict[str, list[dict]] = {}
    with (scrape_dir / "SCESp" / "documents.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            by_acc.setdefault(r["accreditation_id"], []).append(r)
    return by_acc


def prevailing_doc(docs: list[dict], text_dir: Path) -> tuple[dict, str]:
    """Return (document row, reason). Honour the directory's statement about the prevailing version."""
    langs = {d["language"]: d for d in docs}
    for d in docs:
        t = (text_dir / d["file"].replace(".pdf", ".txt")).read_text(encoding="utf-8", errors="replace")
        m = PREVAIL_RE.search(t)
        if m:
            word = (m.group(1) or m.group(2) or m.group(3)).lower()
            lang = PREVAIL_LANG.get(word)
            if lang in langs:
                return langs[lang], f"prevailing {lang} named in directory"
    for lang in LANG_ORDER:
        if lang in langs:
            return langs[lang], "default order de>fr>it>en"
    raise SystemExit(f"no document for {docs[0]['accreditation_id']}")


# ---------------------------------------------------------------- PDF layout

def table_regions(page, prev):
    """Yield (top_start, top_end, normen_x, scope_x, remark_x) for each table header on the page."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    heads = {}
    for w in words:
        if w["text"] in SCOPE_HEADERS:
            heads.setdefault(round(w["top"]), []).append(w)
    rows = sorted(heads)
    regions = []
    for top in rows:
        line = [w for w in words if abs(w["top"] - top) < 3]
        scope = min(w["x0"] for w in heads[top])
        rem = [w["x0"] for w in line if w["text"] in REMARK_HEADERS]
        normen = [w["x0"] for w in line if w["x0"] < scope - 20]
        normen_x = min(normen) if normen else 50
        remark_x = min(rem) if rem else 10_000
        regions.append({"top": top + 8, "normen": normen_x, "scope": scope, "remark": remark_x})
    if not regions:
        if prev is None:
            return [], words
        regions = [dict(prev, top=125)]
    # close regions: each ends where the next begins; the last one at the footer.
    for i, r in enumerate(regions):
        r["end"] = regions[i + 1]["top"] - 8 if i + 1 < len(regions) else 790
    return regions, words


def page_items(pdf_path: Path):
    """Return a list of paragraphs with their governing normen cell.

    Each element: dict(kind='scope', page, top, text, remarks, normen_key) and
    dict(kind='normen', page, top, text).
    """
    out_normen = []  # (page, top, text)
    out_scope = []   # (page, top, text)
    out_remark = []  # (page, top, text)
    prev = None
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            regions, words = table_regions(page, prev)
            if regions:
                prev = regions[-1]
            for r in regions:
                body = [w for w in words if r["top"] <= w["top"] < r["end"]]
                for w in body:
                    if w["x0"] < r["scope"] - 4:
                        col = out_normen
                    elif w["x0"] < r["remark"] - 4:
                        col = out_scope
                    else:
                        col = out_remark
                    col.append((w, pi + 1))
    return out_normen, out_scope, out_remark


def group_lines(items):
    """items: list of (word, page). -> lines [(page, top, text)] merged by top within page."""
    items = sorted(items, key=lambda t: (t[1], round(t[0]["top"]), t[0]["x0"]))
    lines = []
    for w, page in items:
        if lines and lines[-1][0] == page and abs(lines[-1][1] - w["top"]) < 2.5:
            lines[-1][2].append(w["text"])
        else:
            lines.append((page, w["top"], [w["text"]]))
    return [(p, t, join_words(parts)) for p, t, parts in lines]


def paragraphs(lines, gap=14.5):
    """Group lines into paragraphs; a new paragraph starts on a page change or a vertical gap."""
    paras = []
    for page, top, text in lines:
        if paras and paras[-1]["page"] == page and top - paras[-1]["last"] <= gap:
            paras[-1]["text"] = join_words([paras[-1]["text"], text])
            paras[-1]["last"] = top
        else:
            paras.append({"page": page, "top": top, "last": top, "text": text})
    return paras


def normalise_pdf(pdf_path: Path):
    normen_items, scope_items, remark_items = page_items(pdf_path)
    normen = paragraphs(group_lines(normen_items))
    scope = paragraphs(group_lines(scope_items))
    remarks = paragraphs(group_lines(remark_items))
    return normen, scope, remarks


def key(page, top):
    return (page, top)


def build_items(pdf_path: Path):
    """Pair scope paragraphs with the governing normen block and the remark of the same rows."""
    normen, scope, remarks = normalise_pdf(pdf_path)
    # Normen blocks: a block is a paragraph of the normen column (non-empty cell).
    blocks = [(key(p["page"], p["top"]), p["text"]) for p in normen if p["text"]]
    blocks.sort()
    # Remarks belonging to a scope paragraph: those whose top lies between the paragraph and the next.
    scope_keys = [key(p["page"], p["top"]) for p in scope]
    rem_by = {}
    for r in remarks:
        k = key(r["page"], r["top"])
        idx = None
        for i, sk in enumerate(scope_keys):
            if sk <= k:
                idx = i
            else:
                break
        if idx is not None:
            rem_by.setdefault(idx, []).append(r["text"])
    items = []
    for i, p in enumerate(scope):
        k = key(p["page"], p["top"])
        normen_text = ""
        for bk, bt in blocks:
            if bk <= k:
                normen_text = bt
            else:
                break
        text = p["text"]
        if all(tok.strip("()*,.:") in HEADER_WORDS for tok in text.split()):
            continue
        if BOILER_RE.search(text) or BOILER_RE.search(normen_text):
            continue
        if len(re.findall(r"[A-Za-zÀ-ÿ]", text)) < 4:
            # footnote fragment ("(*1, *2)") -> attach to the previous row
            if items:
                items[-1]["text"] = join_words([items[-1]["text"], text])
            continue
        items.append({
            "page": p["page"], "top": p["top"], "text": text,
            "normen": normen_text, "remarks": join_words(rem_by.get(i, [])),
        })
    return items


# ---------------------------------------------------------------- classification

def classify(item: dict) -> tuple[str, str, str]:
    """Return (scheme, industry, standard_refs) for one row."""
    norm = item["normen"]
    text = item["text"]
    remarks = item["remarks"]
    scheme = ""
    # 1. the normative cell and remarks name the directive, regulation or standard
    for rx, code in SCHEMES:
        if re.search(rx, norm + " " + remarks):
            scheme = code
            break
    # 2. the scope text names a standard that is in the catalogue (ISO / IEC / EN ids)
    if not scheme:
        for rx, code in SCHEMES:
            if re.match(r"(ISO|IEC|EN )", rx) and re.search(rx, text):
                scheme = code
                break
    # 3. CPR: a harmonised standard with an AVCP system or FPC, or the words "Bauprodukt"
    if not scheme and re.search(r"Bauprodukt|produits? de construction|construction products", norm + " " + remarks + " " + text, re.IGNORECASE):
        scheme = "Construction Products Regulation (EU) 305/2011"
    if not scheme and re.search(r"EN \d|SN EN", norm) and re.search(r"System ?[1-4]|FPC|AVCP|WPK|harmonis|harmonized", text + " " + remarks, re.IGNORECASE):
        scheme = "Construction Products Regulation (EU) 305/2011"
    industry = ""
    if not scheme:
        for rx, ind in INDUSTRY_RULES:
            if re.search(rx, norm + " " + text + " " + remarks, re.IGNORECASE):
                industry = ind
                break
        if not industry:
            industry = DEFAULT_INDUSTRY
    refs = []
    for m in STD_RE.finditer(norm + " " + text):
        r = clean_ws(m.group(0)).rstrip(".:-")
        if r not in refs:
            refs.append(r)
    for m in REG_RE.finditer(norm):
        r = "EU " + m.group(1)
        if r not in refs:
            refs.append(r)
    return scheme, industry, ";".join(refs)


def status_of(item: dict) -> str:
    t = (item["text"] + " " + item["remarks"]).lower()
    if re.search(r"suspendiert|suspended|suspendu|sospes", t):
        return "SUSPENDED"
    return "ACTIVE"


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape_out")
    ap.add_argument("dataset_dir")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    args = ap.parse_args()

    scrape = Path(args.scrape_out)
    out = Path(args.dataset_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf_dir = scrape / "SCESp" / "pdf"
    text_dir = scrape / "SCESp" / "text"

    bodies = read_bodies(scrape)
    docs_by = read_documents(scrape)

    # reused rows from the 17021 dataset
    with MS_DATASET.open(encoding="utf-8-sig", newline="") as f:
        ms_rows = {r["name"]: r for r in csv.DictReader(f)}

    body_rows, acc_rows, prod_rows = [], [], []
    notes = []
    counts = {"bodies": 0, "accreditations": 0, "lines": 0, "lines_scheme": 0, "lines_industry": 0}
    debug_set = set(args.debug)

    for b in bodies:
        acc_id = b["accreditation_id"]
        docs = docs_by.get(acc_id, [])
        if not docs:
            notes.append(f"{acc_id}: no documents, skipped")
            continue
        doc, why = prevailing_doc(docs, text_dir)
        pdf_path = pdf_dir / doc["file"]
        text = (text_dir / doc["file"].replace(".pdf", ".txt")).read_text(encoding="utf-8", errors="replace")

        if acc_id in REUSED:
            name = REUSED[acc_id]
            ms = ms_rows[name]
            body_rows.append({k: ms[k] for k in ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]})
            body_name = name
        else:
            name = NEW_NAMES[acc_id]
            addr = clean_ws(", ".join(x for x in [b["street_address"], " ".join(x for x in [b["postal_code"], b["locality"]] if x)] if x))
            web = b["website"].strip()
            if web and not web.lower().startswith(("http://", "https://")):
                web = "https://" + web
            web = re.sub(r"^http://", "https://", web)
            email = re.sub(r"\s+", "", b["email"]).replace("mailto:", "")
            phone = b["phone"].strip()
            if not phone:
                # the register field is empty; the directory prints the phone in its header
                m = PHONE_TEXT_RE.search(text)
                if m:
                    phone = clean_ws(m.group(1))
                    notes.append(f"{acc_id} {name}: phone {phone!r} read from the directory text (register field empty)")
            phone = PHONE_FIX.get(acc_id, phone)
            if not phone:
                notes.append(f"{acc_id} {name}: no phone in the register; left empty")
            body_rows.append({
                "name": name, "country": "Switzerland", "registration_no": acc_id,
                "phone": phone, "email": email, "website": web, "address": addr,
                "source_url": REG_URL, "verified_at": "",
            })
            body_name = name

        # accreditation dates: the directory's current accreditation period
        frm = iso_date(b["accreditation_from"]) if b["accreditation_from"].strip() else ""
        to = iso_date(b["accreditation_to"]) if b["accreditation_to"].strip() else ""
        if not frm or not to:
            m = DATE_RANGE_RE.search(re.sub(r"(?<=\d) +(?=[\d.])", "", text))
            if not m:
                raise SystemExit(f"{acc_id}: no accreditation period")
            frm = frm or iso_date(m.group(1))
            to = to or iso_date(m.group(2))
            notes.append(f"{acc_id}: period {frm}..{to} read from the directory text (register field empty)")
        acc_rows.append({
            "ab_code": AB_CODE, "certificate_number": acc_id, "body_name": body_name,
            "accreditation_standard": STANDARD, "status": "ACTIVE",
            "issue_date": frm, "expiry_date": to, "proof_url": doc["url"],
        })
        counts["accreditations"] += 1
        counts["bodies"] += 1

        items = build_items(pdf_path)
        if acc_id in debug_set:
            for it in items:
                print(acc_id, it["page"], "|N:", it["normen"][:80], "|S:", it["text"][:120], "|R:", it["remarks"][:60])
        line_no = 0
        for it in items:
            scheme, industry, refs = classify(it)
            line_no += 1
            prod_rows.append({
                "certificate_number": acc_id, "line_no": line_no, "scheme": scheme,
                "industry": industry, "product_text": it["text"] + (f" ({it['remarks']})" if it["remarks"] else ""),
                "product_text_en": "", "scheme_text": "", "normative_docs": it["normen"],
                "standard_refs": refs, "status": status_of(it),
            })
            counts["lines"] += 1
            counts["lines_scheme" if scheme else "lines_industry"] += 1
        if not items:
            notes.append(f"{acc_id}: no table rows found in {doc['file']}; body dropped")
            body_rows.pop()
            acc_rows.pop()
            counts["accreditations"] -= 1
            counts["bodies"] -= 1
        else:
            notes.append(f"{acc_id}: {len(items)} rows from {doc['file']} ({why})")

    def write(name, fields, rows):
        with (out / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("bodies.csv", ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"], body_rows)
    write("accreditations.csv", ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"], acc_rows)
    write("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write("product_scopes.csv", ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en", "scheme_text", "normative_docs", "standard_refs", "status"], prod_rows)

    print("counts:", counts)
    print("\n".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
