#!/usr/bin/env python3
"""
extract_renar_v2.py - RENAR accreditation PDFs (Certificat + Anexa) -> CSV + PostgreSQL seed.

Input: the tree written by scraper.py
    <pdf_folder>/<5.2.x Category>/<COMPANY>__<CERT_NO>/Certificat.pdf, Anexa.pdf
The PDF text is the source of truth. Folder names are only used to cross-check the category's
expected certification standard and the certificate number (company names in folder names are
ASCII-only and may be truncated, so they are never used).

Everything is grouped by RENAR certificate number ("SM 112"): the certificate is copied into every
category folder, so its copies are compared and the most recently updated one is kept; the annexes
from all category folders together form the company's scope.

Output (--out): certification_bodies.csv, accreditations.csv, accredited_scopes.csv, review.csv,
seed_romania.sql, and with --debug: debug/*.txt (raw text + extracted tables of every PDF).

Usage:
    python extract_renar_v2.py output/pdfs --out output/db [--debug]
                               [--tesseract PATH] [--poppler PATH]    # OCR only, see README
Tests:
    pytest tests
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
PROOF_URL = "https://www.renar.ro"
MIN_TEXT_CHARS = 50          # a page with less extractable text than this is OCR'd
ALL_EA = list(range(1, 40))

# ===========================================================================
# PATTERNS - every regular expression is here. Use --debug to see the raw text they run on.
#
# They run on fold()ed text: diacritics removed (ş/ș->s, ţ/ț->t, ă/â->a, î->i, Ü->U), so write
# them WITHOUT diacritics. fold() keeps the string length, so a match position also indexes
# the original text, which is where names and addresses are copied from.
# ===========================================================================
I, S = re.IGNORECASE, re.DOTALL

# --- certificate number ----------------------------------------------------------------
_NO = r"([A-Z]{2,5})\s*[-.]?\s*(\d{1,4})"     # "SM 112", "SMFS 001" (prefix is case-sensitive)
# certificate title: "CERTIFICAT DE ACREDITARE\nNr. SM 112"
RX_CERT_TITLE = re.compile(r"(?i:CERTIFICAT\s+DE\s+ACREDITARE\s+(?:nr\.?|numar)\s*:?)\s*" + _NO)
# top of every annex page: "Anexa nr. 1 la Certificatul de Acreditare nr. SM 112"
RX_ANNEX_HEADER = re.compile(
    r"(?i:Anexa(?:\s+nr\.?\s*(\d{1,2}))?\s+la\s+certificatul\s+de\s+acreditare\s+nr\.?)\s*" + _NO)
# company folder: "TUV_AUSTRIA_ROMANIA_SRL__SM_112" (truncated names may have lost it)
RX_FOLDER_NO = re.compile(r"__([A-Za-z]{2,5})_(\d{1,4})$")
# category folder: "5.2.1 Calitate" -> "Calitate"
RX_CATEGORY_PREFIX = re.compile(r"^\d+(?:\.\d+)*\s*")

# --- organisation block -------------------------------------------------------------------
# certificate: "...atestă că organizaţia:\nNAME\naddress\nprin\nTRADE NAME\nîndeplineşte ..."
# annex:       "Data emiterii Anexei nr. 1: ...\nNAME\nprin TRADE NAME\naddress\nîndeplineşte ..."
# Name lines have no lower-case letters; the first line with lower case starts the address.
RX_CERT_ORG_ANCHOR = re.compile(r"atesta\s+ca\s+organizatia\s*:?", I)
RX_ANNEX_ORG_ANCHOR = re.compile(r"Data\s+emiterii\s+anexei[^\n]*", I)
RX_ORG_END = re.compile(
    r"^(?:a\s+demonstrat|indeplineste|standard\w*\s+de\s+referinta|nr\.?(?:\s|$)|descrierea)", I)
RX_PRIN = re.compile(r"^prin\b\s*(.*)$", I)        # "prin TAR CERT" = trade name / operating unit
ORG_MAX_LINES = 8

# --- dates (DD.MM.YYYY) -----------------------------------------------------------------
RX_DATE = r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})"
DATE_LABELS = {
    "initial_date": r"Data\s+acreditarii\s+initiale",
    "renewal_date": r"Data\s+re-?innoirii\s+acreditar\w*",      # "acreditării" and "acreditare"
    "updated_date": r"Data\s+actualizarii",
    "expiry_date": r"Data\s+expirarii(?:\s+acreditar\w*)?",
    "annex_date": r"Data\s+emiterii\s+anexei(?:\s+nr\.?\s*\d+)?",
}
# certificate: "Prezentul certificat este însoţit de Anexele nr. 1/25.09.2026 (3 pagini), nr. 2/...
#               și nr. 4/30.03.2026 (1 pagină), părți integrante ale acestuia."
RX_ANNEX_LIST = re.compile(r"insotit\s+de\s+anex\w*(.{0,800}?)part[ie]\s+integrant", I | S)
RX_ANNEX_LIST_ITEM = re.compile(r"nr\.?\s*(\d{1,2})\s*/\s*" + RX_DATE, I)

# --- status (otherwise ACTIVE) -----------------------------------------------------------
RX_SUSPENDED = re.compile(r"\bsuspendat\w*", I)
RX_WITHDRAWN = re.compile(r"\bretras\w*|\bretrager\w*", I)

# --- standards ---------------------------------------------------------------------------
# "SR EN ISO/CEI 17021-1:2015", "SR ISO/IEC TS 17021-10:2018", "SR EN ISO 9001: 2015"
# group 1 = IEC/CEI if written, group 2 = number
RX_STANDARD = re.compile(
    r"\b(?:SR\s+)?(?:EN\s+)?ISO\s*(?:/\s*(IEC|CEI)\s*)?(?:/?\s*TS\s+)?"
    r"(\d{4,5}(?:\s*-\s*\d{1,2}(?!\d))?)(?:\s*:\s*(?:19|20)\d{2})?", I)
# annex: "Standard de referinţă pentru activitatea de certificare: SR EN ISO 9001:2015"
RX_CERT_STD_LINE = re.compile(
    r"standard\w*\s+de\s+referinta\s+pentru\s+activitatea\s+de\s+certificare\s*:?([^\n]*)", I)
# annex: "îndeplineşte şi cerinţele suplimentare conţinute în: SR EN ISO/IEC 17021-3:2019"
# (the clause line plus one continuation line)
RX_SUPPL_CLAUSE = re.compile(
    r"cerintele\s+suplimentare\s+continute\s+in\s*:?([^\n]*(?:\n(?!\s*(?:standard|nr\b))[^\n]*)?)", I)

# --- IAF / EA sector codes -------------------------------------------------------------------
# table column header, whitespace collapsed: "Nr. IAF", "Cod EA", "IAF"
RX_EA_HEADER = re.compile(r"^(?:nr\.?|cod(?:ul)?)?\s*(?:IAF|EA)(?:\s*(?:cod\w*|code\w*))?\.?$", I)
# one cell: "28", "28a" -> 28, "3.1" -> 3, "1-5" -> 1..5   (CAEN codes are in another column)
RX_EA_TOKEN = re.compile(r"(?<!\d)(\d{1,2})(?:[a-z]|\.\d+)?(?:\s*[-–]\s*(\d{1,2})(?:[a-z]|\.\d+)?)?(?!\d)", I)
# letter-spaced digits in some tables: cell "3 0" means 30 (separate codes use newlines/commas)
RX_SPACED_DIGITS = re.compile(r"(?<!\d)(\d) +(\d)(?!\d)")
RX_ALL_CODES = re.compile(r"toate\s+(?:codurile|sectoarele)|all\s+(?:IAF\s+|EA\s+)?(?:codes|sectors)", I)
# text fallback when no ruled table is detected (e.g. OCR): "17. 18 Masini si echipamente ..."
# -> row 17, IAF 18; or "3." alone on a line followed by a line starting with the IAF code.
RX_HAS_EA_COLUMN = re.compile(r"\b(?:IAF|EA)\b")
RX_TEXT_ROW = re.compile(r"^\s*(\d{1,2})\.\s+([1-9]\d?[a-z]?)(?=[\s,]|$)", I)
RX_TEXT_NR_ONLY = re.compile(r"^\s*(\d{1,2})\.\s*$")
RX_TEXT_LEAD_CODE = re.compile(r"^\s*([1-9]\d?[a-z]?)(?=\s|$)", I)
# =========================================================================== /PATTERNS

# --------------------------------------------------------------------------- standards tables
# category folder (without "5.2.x ", folded, lower case) -> expected certification standard
CATEGORY_STANDARD = {
    "calitate": "ISO 9001",
    "mediu": "ISO 14001",
    "calitate pentru dispozitive medicale": "ISO 13485",
    "sanatate si securitate in munca": "ISO 45001",
    "energie": "ISO 50001",
    "securitatea informatiei": "ISO/IEC 27001",
    "siguranta alimentelor": "ISO 22000",
    "anti-mita": "ISO 37001",
}

ACC_17021_1 = "ISO/IEC 17021-1"
# (supplementary standard or None, certification standards) -> accreditation standard
SCHEMES: list[tuple[str | None, tuple[str, ...], str]] = [
    ("ISO/IEC 17021-2", ("ISO 14001",), ACC_17021_1),
    ("ISO/IEC 17021-3", ("ISO 9001",), ACC_17021_1),
    ("ISO/IEC 17021-10", ("ISO 45001",), ACC_17021_1),
    (None, ("ISO 13485",), ACC_17021_1),
    ("ISO/IEC 27006", ("ISO/IEC 27001", "ISO/IEC 27701", "ISO/IEC 27017", "ISO/IEC 27018"), "ISO/IEC 27006"),
    ("ISO 50003", ("ISO 50001",), "ISO 50003"),
    ("ISO 22003-1", ("ISO 22000",), "ISO 22003-1"),
    ("ISO/IEC 17021-4", ("ISO 20121",), "ISO/IEC 17021-4"),
    ("ISO/IEC 17021-6", ("ISO 22301",), "ISO/IEC 17021-6"),
    ("ISO/IEC 17021-7", ("ISO 39001",), "ISO/IEC 17021-7"),
    ("ISO/IEC 17021-9", ("ISO 37001",), "ISO/IEC 17021-9"),
    ("ISO/IEC 20000-6", ("ISO/IEC 20000-1",), "ISO/IEC 20000-6"),
]
ACC_ORDER = list(dict.fromkeys(acc for *_, acc in SCHEMES))
# bare number -> canonical name, e.g. "17021-3" -> "ISO/IEC 17021-3" (also when IEC isn't written)
KNOWN_STANDARDS = {s.split()[-1]: s for sup, certs, acc in SCHEMES for s in (sup, acc, *certs) if s}
STANDARD_ALIASES = {"27006-1": "27006"}


def std_number(std: str) -> str:
    return std.split()[-1]


# "SM 112 (27006)": the code of the certification standard the scheme covers, or the
# accreditation standard's own code when it covers several (27006)
CERT_SUFFIX = {}
for _acc in ACC_ORDER:
    _certs = list(dict.fromkeys(c for _, cs, a in SCHEMES if a == _acc for c in cs))
    CERT_SUFFIX[_acc] = std_number(_acc) if len(_certs) > 1 else std_number(_certs[0])


# --------------------------------------------------------------------------- helpers
def fold(text: str) -> str:
    """Remove diacritics one character at a time (keeps length: spans map to the original)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def same_text(a: str, b: str) -> bool:
    """Equal ignoring case, diacritics, spacing and punctuation."""
    key = lambda s: re.sub(r"[\W_]+", "", fold(s).lower())  # noqa: E731
    return key(a) == key(b)


