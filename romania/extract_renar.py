#!/usr/bin/env python3
"""
extract_renar.py - RENAR accreditation certificate / annex PDFs -> CSV + PostgreSQL seed.

Reads every *.pdf under <pdf_folder> (recursively - e.g. the output/pdfs tree written by
scraper.py, where each company folder holds Certificat.pdf and Anexa.pdf). Every PDF is split
into certificate page(s) and annex page(s), and all parts are merged by RENAR certificate
number (e.g. "SM 003"), so a certificate and its annexes may come from different files.
Byte-identical copies (the scraper saves the same certificate under every category) are read once.

Outputs (in --out):
  certification_bodies.csv, accreditations.csv, accredited_scopes.csv, review.csv,
  seed_romania.sql, debug/*.txt (with --debug: raw extracted text of each PDF)

Usage:
  python extract_renar.py output/pdfs --out output/extracted [--debug]
                          [--tesseract PATH] [--poppler PATH]   # only for scanned pages, see README
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber

COUNTRY = "Romania"
PROOF_URL_SQL = "https://www.renar.ro"
MIN_TEXT_CHARS = 50          # a page with less extractable text than this is OCR'd
ALL_EA = set(range(1, 40))

# --------------------------------------------------------------------------- standards
# accreditation standard -> certification standards allowed under it
ALLOWED: dict[str, list[str]] = {
    "ISO/IEC 17021-1": ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 13485"],
    "ISO/IEC 27006": ["ISO/IEC 27001", "ISO/IEC 27701", "ISO/IEC 27017", "ISO/IEC 27018"],
    "ISO 50003": ["ISO 50001"],
    "ISO 22003-1": ["ISO 22000"],
    "ISO/IEC 17021-4": ["ISO 20121"],
    "ISO/IEC 17021-6": ["ISO 22301"],
    "ISO/IEC 17021-7": ["ISO 39001"],
    "ISO/IEC 17021-9": ["ISO 37001"],
    "ISO/IEC 20000-6": ["ISO/IEC 20000-1"],
}
CERT_TO_ACC = {c: a for a, cs in ALLOWED.items() for c in cs}
# bare number -> canonical name (aliases: other editions of the same scheme)
CANONICAL = {s.split()[-1]: s for a, cs in ALLOWED.items() for s in (a, *cs)}
CANONICAL["27006-1"] = "ISO/IEC 27006"

# ===========================================================================
# PATTERNS - tune here after looking at real certificates (use --debug to see the raw text).
#
# Every pattern runs on fold()ed text: the PDF text with diacritics removed
# (ş/ș->s, ţ/ț->t, ă/â->a, î->i, Ü->U), so write patterns WITHOUT diacritics.
# fold() keeps the string length, so match positions also index the original text,
# which is what values (names, addresses) are copied from.
# ===========================================================================
I, S = re.IGNORECASE, re.DOTALL

# --- document type / certificate number --------------------------------------------
# "Anexa nr. 1 la Certificatul de Acreditare nr. SM 003"  (top of every annex page)
RX_ANNEX_HEADER = re.compile(
    r"Anexa(?:\s+nr\.?\s*(\d+))?\s+la\s+certificatul\s+de\s+acreditare\s+"
    r"nr\.?\s*([A-Z]{1,5})\s*[-.]?\s*(\d{1,4})", I)
# "CERTIFICAT DE ACREDITARE\nNr. SM 003"
RX_CERT_TITLE = re.compile(
    r"CERTIFICAT\s+DE\s+ACREDITARE\s+(?:nr\.?|numar)\s*:?\s*([A-Z]{1,5})\s*[-.]?\s*(\d{1,4})", I)

# --- organisation block: name line(s), optional "prin <unit>", address line(s) -------
RX_CERT_ORG_ANCHOR = re.compile(r"atesta\s+ca\s+organizatia\s*:?", I)     # certificate
RX_ANNEX_ORG_ANCHOR = re.compile(r"Data\s+emiterii\s+anexei[^\n]*", I)     # annex
RX_ORG_BLOCK_END = re.compile(
    r"^(?:indeplineste|standard\w*\s+de\s+referinta|nr\.?\s*(?:crt|nr)\b|descrierea|este\s+competent)", I)
RX_PRIN = re.compile(r"^prin\b\s*(.*)$", I)          # "prin TAR CERT" = operating unit
RX_ADDRESS_HINT = re.compile(
    r"\b(?:str|strada|calea|b-?dul|bd|bulevardul|sos|soseaua|aleea|piata|splaiul|intrarea|"
    r"nr|sector(?:ul)?|jud|judetul|cod\s+postal)\b", I)
ORG_BLOCK_MAX_LINES = 6

# --- contacts (only searched inside the organisation block) --------------------------
RX_PHONE = re.compile(r"\b(?:tel(?:efon)?|phone|mobil)\.?\s*(?:/\s*fax\.?)?\s*:?\s*(\+?\d[\d\s./()-]{6,}\d)", I)
RX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", I)
RX_WEBSITE = re.compile(r"\b(?:https?://)?www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s,;]*)?", I)
RX_IGNORE_CONTACT = re.compile(r"renar\.ro", I)      # RENAR's own details

# --- dates ---------------------------------------------------------------------------
# groups 1-3: DD.MM.YYYY (also / or -);  groups 4-6: "10 mai 2023"
RX_DATE = r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})|(\d{1,2})\s+([a-z]{3,10})\.?,?\s+(\d{4})"
ISSUE_DATE_LABELS = [  # (label, regex) in priority order; regexes must not capture
    ("Data acordarii", r"Data\s+acordarii(?:\s+acreditarii)?"),
    ("Data emiterii", r"Data\s+emiterii(?!\s+anex)(?:\s+certificatului)?"),
    ("Data reinnoirii acreditarii", r"Data\s+reinnoirii\s+acreditar\w*"),
    ("Data acreditarii initiale", r"Data\s+acreditarii\s+initiale"),
]
ISSUE_DATE_LOGGED = {"Data acreditarii initiale"}  # used, but may predate the current cycle
EXPIRY_DATE_LABELS = [
    ("Valabil pana la", r"Valabil\w*\s+pana\s+la"),
    ("Data expirarii", r"Data\s+expirarii(?:\s+acreditarii)?"),
]
MONTHS = {  # first three letters, Romanian + English
    "ian": 1, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "may": 5, "iun": 6, "jun": 6,
    "iul": 7, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "noi": 11, "nov": 11, "dec": 12,
}

# --- status (default ACTIVE) ---------------------------------------------------------
RX_SUSPENDED = re.compile(r"\bsuspendat[ae]?\b|\bsuspendarea\s+acreditarii\b", I)
RX_WITHDRAWN = re.compile(r"\bretras[ae]?\b|\bretragerea\s+acreditarii\b", I)

# --- standards -----------------------------------------------------------------------
# "SR EN ISO/CEI 17021-1:2015", "SR ISO/IEC TS 17021-9:2017", "SR EN ISO 9001: 2015" -> number
RX_STANDARD = re.compile(
    r"\b(?:SR\s+)?(?:EN\s+)?ISO\s*(?:/\s*(?:IEC|CEI)\s*)?(?:/?\s*TS\s*)?"
    r"(\d{4,5}(?:\s*-\s*\d{1,2}(?!\d))?)(?:\s*:\s*(?:19|20)\d{2})?", I)
# certificate: "indeplineste cerintele SR EN ISO/CEI 17021-1:2015 si este competenta ..."
RX_ACC_STD_CLAUSE = re.compile(r"indeplineste\s+cerintele\s+(.{0,150}?)\s+si\s+este\s+competent", I | S)
# annex: "indeplineste si cerintele suplimentare continute in: SR EN ISO/IEC 27006-1:2024"
RX_SUPPL_CLAUSE = re.compile(
    r"cerintele\s+suplimentare\s+continute\s+in\s*:?(.{0,250}?)(?=standard\w*\s+de\s+referinta|\n\s*nr\b|\Z)", I | S)
# annex: "Standard de referinta pentru activitatea de certificare: SR EN ISO 9001:2015"
RX_CERT_STD_CLAUSE = re.compile(
    r"standard\w*\s+de\s+referinta\s+pentru\s+activitatea\s+de\s+certificare\s*:?([^\n]*)", I)
# certificate: "competenta sa efectueze SERVICII DE CERTIFICARE ... asa cum se detaliaza"
RX_SCOPE_SENTENCE = re.compile(r"competent\w*\s+sa\s+efectueze(.{0,400}?)asa\s+cum", I | S)
# scheme wording in that sentence -> certification standard (used only when its annex is missing)
SCHEME_PHRASES = [
    (r"\bcalitatii\b(?!\s+pentru\s+dispozitive)", "ISO 9001"),
    (r"\bde\s+mediu\b", "ISO 14001"),
    (r"sanatatii\s+si\s+securitatii\s+in\s+munca", "ISO 45001"),
    (r"securitatii\s+informatiei", "ISO/IEC 27001"),
    (r"\benergiei\b", "ISO 50001"),
    (r"sigurantei\s+aliment", "ISO 22000"),
    (r"anti-?\s*mita|antimita|anti-?\s*coruptie", "ISO 37001"),
    (r"dispozitive\s+medicale", "ISO 13485"),
    (r"continuitatii\s+afacerilor", "ISO 22301"),
    (r"sigurantei\s+(?:traficului\s+)?rutier", "ISO 39001"),
    (r"evenimente\w*\s+sustenabil", "ISO 20121"),
    (r"serviciilor\s+IT|servicii\w*\s+IT\b", "ISO/IEC 20000-1"),
]

# --- EA / IAF sector codes -------------------------------------------------------------
# table column header, whitespace collapsed: "Nr. IAF", "Cod EA", "IAF", "EA code"
RX_EA_HEADER = re.compile(r"^(?:nr\.?|cod(?:ul)?|sector(?:ul)?)?\s*(?:IAF|EA)(?:\s*cod(?:e|uri)?)?\.?$", I)
# one cell value: "28", "28a" -> 28, "3.1" -> 3, "1-5" -> 1..5
RX_EA_TOKEN = re.compile(r"(?<!\d)(\d{1,2})(?:[a-z]|\.\d+)?(?:\s*[-–]\s*(\d{1,2})(?:[a-z]|\.\d+)?)?(?!\d)", I)
# letter-spaced digits in some PDFs: cell "1 2" means 12 (separate codes use commas/newlines)
RX_SPACED_DIGITS = re.compile(r"(?<!\d)(\d) +(\d)(?!\d)")
RX_ALL_CODES = re.compile(r"toate\s+(?:codurile|sectoarele)|all\s+(?:IAF\s+|EA\s+)?(?:codes|sectors)", I)
# text fallback (no ruled table, e.g. OCR): "17. 18 Masini si echipamente ..." -> row 17, IAF 18,
# or "3." alone on a line followed by a line starting with the IAF code. Leading zeros are CAEN.
RX_HAS_EA_COLUMN = re.compile(r"\b(?:IAF|EA)\b")
RX_TEXT_ROW = re.compile(r"^\s*(\d{1,2})\.\s+([1-9]\d?[a-z]?)(?=[\s,]|$)", I)
RX_TEXT_NR_ONLY = re.compile(r"^\s*(\d{1,2})\.\s*$")
RX_TEXT_LEAD_CODE = re.compile(r"^\s*([1-9]\d?[a-z]?)(?=\s|$)", I)
# =========================================================================== /PATTERNS


# --------------------------------------------------------------------------- helpers
def fold(text: str) -> str:
    """Remove diacritics one character at a time (keeps length: spans map to the original)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonical_standard(number: str) -> str:
    number = re.sub(r"\s+", "", number)
    if number in CANONICAL:
        return CANONICAL[number]
    return f"ISO/IEC {number}" if number.startswith(("17021", "27", "20000")) else f"ISO {number}"