def normalize_standard(raw: str) -> str:
    """'SR EN ISO/CEI 17021-1:2015' -> 'ISO/IEC 17021-1'; '' if no ISO standard in raw."""
    m = RX_STANDARD.search(fold(raw))
    if not m:
        return ""
    number = re.sub(r"\s+", "", m.group(2))
    number = STANDARD_ALIASES.get(number, number)
    if number in KNOWN_STANDARDS:
        return KNOWN_STANDARDS[number]
    return f"ISO/IEC {number}" if m.group(1) else f"ISO {number}"


def standards_in(folded: str) -> list[tuple[str, str]]:
    """-> [(normalised standard, raw text)] in order, without repeats."""
    out: dict[str, str] = {}
    for m in RX_STANDARD.finditer(folded):
        out.setdefault(normalize_standard(m.group(0)), m.group(0))
    return list(out.items())


def format_no(prefix: str, digits: str) -> str:
    return f"{prefix.upper()} {digits}"


def no_key(no: str) -> tuple:
    m = re.match(r"([A-Z]+)\s*(\d+)", no or "")
    return (m.group(1), int(m.group(2))) if m else (no or "", 0)


def make_date(d: str, m: str, y: str) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


class Review:
    FIELDS = ["certificate_number", "source_pdf", "field", "problem", "raw_text_snippet"]

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seen: set[tuple] = set()

    def add(self, no: str, src: str, fld: str, problem: str, snippet: str = "") -> None:
        key = (no, src, fld, problem)
        if key not in self._seen:
            self._seen.add(key)
            self.rows.append(dict(zip(self.FIELDS, (no, src, fld, problem, collapse(snippet)[:300]))))