def standards_in(folded: str) -> list[str]:
    return list(dict.fromkeys(canonical_standard(m.group(1)) for m in RX_STANDARD.finditer(folded)))


def std_number(std: str) -> str:
    return std.split()[-1]


def certificate_number(base: str, acc_std: str) -> str:
    """'SM 003' for 17021-1, 'SM 003 (27006)', 'SM 003 (50003)', 'SM 003 (37001)', ..."""
    if acc_std == "ISO/IEC 17021-1":
        return base
    if acc_std in ("ISO/IEC 27006", "ISO 50003"):
        return f"{base} ({std_number(acc_std)})"
    return f"{base} ({std_number(ALLOWED[acc_std][0])})"


def cert_sort_key(no: str):
    m = re.match(r"([A-Z]+)\s*(\d+)", no)
    return (m.group(1), int(m.group(2))) if m else (no, 0)


def parse_date(m: re.Match) -> str:
    if m.group(1):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        d, y, mo = int(m.group(4)), int(m.group(6)), MONTHS.get(m.group(5)[:3].lower())
    try:
        return date(y, mo, d).isoformat()
    except (TypeError, ValueError):
        return ""


def find_date(folded: str, labels: list[tuple[str, str]]) -> tuple[str, str, str]:
    """-> (label used, YYYY-MM-DD or '', raw matched text)"""
    for label, rx in labels:
        m = re.search(rf"{rx}\s*:?\s*(?:{RX_DATE})", folded, I)
        if m:
            return label, parse_date(m), m.group(0)
    return "", "", ""


class Review:
    FIELDS = ["source_pdf", "field", "problem", "raw_text_snippet"]

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seen: set[tuple] = set()

    def add(self, src: str, fld: str, problem: str, snippet: str = "") -> None:
        key = (src, fld, problem)
        if key not in self._seen:
            self._seen.add(key)
            self.rows.append(dict(zip(self.FIELDS, (src, fld, problem, collapse(snippet)[:300]))))


# --------------------------------------------------------------------------- text
@dataclass
class Page:
    no: int
    text: str
    folded: str
    tables: list
    ocr: bool = False


def ocr_page(path: Path, page_no: int, args: argparse.Namespace) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    if args.tesseract:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract
    images = convert_from_path(str(path), dpi=300, first_page=page_no, last_page=page_no,
                               poppler_path=args.poppler or None)
    return pytesseract.image_to_string(images[0], lang="ron+eng")


def read_pages(path: Path, rel: str, args: argparse.Namespace, review: Review) -> list[Page]:
    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for i, raw in enumerate(pdf.pages, 1):
            # drop rotated characters - the diagonal "RENAR" watermark
            page = raw.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
            text, tables, ocr = page.extract_text() or "", page.extract_tables() or [], False
            if len(text.strip()) < MIN_TEXT_CHARS:
                try:
                    text, tables, ocr = ocr_page(path, i, args), [], True
                    review.add(rel, f"page {i}", "text obtained by OCR - check every value from this page",
                               text[:200])
                except Exception as e:  # noqa: BLE001
                    review.add(rel, f"page {i}", f"no text layer and OCR failed: {type(e).__name__}: {e}")
            text = unicodedata.normalize("NFC", text)
            tables = [[[unicodedata.normalize("NFC", c) if c else c for c in row] for row in t] for t in tables]
            pages.append(Page(i, text, fold(text), tables, ocr))
    return pages