def find_date(folded: str, label: str, log) -> str:
    rx = DATE_LABELS[label]
    m = re.search(rf"{rx}\s*:?\s*{RX_DATE}", folded, I)
    if m:
        value = make_date(*m.groups()[-3:])
        if not value:
            log(label, "not a valid calendar date - left empty", m.group(0))
        return value
    m = re.search(rx, folded, I)
    if m:
        log(label, "label found without a DD.MM.YYYY date - left empty", folded[m.start():m.end() + 60])
    return ""


def find_status(text: str, folded: str) -> tuple[str, str]:
    """-> (ACTIVE / SUSPENDED / WITHDRAWN, snippet of the wording that decided it)"""
    for rx, status in ((RX_WITHDRAWN, "WITHDRAWN"), (RX_SUSPENDED, "SUSPENDED")):
        m = rx.search(folded)
        if m:
            return status, text[max(0, m.start() - 100):m.end() + 100]
    return "ACTIVE", ""


STATUS_RANK = {"ACTIVE": 0, "SUSPENDED": 1, "WITHDRAWN": 2}


# --------------------------------------------------------------------------- reading PDFs
@dataclass
class Page:
    no: int
    text: str
    folded: str
    tables: list
    ocr: bool = False


@dataclass
class Folder:
    """What the folder path says - only used for cross-checks and fallbacks."""
    category: str = ""
    expected_std: str = ""
    company_dir: str = ""
    number: str = ""


def folder_info(rel: str) -> Folder:
    parts = rel.split("/")
    f = Folder(company_dir="/".join(parts[:-1]))
    if len(parts) >= 3:
        f.category = parts[-3]
        key = collapse(fold(RX_CATEGORY_PREFIX.sub("", f.category))).lower()
        f.expected_std = CATEGORY_STANDARD.get(key, "")
    if len(parts) >= 2 and (m := RX_FOLDER_NO.search(parts[-2])):
        f.number = format_no(*m.groups())
    return f


def ocr_page(path: Path, page_no: int, args: argparse.Namespace) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    if args.tesseract:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract
    images = convert_from_path(str(path), dpi=300, first_page=page_no, last_page=page_no,
                               poppler_path=args.poppler or None)
    return pytesseract.image_to_string(images[0], lang="ron+eng")


def read_pages(path: Path, rel: str, no: str, args: argparse.Namespace, review: Review) -> list[Page]:
    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for i, raw in enumerate(pdf.pages, 1):
            # drop rotated characters - the diagonal "RENAR" watermark
            page = raw.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
            text, tables, ocr = page.extract_text() or "", page.extract_tables() or [], False
            if len(text.strip()) < MIN_TEXT_CHARS:
                try:
                    text, tables, ocr = ocr_page(path, i, args), [], True
                    review.add(no, rel, f"page {i}", "no text layer - text obtained by OCR, check every "
                               "value from this page", text[:200])
                except Exception as e:  # noqa: BLE001
                    review.add(no, rel, f"page {i}", f"no text layer and OCR failed: {type(e).__name__}: {e}")
            text = unicodedata.normalize("NFC", text)
            tables = [[[unicodedata.normalize("NFC", c) if c else c for c in row] for row in t] for t in tables]
            pages.append(Page(i, text, fold(text), tables, ocr))
    return pages