def split_documents(pages: list[Page]) -> list[list]:
    """Group pages into ['cert', None, pages] / ['annex', annex_no, pages]."""
    docs: list[list] = []
    for p in pages:
        m = RX_ANNEX_HEADER.search(p.folded)
        if m:
            no = m.group(1) or "?"
            if docs and docs[-1][0] == "annex" and docs[-1][1] == no:
                docs[-1][2].append(p)
            else:
                docs.append(["annex", no, [p]])
        elif RX_CERT_TITLE.search(p.folded) or not docs:
            docs.append(["cert", None, [p]])
        else:
            docs[-1][2].append(p)  # header-less continuation page
    return docs


def org_block(text: str, folded: str, anchor: re.Pattern) -> tuple[str, str, str, str] | None:
    """-> (name, address, operating unit after 'prin', block text) or None if anchor missing."""
    m = anchor.search(folded)
    if not m:
        return None
    name: list[str] = []
    addr: list[str] = []
    block: list[str] = []
    operator, in_addr, prin_pending = "", False, False
    for o, f in zip(text[m.end():].splitlines(), folded[m.end():].splitlines()):
        o, f = o.strip(), f.strip()
        if not o:
            continue
        if RX_ORG_BLOCK_END.match(f) or len(block) >= ORG_BLOCK_MAX_LINES:
            break
        block.append(o)
        if prin_pending:
            operator, prin_pending = o, False
            continue
        pm = RX_PRIN.match(f)
        if pm:
            operator = o[pm.start(1):].strip()
            prin_pending = not operator
            continue
        if not in_addr and RX_ADDRESS_HINT.search(f):
            in_addr = True
        (addr if in_addr else name).append(o)
    return " ".join(name), " ".join(addr), operator, "\n".join(block)


def find_contacts(block: str) -> tuple[str, str, str]:
    f = fold(block)
    phone = next((m.group(1).strip() for m in RX_PHONE.finditer(f)), "")
    email = next((block[m.start():m.end()] for m in RX_EMAIL.finditer(f)
                  if not RX_IGNORE_CONTACT.search(m.group(0))), "")
    web = next((block[m.start():m.end()] for m in RX_WEBSITE.finditer(f)
                if not RX_IGNORE_CONTACT.search(m.group(0))), "")
    return phone, email, web


# --------------------------------------------------------------------------- parsing
@dataclass
class CertPart:
    source: str
    base_no: str = ""
    name: str = ""
    address: str = ""
    operator: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    acc_stds: list[str] = field(default_factory=list)
    schemes: list[str] = field(default_factory=list)
    issue: str = ""
    issue_label: str = ""
    expiry: str = ""
    status: str = "ACTIVE"
    status_snippet: str = ""
    snippet: str = ""


@dataclass
class AnnexPart:
    source: str
    base_no: str = ""
    annex_no: str = ""
    name: str = ""
    address: str = ""
    cert_stds: list[str] = field(default_factory=list)
    suppl_stds: list[str] = field(default_factory=list)
    ea: set[int] = field(default_factory=set)
    ea_note: str = ""


def parse_cert(text: str, folded: str, src: str, review: Review) -> CertPart:
    c = CertPart(src, snippet=text[:300])
    m = RX_CERT_TITLE.search(folded)
    if m:
        c.base_no = f"{m.group(1).upper()} {m.group(2)}"
    else:
        review.add(src, "certificate_number", "not found on certificate page", text[:300])

    org = org_block(text, folded, RX_CERT_ORG_ANCHOR)
    if org:
        c.name, c.address, c.operator, block = org
        c.phone, c.email, c.website = find_contacts(block)

    m = RX_ACC_STD_CLAUSE.search(folded)
    if m:
        c.acc_stds = standards_in(m.group(1))
    else:
        review.add(src, "accreditation_standard", "'indeplineste cerintele ...' clause not found", text[:300])

    m = RX_SCOPE_SENTENCE.search(folded)
    sentence = m.group(1) if m else ""
    c.schemes = [std for rx, std in SCHEME_PHRASES if re.search(rx, sentence, I)]

    c.issue_label, c.issue, raw = find_date(folded, ISSUE_DATE_LABELS)
    if raw and not c.issue:
        review.add(src, "issue_date", "date found but not a valid calendar date", raw)
    _, c.expiry, raw = find_date(folded, EXPIRY_DATE_LABELS)
    if raw and not c.expiry:
        review.add(src, "expiry_date", "date found but not a valid calendar date", raw)

    for rx, status in ((RX_WITHDRAWN, "WITHDRAWN"), (RX_SUSPENDED, "SUSPENDED")):
        m = rx.search(folded)
        if m:
            c.status, c.status_snippet = status, text[max(0, m.start() - 100):m.end() + 100]
            break
    return c


def ea_from_tables(page_tables: list[list], src: str, review: Review) -> tuple[bool, set[int], list[str]]:
    """-> (EA column found, codes, headers of other tables)"""
    col = ncols = None
    codes: set[int] = set()
    other: list[str] = []
    for tables in page_tables:
        for t in tables:
            if not t or not t[0]:
                continue
            header = [collapse(fold(c or "")) for c in t[0]]
            idx = next((i for i, h in enumerate(header) if RX_EA_HEADER.match(h)), None)
            if idx is not None:
                col, ncols, rows = idx, len(header), t[1:]
            elif col is not None and len(header) == ncols:
                rows = t  # continuation table without a repeated header
            else:
                other.append(" | ".join(h for h in header if h))
                continue
            for row in rows:
                cell = row[col] if col < len(row) else None
                if cell and cell.strip():
                    codes |= ea_tokens(cell, src, review)
    return col is not None, codes, other


def ea_tokens(cell: str, src: str, review: Review) -> set[int]:
    out: set[int] = set()
    tokens = RX_EA_TOKEN.findall(RX_SPACED_DIGITS.sub(r"\1\2", cell))
    if not tokens:
        review.add(src, "ea_codes", "IAF/EA cell without a code", cell)
    for a, b in tokens:
        lo, hi = int(a), int(b or a)
        for n in range(lo, hi + 1) if lo <= hi else (lo, hi):
            if 1 <= n <= 39:
                out.add(n)
            else:
                review.add(src, "ea_codes", f"code {n} outside 1-39 - dropped", cell)
    return out


def ea_from_text(folded: str, src: str, review: Review) -> set[int]:
    codes: set[int] = set()
    last_row = 0
    lines = folded.splitlines()
    for i, line in enumerate(lines):
        nr = code = None
        m = RX_TEXT_ROW.match(line)
        if m:
            nr, code = int(m.group(1)), m.group(2)
        elif (m := RX_TEXT_NR_ONLY.match(line)) and i + 1 < len(lines):
            n = RX_TEXT_LEAD_CODE.match(lines[i + 1])
            if n:
                nr, code = int(m.group(1)), n.group(1)
        if nr is not None and nr > last_row:  # row numbers only go up: skips stray matches
            last_row = nr
            codes |= ea_tokens(code, src, review)
    return codes