def debug_dump(pages: list[Page]) -> str:
    out = []
    for p in pages:
        out.append(f"===== page {p.no}{' (OCR)' if p.ocr else ''}\n{p.text}")
        for n, t in enumerate(p.tables, 1):
            out.append(f"----- page {p.no} table {n}")
            out += [" | ".join(collapse(c or "") for c in row) for row in t]
    return "\n".join(out) + "\n"


def split_documents(pages: list[Page]) -> list[tuple[str, list[Page]]]:
    """Group pages into ('cert', pages) / ('annex', pages); a PDF may hold several documents."""
    docs: list[tuple[str, list[Page]]] = []
    current_annex = None
    for p in pages:
        m = RX_ANNEX_HEADER.search(p.folded)
        if m:
            key = (m.group(1), m.group(2), m.group(3))
            if docs and docs[-1][0] == "annex" and key == current_annex:
                docs[-1][1].append(p)
            else:
                docs.append(("annex", [p]))
                current_annex = key
        elif RX_CERT_TITLE.search(p.folded) or not docs:
            docs.append(("cert", [p]))
        else:
            docs[-1][1].append(p)  # continuation page without a header
    return docs


# --------------------------------------------------------------------------- parsing
@dataclass
class Cert:
    source: str
    folder: Folder
    number: str = ""
    legal_name: str = ""
    trade_name: str = ""
    address: str = ""
    initial_date: str = ""
    renewal_date: str = ""
    updated_date: str = ""
    expiry_date: str = ""
    status: str = "ACTIVE"
    status_snippet: str = ""
    listed_annexes: dict[str, str] | None = None   # annex no -> date; None = list not found
    snippet: str = ""


@dataclass
class Annex:
    source: str
    folder: Folder
    number: str = ""
    annex_no: str = ""
    annex_date: str = ""
    legal_name: str = ""
    trade_name: str = ""
    address: str = ""
    cert_stds: list[str] = field(default_factory=list)
    suppl_stds: list[str] = field(default_factory=list)
    ea: list[int] = field(default_factory=list)
    note: str = ""
    status: str = "ACTIVE"
    status_snippet: str = ""


def org_block(text: str, folded: str, anchor: re.Pattern) -> tuple[str, str, str] | None:
    """-> (legal name, address, trade name after 'prin') or None if the anchor is missing."""
    m = anchor.search(folded)
    if not m:
        return None
    name: list[str] = []
    addr: list[str] = []
    trade: list[str] = []
    state, n = "name", 0
    after_trade = addr  # where lines after the trade name go: the address, unless it came first
    for o, f in zip(text[m.end():].splitlines(), folded[m.end():].splitlines()):
        o, f = o.strip(), f.strip()
        if not o:
            continue
        if RX_ORG_END.match(f) or n >= ORG_MAX_LINES:
            break
        n += 1
        if (pm := RX_PRIN.match(f)):
            rest = o[pm.start(1):].strip()
            trade += [rest] if rest else []
            after_trade = trade if addr else addr
            state = "after_trade" if rest else "trade"
        elif state == "trade":
            trade.append(o)
            state = "after_trade"
        elif state == "after_trade":
            after_trade.append(o)
        elif state == "name" and (not name or not any(ch.islower() for ch in o)):
            name.append(o)
        else:
            state = "address"
            addr.append(o)
    return " ".join(name), " ".join(addr), " ".join(trade)


def resolve_number(pdf_no: str, folder: Folder, src: str, review: Review, snippet: str) -> str:
    """Certificate number from the PDF, cross-checked with (or falling back to) the folder name."""
    if not folder.number:
        review.add(pdf_no, src, "folder", "folder name has no certificate number (truncated?) - "
                   "cannot cross-check", folder.company_dir)
    if not pdf_no:
        if folder.number:
            review.add(folder.number, src, "certificate_number",
                       "not found in PDF - taken from the folder name", snippet)
        return folder.number
    if folder.number and no_key(folder.number) != no_key(pdf_no):
        review.add(pdf_no, src, "certificate_number",
                   f"PDF says {pdf_no} but the folder name says {folder.number} - PDF value used",
                   folder.company_dir)
    return pdf_no


def parse_cert(text: str, folded: str, src: str, folder: Folder, review: Review) -> Cert:
    c = Cert(src, folder, snippet=text[:300])
    m = RX_CERT_TITLE.search(folded)
    c.number = resolve_number(format_no(*m.groups()) if m else "", folder, src, review, text[:300])
    log = lambda fld, problem, snip="": review.add(c.number, src, fld, problem, snip)  # noqa: E731

    org = org_block(text, folded, RX_CERT_ORG_ANCHOR)
    if org:
        c.legal_name, c.address, c.trade_name = org
    else:
        log("name", "'atestă că organizaţia' block not found", text[:300])
    for label in ("initial_date", "renewal_date", "updated_date", "expiry_date"):
        setattr(c, label, find_date(folded, label, log))
    c.status, c.status_snippet = find_status(text, folded)

    m = RX_ANNEX_LIST.search(folded)
    if m:
        c.listed_annexes = {str(int(i.group(1))): make_date(*i.groups()[1:])
                            for i in RX_ANNEX_LIST_ITEM.finditer(m.group(1))}
    return c