def parse_annex(text: str, folded: str, page_tables: list[list], src: str, review: Review) -> AnnexPart:
    a = AnnexPart(src)
    m = RX_ANNEX_HEADER.search(folded)
    a.annex_no, a.base_no = m.group(1) or "", f"{m.group(2).upper()} {m.group(3)}"
    org = org_block(text, folded, RX_ANNEX_ORG_ANCHOR)
    if org:
        a.name, a.address = org[0], org[1]

    m = RX_CERT_STD_CLAUSE.search(folded)
    a.cert_stds = standards_in(m.group(1)) if m else []
    if not a.cert_stds:
        a.cert_stds = [s for s in standards_in(folded) if s in CERT_TO_ACC]
        problem = ("no 'Standard de referinta' line - certification standard taken from annex body"
                   if a.cert_stds else "certification standard not found in annex")
        review.add(src, "certification_standard", problem, text[:300])
    m = RX_SUPPL_CLAUSE.search(folded)
    a.suppl_stds = standards_in(m.group(1)) if m else []

    has_col, codes, other_headers = ea_from_tables(page_tables, src, review)
    if codes:
        a.ea = codes
    elif not has_col and RX_HAS_EA_COLUMN.search(text):
        a.ea = ea_from_text(folded, src, review)
        if a.ea:
            review.add(src, "ea_codes", "no IAF/EA table detected - codes parsed from plain text, verify",
                       ",".join(map(str, sorted(a.ea))))
    if not a.ea:
        if (m := RX_ALL_CODES.search(folded)):
            a.ea, a.ea_note = set(ALL_EA), "annex states all IAF/EA codes; set to 1-39"
            review.add(src, "ea_codes", "'all codes' wording - set to 1-39, check for exceptions",
                       text[max(0, m.start() - 100):m.end() + 150])
        else:
            what = f" (annex table: {other_headers[0]})" if other_headers else ""
            a.ea, a.ea_note = set(ALL_EA), f"annex gives no IAF/EA sector list{what}; defaulted to 1-39"
            review.add(src, "ea_codes", "no IAF/EA sector list - defaulted to 1-39", text[:300])
    return a


def process_pdf(path: Path, rel: str, args: argparse.Namespace, review: Review,
                debug_dir: Path | None) -> tuple[list[CertPart], list[AnnexPart]]:
    pages = read_pages(path, rel, args, review)
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        dump = "\n".join(f"===== page {p.no}{' (OCR)' if p.ocr else ''}\n{p.text}" for p in pages)
        (debug_dir / (rel.replace("/", "__")[:-4] + ".txt")).write_text(dump, encoding="utf-8")

    certs: list[CertPart] = []
    annexes: list[AnnexPart] = []
    for kind, _, doc_pages in split_documents(pages):
        text = "\n".join(p.text for p in doc_pages)
        if kind == "cert":
            certs.append(parse_cert(text, fold(text), rel, review))
        else:
            annexes.append(parse_annex(text, fold(text), [p.tables for p in doc_pages], rel, review))
    if not pages:
        review.add(rel, "file", "PDF has no pages")
    return [c for c in certs if c.base_no], annexes