def ea_tokens(cell: str, log) -> set[int]:
    out: set[int] = set()
    if RX_SPACED_DIGITS.search(cell):
        joined = RX_SPACED_DIGITS.sub(r"\1\2", cell)
        log("ea_codes", "letter-spaced IAF cells (e.g. '3 0') read as two-digit codes (30) - verify",
            f"{collapse(cell)} -> {collapse(joined)}")
        cell = joined
    tokens = RX_EA_TOKEN.findall(cell)
    if not tokens:
        log("ea_codes", "IAF/EA cell without a code", cell)
    for a, b in tokens:
        lo, hi = int(a), int(b or a)
        for n in (range(lo, hi + 1) if lo <= hi else (lo, hi)):
            if 1 <= n <= 39:
                out.add(n)
            else:
                log("ea_codes", f"code {n} outside 1-39 - dropped", cell)
    return out


def ea_from_tables(page_tables: list[list], log) -> tuple[bool, set[int], list[str]]:
    """-> (IAF/EA column found, codes, headers of tables without one)"""
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
                    codes |= ea_tokens(cell, log)
    return col is not None, codes, other


def ea_from_text(folded: str, log) -> set[int]:
    codes: set[int] = set()
    last_row = 0
    lines = folded.splitlines()
    for i, line in enumerate(lines):
        nr = code = None
        if (m := RX_TEXT_ROW.match(line)):
            nr, code = int(m.group(1)), m.group(2)
        elif (m := RX_TEXT_NR_ONLY.match(line)) and i + 1 < len(lines):
            if (n := RX_TEXT_LEAD_CODE.match(lines[i + 1])):
                nr, code = int(m.group(1)), n.group(1)
        if nr is not None and nr > last_row:  # row numbers only go up: skips stray matches
            last_row = nr
            codes |= ea_tokens(code, log)
    return codes


def parse_annex(text: str, folded: str, page_tables: list[list], src: str, folder: Folder,
                review: Review) -> Annex:
    a = Annex(src, folder)
    m = RX_ANNEX_HEADER.search(folded)
    a.number = resolve_number(format_no(m.group(2), m.group(3)), folder, src, review, text[:300])
    log = lambda fld, problem, snip="": review.add(a.number, src, fld, problem, snip)  # noqa: E731
    a.annex_no = str(int(m.group(1))) if m.group(1) else ""
    if not a.annex_no:
        log("annex_number", "annex header has no 'nr.' - left empty", m.group(0))
    a.annex_date = find_date(folded, "annex_date", log)
    if not a.annex_date:
        log("annex_date", "not found - left empty", text[:300])

    org = org_block(text, folded, RX_ANNEX_ORG_ANCHOR)
    if org:
        a.legal_name, a.address, a.trade_name = org
    a.status, a.status_snippet = find_status(text, folded)

    # certification standard: "Standard de referinţă ..." line
    m = RX_CERT_STD_LINE.search(folded)
    found = standards_in(m.group(1)) if m else []
    if not found:
        known_certs = {c for _, cs, _ in SCHEMES for c in cs}
        found = [(s, raw) for s, raw in standards_in(folded) if s in known_certs]
        log("certification_standard",
            "no 'Standard de referinţă pentru activitatea de certificare' line - "
            + (f"taken from the annex body: {', '.join(s for s, _ in found)}" if found else "not found"),
            text[:400])
    if len(found) > 1:
        log("certification_standard", f"annex names several certification standards: "
            f"{', '.join(s for s, _ in found)} - one scope row each", m.group(0) if m else "")
    a.cert_stds = [s for s, _ in found]

    # supplementary standard: "... cerinţele suplimentare conţinute în: ..."
    m = RX_SUPPL_CLAUSE.search(folded)
    suppl = standards_in(m.group(1)) if m else []
    a.suppl_stds = [s for s, _ in suppl]
    if m and not suppl:
        log("supplementary_standard", "supplementary clause names no ISO standard", m.group(0))
    for s, raw in found + suppl:
        if "IEC" in s and not re.search(r"IEC|CEI", raw, I):
            log("standard", f"'{collapse(raw)}' written without IEC - normalised to {s}", raw)

    if folder.expected_std and a.cert_stds and folder.expected_std not in a.cert_stds:
        log("certification_standard",
            f"annex covers {', '.join(a.cert_stds)} but its category folder '{folder.category}' "
            f"expects {folder.expected_std} - PDF value used", folder.company_dir)

    # IAF / EA codes
    has_col, codes, other_headers = ea_from_tables(page_tables, log)
    if not codes and not has_col and not other_headers and RX_HAS_EA_COLUMN.search(text):
        codes = ea_from_text(folded, log)
        if codes:
            log("ea_codes", "no IAF table detected - codes parsed from plain text, verify",
                ",".join(map(str, sorted(codes))))
    if codes:
        a.ea = sorted(codes)
    else:
        a.ea = list(ALL_EA)
        if (m := RX_ALL_CODES.search(folded)):
            a.note = "annex states all IAF/EA codes"
            snip = text[max(0, m.start() - 100):m.end() + 150]
        elif has_col:
            a.note, snip = "IAF column in annex table is empty", ""
        elif other_headers:
            a.note, snip = f"no IAF/EA column in annex table ({other_headers[0]})", ""
        else:
            a.note, snip = "no sector table in annex", ""
        log("ea_codes", f"{a.note} - EA codes set to 1-39", snip)
    return a


def process_pdf(path: Path, rel: str, pages: list[Page], review: Review) -> tuple[list[Cert], list[Annex]]:
    folder = folder_info(rel)
    certs: list[Cert] = []
    annexes: list[Annex] = []
    if not pages:
        review.add(folder.number, rel, "file", "PDF has no pages")
    for kind, doc_pages in split_documents(pages):
        text = "\n".join(p.text for p in doc_pages)
        if kind == "cert":
            if not RX_CERT_TITLE.search(fold(text)):
                review.add(folder.number, rel, "file", "pages are neither a certificate nor an annex - "
                           "ignored", text[:300])
                continue
            certs.append(parse_cert(text, fold(text), rel, folder, review))
        else:
            annexes.append(parse_annex(text, fold(text), [p.tables for p in doc_pages], rel, folder, review))
    return certs, annexes


# --------------------------------------------------------------------------- merging
CERT_FIELDS = ("legal_name", "trade_name", "address", "initial_date", "renewal_date", "updated_date",
               "expiry_date", "status", "listed_annexes")
ANNEX_FIELDS = ("annex_date", "legal_name", "trade_name", "address", "cert_stds", "suppl_stds", "ea", "status")


def pick_certificate(no: str, copies: list[Cert], review: Review) -> Cert | None:
    """Keep the copy with the latest 'Data actualizării' and log fields the copies disagree on."""
    if not copies:
        return None
    kept = max(copies, key=lambda c: c.updated_date)  # stable: the first of equal copies wins
    for other in copies:
        for f in CERT_FIELDS:
            if getattr(other, f) != getattr(kept, f):
                review.add(no, other.source, f, f"certificate copies disagree: '{getattr(other, f)}' here vs "
                           f"'{getattr(kept, f)}' in {kept.source} - kept the latter (latest Data actualizării)")
    return kept


def dedupe_annexes(no: str, annexes: list[Annex], review: Review) -> list[Annex]:
    kept: dict[str, Annex] = {}
    for a in annexes:
        key = a.annex_no or f"?{a.source}"
        if key not in kept:
            kept[key] = a
            continue
        first = kept[key]
        diff = [f for f in ANNEX_FIELDS if getattr(a, f) != getattr(first, f)]
        if diff and a.annex_date > first.annex_date:
            kept[key], a, first = a, first, a
        review.add(no, a.source, "annex", f"duplicate of annex nr. {a.annex_no} in {first.source} - "
                   + (f"copies differ in {', '.join(diff)}; kept the one with the latest annex date"
                      if diff else "identical, one copy kept"))
    return sorted(kept.values(), key=lambda a: (int(a.annex_no) if a.annex_no else 999, a.source))


def check_annex_list(no: str, cert: Cert, annexes: list[Annex], review: Review) -> None:
    if cert.listed_annexes is None:
        review.add(no, cert.source, "annex", "list of annexes ('însoţit de Anexele ...') not found on "
                   "the certificate - completeness not checked", cert.snippet)
        return
    listed = cert.listed_annexes
    found = {a.annex_no: a for a in annexes if a.annex_no}
    for n, d in listed.items():
        if n not in found:
            review.add(no, cert.source, "annex", f"annex nr. {n} ({d}) is listed on the certificate but "
                       "was not found in the input")
        elif d and found[n].annex_date and d != found[n].annex_date:
            review.add(no, found[n].source, "annex_date", f"annex nr. {n} is dated {found[n].annex_date} but "
                       f"the certificate lists it as {d}")
    for n, a in found.items():
        if n not in listed:
            review.add(no, a.source, "annex", f"annex nr. {n} was found but is not listed on the certificate")
    if listed:
        gaps = sorted(set(range(1, max(map(int, listed)) + 1)) - set(map(int, listed)))
        if gaps:
            review.add(no, cert.source, "annex", "gaps in annex numbering (normal): nr. "
                       f"{', '.join(map(str, gaps))} not listed on the certificate")


def compare_org(no: str, cert: Cert, a: Annex, review: Review) -> None:
    for f, label in (("legal_name", "name"), ("trade_name", "trade name"), ("address", "address")):
        ca, aa = getattr(cert, f), getattr(a, f)
        if f == "trade_name" and same_text(aa, a.legal_name):
            aa = ""  # "CERTIND SA prin CERTIND SA": no separate trade name
        if aa and not same_text(ca, aa):
            review.add(no, a.source, f, f"info: annex {label} differs from the certificate "
                       f"('{aa}' vs '{ca}') - certificate value used")
        elif not aa and ca and f != "trade_name":
            review.add(no, a.source, f, f"info: annex {label} not found - not compared")


def classify(no: str, a: Annex, std: str, review: Review) -> str | None:
    """Accreditation standard (scheme) of one annex certification standard, or None."""
    rows = [r for r in SCHEMES if std in r[1]]
    if not rows:
        review.add(no, a.source, "certification_standard",
                   f"{std} is not in the scheme table - not exported")
        return None
    if a.suppl_stds:
        for sup, _, acc in rows:
            if sup in a.suppl_stds:
                return acc
        review.add(no, a.source, "accreditation_standard",
                   f"supplementary {', '.join(a.suppl_stds)} with certification standard {std} is not a "
                   "combination in the scheme table - not exported")
        return None
    sup, _, acc = rows[0]
    if sup is not None:
        review.add(no, a.source, "accreditation_standard",
                   f"no supplementary standard in annex - scheme {acc} derived from certification standard {std}")
    return acc


def scheme_number(no: str, acc: str) -> str:
    return no if acc == ACC_17021_1 else f"{no} ({CERT_SUFFIX[acc]})"