# --------------------------------------------------------------------------- merge
def build(certs: list[CertPart], annexes: list[AnnexPart], review: Review):
    groups: dict[str, tuple[list[CertPart], list[AnnexPart]]] = {}
    for c in certs:
        groups.setdefault(c.base_no, ([], []))[0].append(c)
    for a in annexes:
        groups.setdefault(a.base_no, ([], []))[1].append(a)

    bodies: dict[str, dict] = {}
    accs: list[dict] = []
    scopes: list[dict] = []
    for base in sorted(groups, key=cert_sort_key):
        g_certs, g_annexes = groups[base]
        cert = g_certs[0] if g_certs else None
        src = cert.source if cert else g_annexes[0].source
        for other in g_certs[1:]:
            for attr in ("name", "issue", "expiry", "status"):
                if getattr(other, attr) != getattr(cert, attr):
                    review.add(other.source, attr, f"differs from {cert.source} for {base}: "
                               f"'{getattr(other, attr)}' vs '{getattr(cert, attr)}' (first kept)")

        name = (cert.name if cert else "") or next((a.name for a in g_annexes if a.name), "")
        if not name:
            review.add(src, "name", f"certification body name not found for {base} - certificate not exported",
                       cert.snippet if cert else "")
            continue
        if cert and not cert.name:
            review.add(src, "name", "name not found on certificate - taken from annex", name)
        address = (cert.address if cert else "") or next((a.address for a in g_annexes if a.address), "")
        if not address:
            review.add(src, "address", "not found", cert.snippet if cert else "")
        if cert and cert.operator:
            review.add(src, "name", f"certificate says 'prin {cert.operator}' (operating unit) - "
                       "name kept as the legal entity", f"{name} prin {cert.operator}")

        body = bodies.setdefault(name, {"name": name, "country": COUNTRY, "phone": "", "email": "",
                                        "website": "", "address": "", "_source": src})
        for k, v in (("address", address), ("phone", cert.phone if cert else ""),
                     ("email", cert.email if cert else ""), ("website", cert.website if cert else "")):
            body[k] = body[k] or v

        # dates / status
        if not cert:
            review.add(src, "certificate", f"no certificate page found for {base} - "
                       "issue/expiry unknown, status defaulted to ACTIVE")
        else:
            if not cert.issue:
                review.add(src, "issue_date", "not found", cert.snippet)
            elif cert.issue_label in ISSUE_DATE_LOGGED:
                review.add(src, "issue_date", f"taken from '{cert.issue_label}' (no renewal/issue date) - "
                           "may predate the current accreditation cycle", cert.issue)
            if not cert.expiry:
                review.add(src, "expiry_date", "not found", cert.snippet)
            if cert.status_snippet:
                review.add(src, "status", f"set to {cert.status} from document wording", cert.status_snippet)
            else:
                review.add(src, "status", "no suspendat/retras wording - defaulted to ACTIVE")
            for s in cert.acc_stds:
                if s not in ALLOWED:
                    review.add(src, "accreditation_standard", f"{s} not in allowed list - not exported")

        # certification standards -> EA codes
        by_std: dict[str, dict] = {}
        for a in g_annexes:
            for s in a.cert_stds:
                e = by_std.setdefault(s, {"ea": set(), "notes": [], "sources": []})
                e["ea"] |= a.ea
                e["notes"] += [a.ea_note] if a.ea_note else []
                e["sources"].append(a.source)
            expected = {CERT_TO_ACC.get(s) for s in a.cert_stds}
            for s in a.suppl_stds:
                if s not in ALLOWED:
                    review.add(a.source, "accreditation_standard",
                               f"supplementary standard {s} not in allowed list - not exported")
                elif s not in expected:
                    review.add(a.source, "accreditation_standard",
                               f"annex names {s} but its certification standard(s) "
                               f"{', '.join(a.cert_stds) or '-'} belong under another scheme")
        if cert:
            for s in cert.schemes:
                if s not in by_std:
                    by_std[s] = {"ea": set(ALL_EA), "sources": [],
                                 "notes": ["no annex found; standard inferred from certificate scope wording; "
                                           "defaulted to 1-39"]}
                    review.add(src, "certification_standard", f"{s} inferred from certificate wording "
                               f"(annex not found) - EA codes defaulted to 1-39")

        per_acc: dict[str, list[str]] = {}
        for s in by_std:
            if s in CERT_TO_ACC:
                per_acc.setdefault(CERT_TO_ACC[s], []).append(s)
            else:
                review.add(", ".join(by_std[s]["sources"]) or src, "certification_standard",
                           f"{s} not in allowed list - not exported")
        if not per_acc and cert:
            per_acc = {s: [] for s in cert.acc_stds if s in ALLOWED}
            review.add(src, "accredited_scopes", f"no certification standard found for {base} - "
                       "accreditation exported without scope")

        for acc in sorted(per_acc, key=list(ALLOWED).index):
            number = certificate_number(base, acc)
            stds = sorted(per_acc[acc], key=ALLOWED[acc].index)
            sources = ([cert.source] if cert else []) + [p for s in stds for p in by_std[s]["sources"]]
            accs.append({
                "company_name": name, "accreditation_standard": acc, "certificate_number": number,
                "status": cert.status if cert else "ACTIVE", "issue_date": cert.issue if cert else "",
                "expiry_date": cert.expiry if cert else "", "proof_url": "",
                "source_pdf": "; ".join(dict.fromkeys(sources)),
            })
            for s in stds:
                e = by_std[s]
                scopes.append({
                    "certificate_number": number, "certification_standard": s,
                    "ea_codes": ",".join(map(str, sorted(e["ea"]))),
                    "note": "; ".join(dict.fromkeys(e["notes"])),
                    "_source": "; ".join(dict.fromkeys(e["sources"])) or src,
                })

    for b in bodies.values():
        missing = [k for k in ("phone", "email", "website") if not b[k]]
        if missing:
            review.add(b["_source"], "/".join(missing), "not printed in the PDF(s) - left empty")
    return list(bodies.values()), accs, scopes


# --------------------------------------------------------------------------- output
def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sql_str(v) -> str:
    return "NULL" if v in (None, "") else "'" + str(v).replace("'", "''") + "'"


def values_lines(rows: list[dict], fmt, source_of) -> list[str]:
    lines, prev = [], None
    for i, r in enumerate(rows):
        if source_of(r) != prev:
            prev = source_of(r)
            lines.append(f"    -- source: {prev}")
        lines.append("    " + fmt(r) + ("," if i < len(rows) - 1 else ""))
    return lines