def build(certs: list[Cert], annexes: list[Annex], review: Review):
    groups: dict[str, tuple[list[Cert], list[Annex]]] = {}
    for c in certs:
        groups.setdefault(c.number, ([], []))[0].append(c)
    for a in annexes:
        groups.setdefault(a.number, ([], []))[1].append(a)

    bodies: dict[str, dict] = {}
    accs: list[dict] = []
    scopes: list[dict] = []
    stats = {"certificates": 0, "annexes": 0}
    for no in sorted(groups, key=no_key):
        g_certs, g_annexes = groups[no]
        if not no:
            for x in g_certs + g_annexes:
                review.add("", x.source, "certificate_number", "not found in PDF or folder name - not exported")
            continue
        cert = pick_certificate(no, g_certs, review)
        found_annexes = dedupe_annexes(no, g_annexes, review)
        stats["annexes"] += len(found_annexes)
        if not cert:
            for a in found_annexes:
                review.add(no, a.source, "certificate", "annex found but its certificate was not found in "
                           "the input - not exported")
            continue
        stats["certificates"] += 1
        check_annex_list(no, cert, found_annexes, review)
        if not found_annexes:
            review.add(no, cert.source, "annex", "certificate found but none of its annexes - only "
                       f"{ACC_17021_1} exported, without scope")
        if not cert.legal_name:
            review.add(no, cert.source, "name", "company name not found on certificate - not exported",
                       cert.snippet)
            continue
        name = cert.legal_name
        if cert.trade_name and not same_text(cert.trade_name, cert.legal_name):
            name += f" ({cert.trade_name})"
        if not cert.address:
            review.add(no, cert.source, "address", "not found on certificate - left empty", cert.snippet)

        issue = cert.renewal_date or cert.initial_date
        if not cert.renewal_date and cert.initial_date:
            review.add(no, cert.source, "issue_date", "no 'Data reînnoirii acreditării' - issue_date = initial "
                       "date", cert.initial_date)
        for f, value in (("issue_date", issue), ("expiry_date", cert.expiry_date),
                         ("updated_date", cert.updated_date)):
            if not value:
                review.add(no, cert.source, f, "not found on certificate - left empty", cert.snippet)
        if issue and cert.expiry_date and cert.expiry_date < issue:
            review.add(no, cert.source, "expiry_date", f"expiry {cert.expiry_date} is before issue {issue}")
        if cert.status_snippet:
            review.add(no, cert.source, "status", f"set to {cert.status} from the certificate wording",
                       cert.status_snippet)

        # schemes: ISO/IEC 17021-1 always (the certificate grants it), plus one per annex scheme
        schemes = {ACC_17021_1: {"status": cert.status, "sources": [cert.source]}}
        for a in found_annexes:
            compare_org(no, cert, a, review)
            for std in a.cert_stds:
                acc = classify(no, a, std, review)
                if not acc:
                    continue
                s = schemes.setdefault(acc, {"status": cert.status, "sources": [cert.source]})
                s["sources"].append(a.source)
                if STATUS_RANK[a.status] > STATUS_RANK[s["status"]]:
                    s["status"] = a.status
                    review.add(no, a.source, "status", f"{acc} set to {a.status} from the annex wording",
                               a.status_snippet)
                scopes.append({
                    "certificate_number": scheme_number(no, acc), "certification_standard": std,
                    "ea_codes": ",".join(map(str, a.ea)), "annex_number": a.annex_no,
                    "annex_date": a.annex_date, "note": a.note, "source_pdf": a.source, "_base": no,
                })
        for acc in sorted(schemes, key=ACC_ORDER.index):
            accs.append({
                "company_name": name, "accreditation_standard": acc,
                "certificate_number": scheme_number(no, acc), "status": schemes[acc]["status"],
                "issue_date": issue, "expiry_date": cert.expiry_date, "initial_date": cert.initial_date,
                "updated_date": cert.updated_date, "proof_url": PROOF_URL,
                "source_pdf": "; ".join(dict.fromkeys(schemes[acc]["sources"])), "_base": no,
            })

        if name in bodies:  # one company holding several certificates (e.g. SM 041 + SMFS 001)
            body = bodies[name]
            body["_base"] += f", {no}"
            review.add(no, cert.source, "name", f"same company also holds {body['_base'].split(', ')[0]} - "
                       "one certification_bodies row")
            if not same_text(body["address"], cert.address):
                review.add(no, cert.source, "address", f"info: differs between this company's certificates "
                           f"('{cert.address}' vs '{body['address']}') - first kept")
            continue
        bodies[name] = {"name": name, "legal_name": cert.legal_name, "trade_name": cert.trade_name,
                        "country": COUNTRY, "phone": "", "email": "", "website": "",
                        "address": cert.address, "_base": no}
        review.add(no, cert.source, "phone/email/website", "not in the RENAR PDFs - left empty")
    return list(bodies.values()), accs, scopes, stats


# --------------------------------------------------------------------------- output
def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sql_str(v) -> str:
    return "NULL" if v in (None, "") else "'" + str(v).replace("'", "''") + "'"


def sql_ea_array(codes: str) -> str:
    if codes == ",".join(map(str, ALL_EA)):
        return "ARRAY(SELECT generate_series(1, 39))"
    return f"ARRAY[{codes.replace(',', ', ')}]"


def values_lines(rows: list[dict], fmt, indent: str) -> list[str]:
    """VALUES rows with '-- source: <certificate_number>' above each company's rows."""
    lines, prev = [], None
    for i, r in enumerate(rows):
        if r["_base"] != prev:
            prev = r["_base"]
            lines.append(f"{indent}-- source: {prev}")
        lines.append(indent + fmt(r) + ("," if i < len(rows) - 1 else ""))
    return lines


def write_sql(path: Path, bodies: list[dict], accs: list[dict], scopes: list[dict]) -> None:
    out = ["-- Generated by extract_renar_v2.py from RENAR certificate/annex PDFs.",
           "-- Requires the accreditation_bodies row with code 'RENAR'.", ""]
    if bodies:
        out.append("INSERT INTO certification_bodies (name, country, phone, email, website, address) VALUES")
        out += values_lines(bodies, lambda b: "(" + ", ".join(sql_str(b[k]) for k in (
            "name", "country", "phone", "email", "website", "address")) + ")", "")
        out[-1] += ";"
        out.append("")
    for status in dict.fromkeys(a["status"] for a in accs):
        rows = [a for a in accs if a["status"] == status]
        out += ["INSERT INTO accreditations",
                "    (certification_body_id, accreditation_body_id, accreditation_standard, certificate_number,",
                "     status, issue_date, expiry_date, proof_url)",
                f"SELECT cb.id, ab.id, v.std, v.cert, {sql_str(status)}, v.issued::date, v.expires::date, "
                f"{sql_str(PROOF_URL)}",
                "FROM (VALUES"]
        out += values_lines(rows, lambda a: "(" + ", ".join(sql_str(a[k]) for k in (
            "company_name", "accreditation_standard", "certificate_number", "issue_date", "expiry_date")) + ")",
            "    ")
        out += [") AS v(cb_name, std, cert, issued, expires)",
                "JOIN certification_bodies cb ON cb.name = v.cb_name",
                "JOIN accreditation_bodies ab ON ab.code = 'RENAR';", ""]
    if scopes:
        out += ["INSERT INTO accredited_scopes (accreditation_id, accreditation_standard, certification_standard, ea_code)",
                "SELECT a.id, a.accreditation_standard, v.std, ea",
                "FROM (VALUES"]
        out += values_lines(scopes, lambda s: f"({sql_str(s['certificate_number'])}, "
                            f"{sql_str(s['certification_standard'])}, {sql_ea_array(s['ea_codes'])})", "    ")
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
    p.add_argument("pdf_folder", nargs="?", default="output/pdfs", help="PDF folder (default: output/pdfs)")
    p.add_argument("--out", default="output/db", help="Output folder (default: output/db)")
    p.add_argument("--debug", action="store_true", help="Also save each PDF's raw text and tables as .txt")
    p.add_argument("--tesseract", default=default_tess, help="tesseract.exe path (env TESSERACT_CMD)")
    p.add_argument("--poppler", default=os.environ.get("POPPLER_PATH", ""),
                   help="Poppler bin folder (env POPPLER_PATH)")
    return p.parse_args(argv)


def check_folders(docs_per_folder: dict[str, list[int]], review: Review) -> None:
    for folder, (n_cert, n_annex) in docs_per_folder.items():
        no = folder_info(folder + "/x.pdf").number
        if n_cert != 1:
            review.add(no, folder, "file", f"folder has {n_cert} certificates (expected 1)")
        if n_annex != 1:
            review.add(no, folder, "file", f"folder has {n_annex} annexes (expected 1)")


def main(argv=None) -> int:
    args = parse_args(argv)
    in_dir, out_dir = Path(args.pdf_folder).resolve(), Path(args.out).resolve()
    if not in_dir.is_dir():
        print(f"Not a folder: {in_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = out_dir / "debug" if args.debug else None

    review = Review()
    certs: list[Cert] = []
    annexes: list[Annex] = []
    page_cache: dict[str, list[Page]] = {}     # identical copies are read once
    docs_per_folder: dict[str, list[int]] = {}
    categories: set[str] = set()
    pdfs = sorted(in_dir.rglob("*.pdf"), key=lambda p: str(p).lower())
    failed = 0
    for i, path in enumerate(pdfs, 1):
        rel = path.relative_to(in_dir).as_posix()
        folder = folder_info(rel)
        print(f"[{i}/{len(pdfs)}] {rel}")
        counts = docs_per_folder.setdefault(folder.company_dir, [0, 0])
        if folder.category and not folder.expected_std and folder.category not in categories:
            review.add("", folder.category, "category", "category folder not in the known list - "
                       "processed anyway, no expected standard to cross-check")
        categories.add(folder.category)
        try:
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            if digest not in page_cache:
                page_cache[digest] = read_pages(path, rel, folder.number, args, review)
            pages = page_cache[digest]
            if debug_dir:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / (rel.replace("/", "__")[:-4] + ".txt")).write_text(debug_dump(pages), encoding="utf-8")
            c, a = process_pdf(path, rel, pages, review)
            certs += c
            annexes += a
            counts[0] += len(c)
            counts[1] += len(a)
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
            failed += 1
            review.add(folder.number, rel, "file", f"could not process: {type(e).__name__}: {e}")

    check_folders(docs_per_folder, review)
    bodies, accs, scopes, stats = build(certs, annexes, review)

    write_csv(out_dir / "certification_bodies.csv",
              ["name", "legal_name", "trade_name", "country", "phone", "email", "website", "address"], bodies)
    write_csv(out_dir / "accreditations.csv",
              ["company_name", "accreditation_standard", "certificate_number", "status", "issue_date",
               "expiry_date", "initial_date", "updated_date", "proof_url", "source_pdf"], accs)
    write_csv(out_dir / "accredited_scopes.csv",
              ["certificate_number", "certification_standard", "ea_codes", "annex_number", "annex_date",
               "note", "source_pdf"], scopes)
    write_csv(out_dir / "review.csv", Review.FIELDS, review.rows)
    write_sql(out_dir / "seed_romania.sql", bodies, accs, scopes)

    print()
    print(f"PDFs read      : {len(pdfs)} ({failed} failed)")
    print(f"Certificates   : {stats['certificates']}")
    print(f"Annexes        : {stats['annexes']}")
    print(f"Companies      : {len(bodies)}")
    print(f"Accreditations : {len(accs)}")
    print(f"Scope rows     : {len(scopes)}")
    print(f"Review items   : {len(review.rows)}")
    print(f"Output         : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