def write_sql(path: Path, bodies: list[dict], accs: list[dict], scopes: list[dict]) -> None:
    out = ["-- Generated by extract_renar.py from RENAR certificate/annex PDFs.",
           "-- Requires accreditation_bodies row with code 'RENAR'.", ""]
    if bodies:
        out.append("INSERT INTO certification_bodies (name, country, phone, email, website, address) VALUES")
        out += values_lines(bodies, lambda b: "(" + ", ".join(sql_str(b[k]) for k in (
            "name", "country", "phone", "email", "website", "address")) + ")", lambda b: b["_source"])
        out[-1] += ";"
        out.append("")
    for status in dict.fromkeys(a["status"] for a in accs):
        rows = [a for a in accs if a["status"] == status]
        out += ["INSERT INTO accreditations",
                "    (certification_body_id, accreditation_body_id, accreditation_standard, certificate_number,",
                "     status, issue_date, expiry_date, proof_url)",
                f"SELECT cb.id, ab.id, v.std, v.cert, {sql_str(status)}, v.issued::date, v.expires::date, "
                f"{sql_str(PROOF_URL_SQL)}",
                "FROM (VALUES"]
        out += values_lines(rows, lambda a: "(" + ", ".join(sql_str(a[k]) for k in (
            "company_name", "accreditation_standard", "certificate_number", "issue_date", "expiry_date")) + ")",
            lambda a: a["source_pdf"])
        out += [") AS v(cb_name, std, cert, issued, expires)",
                "JOIN certification_bodies cb ON cb.name = v.cb_name",
                "JOIN accreditation_bodies ab ON ab.code = 'RENAR';", ""]
    rows = [s for s in scopes if s["ea_codes"]]
    if rows:
        out += ["INSERT INTO accredited_scopes (accreditation_id, accreditation_standard, certification_standard, ea_code)",
                "SELECT a.id, a.accreditation_standard, v.std, ea",
                "FROM (VALUES"]
        out += values_lines(rows, lambda s: f"({sql_str(s['certificate_number'])}, "
                            f"{sql_str(s['certification_standard'])}, "
                            f"ARRAY[{s['ea_codes'].replace(',', ', ')}])", lambda s: s["_source"])
        out += [") AS v(cert, std, eas)",
                "CROSS JOIN LATERAL unnest(v.eas) AS ea",
                "JOIN accreditations a ON a.certificate_number = v.cert",
                "JOIN accreditation_bodies ab ON ab.id = a.accreditation_body_id AND ab.code = 'RENAR';", ""]
    path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------------- main
def parse_args(argv=None) -> argparse.Namespace:
    default_tess = os.environ.get("TESSERACT_CMD", "")
    win_tess = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if not default_tess and win_tess.exists():
        default_tess = str(win_tess)
    p = argparse.ArgumentParser(description="Extract RENAR accreditation PDFs to CSV + PostgreSQL seed.")
    p.add_argument("pdf_folder", help="Folder with PDFs (searched recursively)")
    p.add_argument("--out", required=True, help="Output folder")
    p.add_argument("--debug", action="store_true", help="Also save each PDF's raw extracted text")
    p.add_argument("--tesseract", default=default_tess, help="tesseract.exe path (env TESSERACT_CMD)")
    p.add_argument("--poppler", default=os.environ.get("POPPLER_PATH", ""),
                   help="Poppler bin folder (env POPPLER_PATH)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    in_dir, out_dir = Path(args.pdf_folder).resolve(), Path(args.out).resolve()
    if not in_dir.is_dir():
        print(f"Not a folder: {in_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = out_dir / "debug" if args.debug else None

    review = Review()
    certs: list[CertPart] = []
    annexes: list[AnnexPart] = []
    seen: set[str] = set()
    pdfs = sorted(in_dir.rglob("*.pdf"), key=lambda p: str(p).lower())
    duplicates = failed = 0
    for i, path in enumerate(pdfs, 1):
        rel = path.relative_to(in_dir).as_posix()
        print(f"[{i}/{len(pdfs)}] {rel}")
        try:
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            if digest in seen:
                duplicates += 1
                continue
            seen.add(digest)
            c, a = process_pdf(path, rel, args, review, debug_dir)
            certs += c
            annexes += a
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
            failed += 1
            review.add(rel, "file", f"could not process: {type(e).__name__}: {e}")

    bodies, accs, scopes = build(certs, annexes, review)

    write_csv(out_dir / "certification_bodies.csv",
              ["name", "country", "phone", "email", "website", "address"], bodies)
    write_csv(out_dir / "accreditations.csv",
              ["company_name", "accreditation_standard", "certificate_number", "status",
               "issue_date", "expiry_date", "proof_url", "source_pdf"], accs)
    write_csv(out_dir / "accredited_scopes.csv",
              ["certificate_number", "certification_standard", "ea_codes", "note"], scopes)
    write_csv(out_dir / "review.csv", Review.FIELDS, review.rows)
    write_sql(out_dir / "seed_romania.sql", bodies, accs, scopes)

    print()
    print(f"PDFs processed : {len(pdfs)} ({duplicates} identical copies skipped, {failed} failed)")
    print(f"Companies      : {len(bodies)}")
    print(f"Accreditations : {len(accs)}")
    print(f"Scope rows     : {len(scopes)}")
    print(f"Review items   : {len(review.rows)}")
    print(f"Output         : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
