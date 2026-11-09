#!/usr/bin/env python3
"""Extract CAB metadata and accredited ISO scopes from DPA certificate PDFs.

Each certificate is a short certificate page followed by annex pages
("Programi i AKREDITIMIT / Aneks i Çertifikatës"). The annex is parsed as one
continuous line stream, so a scope that starts on one page and continues on the
next is handled, and footers/headers that repeat on every page are ignored.

Outputs (written to --output-dir, default: current directory):
    accreditation_data.json   one object per certificate, with nested scopes
    accreditations_flat.csv   one row per company + standard + EA code

Install:
    pip install pdfplumber
    pip install pypdf          (optional: used only if pdfplumber is not installed)

Usage:
    python parse_accreditation_pdfs.py
    python parse_accreditation_pdfs.py --input-dir certificates --no-recursive -v
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


LOG = logging.getLogger("parse_accreditation_pdfs")

ACCREDITATION_BODY = "DPA (Drejtoria e Përgjithshme e Akreditimit)"
ALL_IAF_CODES = [f"{number:02d}" for number in range(1, 40)]
JSON_NAME = "accreditation_data.json"
CSV_NAME = "accreditations_flat.csv"
CSV_COLUMNS = ["company_name", "accreditation_number", "standard", "ea_code", "valid_until", "file_name"]

# --- text cleaning ---------------------------------------------------------

INVISIBLE_RE = re.compile("[­​‌‍⁠﻿]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
QUOTES_RE = re.compile("[\"'“”„‟«»]")

# Repeated page header/footer/signature lines, and the CAB's own accreditation standards
# (ISO/IEC 17021, 27006, 50003, 22003) that appear in annex headers. Dropped before scope parsing.
BOILERPLATE_RE = re.compile(
    r"^(?:REPUBLIKA\s+E\s+SHQIP|MINISTRIA\s+E\s+EKONOMI|(?:KULTURËS\s+)?DHE\s+INOVACIONIT|INOVACIONIT\s*$"
    r"|Programi\s+i\s+AKREDI|Aneks\s+i\s+Çertifikat|Organizëm\s+që\s+Operon"
    r"|(?:S\s?SH\s+)?ISO\s*/?\s*(?:IEC\s*)?(?:17021|27006|50003|22003)"
    r"|\d{4,5}-\d+"
    r"|DREJTOR\s+I\s+P[ËE]RGJITHSH|PRANVERA\s+FAGU|Rishikimi\b(?=.*\d)|Lëshuar\s+më"
    r"|E\s+vlefshme\s+deri|Fusha\s+e\s+Akredi)",
    re.IGNORECASE,
)


def clean_text(raw: str) -> str:
    """Normalise extracted PDF text: compose diacritics, drop invisible and control characters."""
    text = unicodedata.normalize("NFKC", raw)
    text = INVISIBLE_RE.sub("", text)
    text = CONTROL_RE.sub(" ", text)
    text = text.replace("�", "").replace(" ", " ")
    return text


def clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,;")


def unique(items) -> list:
    return list(dict.fromkeys(items))


# --- extraction ------------------------------------------------------------

@dataclass(frozen=True)
class Line:
    page: int
    text: str


@dataclass
class Scope:
    lines: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    has_put_me: bool = False  # a "… në përputhje me:" heading has been seen in this block


def _safe_extract(extract, number: int, warnings: list[str]) -> str:
    """Call an extractor for one page. A broken page is recorded, not fatal."""
    try:
        return extract() or ""
    except Exception as exc:  # broken content stream on this page only
        warnings.append(f"page {number}: text extraction failed ({exc})")
        return ""


def extract_page_texts(pdf_path: Path, warnings: list[str]) -> list[str]:
    if pdfplumber is None and PdfReader is None:
        raise RuntimeError("no PDF library installed; run: pip install pdfplumber")
    if pdfplumber is not None:
        with pdfplumber.open(pdf_path) as pdf:
            raw_pages = [
                _safe_extract(page.extract_text, number, warnings)
                for number, page in enumerate(pdf.pages, start=1)
            ]
    else:
        reader = PdfReader(str(pdf_path))
        raw_pages = [
            _safe_extract(page.extract_text, number, warnings)
            for number, page in enumerate(reader.pages, start=1)
        ]
    return [clean_text(text) for text in raw_pages]


ANNEX_TITLE_RE = re.compile(r"^Aneks\s+i\s+Çertifikat", re.IGNORECASE)


def to_lines(page_texts: list[str]) -> list[Line]:
    lines = []
    drop_company_line = False  # the annex title is followed by the CAB name on its own line
    for number, text in enumerate(page_texts, start=1):
        for raw in text.splitlines():
            line = clean_spaces(raw)
            if not line:
                continue
            if drop_company_line and not ADDRESS_STOP_RE.match(line):
                drop_company_line = False
                continue
            drop_company_line = False
            if BOILERPLATE_RE.match(line):
                drop_company_line = bool(ANNEX_TITLE_RE.match(line))
                continue
            lines.append(Line(number, line))
    return lines


# --- certificate metadata --------------------------------------------------

NAME_STOP_RE = re.compile(r"^(Numri|Adresa\s*:|Është|Kjo|Çertifikata|Certifikata|Data\b)", re.IGNORECASE)
SUFFIX_GLUE_RE = re.compile(r"(?<=[A-Za-z])(?=sh\.\s?p\.\s?k|shpk)", re.IGNORECASE)
SUFFIX_NORMALISE_RE = re.compile(r"\b(sh)\.\s*p\.\s*k\.?", re.IGNORECASE)
LEGAL_SUFFIX_RE = re.compile(r"\bsh\.?\s?p\.?\s?k\b|\bshpk\b|\bsh\.?\s?a\b", re.IGNORECASE)
ACC_NUMBER_RE = re.compile(r"Numri\s+i\s+Akreditimit\s*:?\s*CS\s*[-_]?\s*(\d{1,4})", re.IGNORECASE)
FILENAME_ACC_RE = re.compile(r"CS[\s_-]*(\d{1,4})", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")
VALID_FROM_RE = re.compile(r"akredit[\w\s]*?t[ëe]\s+fundit", re.IGNORECASE)
VALID_UNTIL_RE = re.compile(r"vlefsh\w*\s+deri|deri\s+(?:më|në)\s+dat", re.IGNORECASE)
# Anchored to the start of a line: the footer "kontaktoni me DPA tel: …" is not the CAB's own phone.
PHONE_LINE_RE = re.compile(r"^(?:Tel|Cel)\w*[^:]{0,25}:[ \t]*(\+?\s*\d[\d\s-]{5,})", re.IGNORECASE)
ADDRESS_INLINE_STOP_RE = re.compile(r"\s+(?:Tel|Cel|Person|E-?mail)\w*[^:]{0,25}:.*$", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CONTACT_PERSON_RE = re.compile(r"\bPerson(?:i|a)?\s+kontakt\w*\s*:\s*(.+)", re.IGNORECASE)
ADDRESS_LABEL_RE = re.compile(r"^Adresa\s*:\s*(.*)$", re.IGNORECASE)
ADDRESS_STOP_RE = re.compile(
    r"^(Tel|Telefon|Person|E-?mail|Numri|Fusha|Akredit|Është|Kjo|Çertifikata|Certifikata|Data|Rishikimi|Lëshuar|Adresa)",
    re.IGNORECASE,
)


def is_certificate_heading(text: str) -> bool:
    # Some PDFs letter-space the heading ("Ç E R TI FI K A T Ë"), so compare with all spaces removed.
    return re.sub(r"\s+", "", text).upper() == "ÇERTIFIKATËAKREDITIMI"


def parse_company_name(lines: list[Line]) -> str | None:
    """Accredited CAB name: the lines after the 'ÇERTIFIKATË AKREDITIMI' heading, up to the legal suffix."""
    page_one = [line.text for line in lines if line.page == 1]
    start = next((i + 1 for i, text in enumerate(page_one) if is_certificate_heading(text)), 0)

    chosen: list[str] = []
    for raw in page_one[start:]:
        text = QUOTES_RE.sub("", raw)  # quotes can sit between the name and "sh.p.k"; drop them first
        if NAME_STOP_RE.match(text):
            break
        chosen.append(text)
        if LEGAL_SUFFIX_RE.search(SUFFIX_GLUE_RE.sub(" ", text)):
            break
    if not any(LEGAL_SUFFIX_RE.search(SUFFIX_GLUE_RE.sub(" ", text)) for text in chosen):
        chosen = chosen[:1]  # no suffix seen: the first line is the name, the rest is address

    name = " ".join(SUFFIX_GLUE_RE.sub(" ", text) for text in chosen)
    name = SUFFIX_NORMALISE_RE.sub(r"\1.p.k", clean_spaces(name)).strip(" .-")
    return name or None


def parse_accreditation_number(lines: list[Line], file_name: str) -> str | None:
    page_one = "\n".join(line.text for line in lines if line.page == 1)
    match = ACC_NUMBER_RE.search(page_one) or FILENAME_ACC_RE.search(file_name)
    return f"CS {int(match.group(1)):03d}" if match else None


def find_date(lines: list[Line], label_re: re.Pattern) -> str | None:
    """Return the first dd.mm.yyyy date on a line matching the label, in document order."""
    for line in lines:
        if label_re.search(line.text):
            match = DATE_RE.search(line.text)
            if match:
                day, month, year = match.groups()
                return f"{int(day):02d}.{int(month):02d}.{year}"
    return None


def parse_address(texts: list[str]) -> str | None:
    for index, text in enumerate(texts):
        match = ADDRESS_LABEL_RE.match(text)
        if not match:
            continue
        parts = [match.group(1)]
        for follow in texts[index + 1:index + 4]:  # addresses wrap over up to 3 more lines
            if ADDRESS_STOP_RE.match(follow) or ADDRESS_LABEL_RE.match(follow):
                break
            parts.append(follow)
        address = ADDRESS_INLINE_STOP_RE.sub("", " ".join(part for part in parts if part))
        return clean_spaces(address) or None
    return None


def parse_phone(texts: list[str]) -> str | None:
    for text in texts:
        match = PHONE_LINE_RE.match(text)
        if match:
            return re.sub(r"\s+", "", match.group(1)).rstrip("-/")
    return None


def parse_contact(lines: list[Line]) -> dict:
    full = "\n".join(line.text for line in lines)
    email = EMAIL_RE.search(full)
    person = CONTACT_PERSON_RE.search(full)
    texts = [line.text for line in lines]
    return {
        "address": parse_address(texts),
        "phone": parse_phone(texts),
        "email": email.group(0).lower() if email else None,
        "contact_person": clean_spaces(person.group(1)) if person else None,
    }


# --- scope parsing ---------------------------------------------------------

ACCREDITATION_START_RE = re.compile(r"\bAkreditohet\b", re.IGNORECASE)
PUT_ME_RE = re.compile(r"p[ëe]rputhje\s+me\s*:?", re.IGNORECASE)
# Words that end the standard name: the code/category list or the page footer starts here.
SCOPE_STOP_RE = re.compile(
    r"\bpër\s+(?:kodet|kategori|të\s+gjitha|te\s+gjitha)"
    r"|\b(?:Kodet|Kategoria|Fushat|Rishikimi|Lëshuar|DREJTOR|vlefshme|Programi|Aneks|REPUBLIKA)\b"
    r"|\b17021\b|\bEA\s*\d",
    re.IGNORECASE,
)
STANDARD_RE = re.compile(
    r"\bISO(?:\s*/\s*IEC)?\s*\d{2,6}(?:-\d+)*(?:\s*:\s*\d{4})?(?:\s*/\s*Amd\s*\d+\s*:\s*\d{4})?",
    re.IGNORECASE,
)
FAMILY_RE = re.compile(r"^(ISO(?:/IEC)?\s\d+(?:-\d+)?)")
EA_CODE_RE = re.compile(r"\bEA\s*0?(\d{1,2})\b")
# Table rows where the code is the second number: "0 1 Bujqësi", "0 12 Kimikate", "01 17 Metalet…".
TABLE_CODE_RE = re.compile(r"^0\d?\s+(\d{1,2})\s+[^\d\s]")
ALL_IAF_RE = re.compile(r"\bgjitha\s+kodet\b", re.IGNORECASE)  # "Për të gjitha kodet IAF" / "… të gjitha kodet e EA/IAF"
CATEGORY_HINT_RE = re.compile(r"kategori", re.IGNORECASE)
PER_KATEGORI_RE = re.compile(r"për\s+kategori", re.IGNORECASE)
# Category bullets: "A. Industria…", "A - Industri…", "A (industri…)", "- Ndërtesa", "1 Industria…",
# and "0 Industri…" where the PDF draws the bullet as a "0".
CATEGORY_RE = re.compile(r"^(?:[A-Z]\s*(?:\.|-|–|\)|\()\s*|[-–•]\s+|0\s+(?!\d)|\d{1,2}\s+(?=[A-ZÇË]))(.+?)[\s.;,)]*$")
LETTER_PREFIX_RE = re.compile(r"^[A-Z]\s*[.)\-–(]\s*")  # a lettered label left inside the name, e.g. "0 A. Industri…"
LETTERS_RE = re.compile(r"[^\W\d_]{3,}")  # a real name has at least one run of three letters
SIGNATURE_TAIL_RE = re.compile(r"\s+(?:DREJTOR|PRANVERA|Rishikimi\s+\d|E\s+vlefshme|Lëshuar)\b.*$")  # uppercase signature/footer
COLUMN_HEADER_RE = re.compile(
    r"^(?:[A-Z]\.?\s+)?(?:Rishikimi\s+)?P[ëe]?rshkrimi\s+i\s+(?:sektorit|aktivitetit)|^Kodet\b", re.IGNORECASE
)
CONNECTIVE_END_RE = re.compile(r"\b(?:së|e|të|dhe|me|për|në|nga|i)\s*$", re.IGNORECASE)  # the item is cut mid-phrase
# Lines that end an unbulleted category list: the next annex's contact block, a new heading, or a table.
CATEGORY_STOP_RE = re.compile(
    r"^(?:Adresa|Tel|Cel|Telefon|Person|E-?mail|Numri|Fusha|Akredit|Kjo|Është|Çertifikata|Certifikata"
    r"|CS\s?\d|Data|Kategoria|S\s?SH|SSH|ISO|REPUBLIKA|dhe$|Cert-|Çertifikimit)"
    r"|^[“”\"]|\bsh\.?\s?p\.?\s?k\b|\bpër\s+kodet\b|\bS\s?SH\b|Sistemeve\s+t[ëe]\s+Menaxhimit",
    re.IGNORECASE,
)
TABLE_HINT_RE = re.compile(
    r"Kategoria\s+N[ëe]n|Fushat\s+kritike|Kategorite\s+e\s+produkteve|\b[A-K]\s?(?:I{1,3}|IV|0)\b"  # sub-codes like "CII", "C0"
)


def build_scopes(lines: list[Line]) -> list[Scope]:
    """Each 'Akreditohet ...' line starts a scope, and so does every further '... në përputhje me:' heading in it."""
    scopes: list[Scope] = []
    current: Scope | None = None
    for line in lines:
        has_put_me = bool(PUT_ME_RE.search(line.text))
        starts_annex = bool(ACCREDITATION_START_RE.search(line.text))
        # Some annexes list several standards under one 'Akreditohet' line, each with its own heading.
        starts_block = current is not None and current.has_put_me and has_put_me
        if starts_annex or starts_block:
            current = Scope()
            scopes.append(current)
        if current is not None:
            current.lines.append(line.text)
            current.pages.add(line.page)
            current.has_put_me = current.has_put_me or has_put_me
    return scopes


def canonical_standard(raw: str) -> str:
    """'S SH ISO /IEC 27001 : 2022' -> 'ISO/IEC 27001:2022'."""
    text = clean_spaces(raw)
    text = re.sub(r"(?i)\bISO\b", "ISO", text)
    text = re.sub(r"(?i)\s*/\s*IEC\b", "/IEC", text)
    text = re.sub(r"\s*:\s*", ":", text)
    text = re.sub(r"(?i)\s*/\s*Amd\s*", "/Amd ", text)
    return text


def standard_family(standard: str) -> str:
    match = FAMILY_RE.match(standard)
    return match.group(1) if match else standard


def parse_ea_codes(text: str, lines: list[str]) -> tuple[list[str], bool]:
    if ALL_IAF_RE.search(text):
        return list(ALL_IAF_CODES), True
    numbers = {int(match.group(1)) for match in EA_CODE_RE.finditer(text)}
    for line in lines:
        match = TABLE_CODE_RE.match(line)
        if match:
            numbers.add(int(match.group(1)))
    return [f"{number:02d}" for number in sorted(numbers) if 1 <= number <= 39], False


def category_block(lines: list[str]) -> list[str]:
    """Lines after 'për kategoritë:' up to the next contact block, heading or table."""
    start = next((i + 1 for i, text in enumerate(lines) if PER_KATEGORI_RE.search(text)), None)
    if start is None:
        return []
    block = []
    for text in lines[start:start + 40]:
        if CATEGORY_STOP_RE.search(text):
            break
        text = SIGNATURE_TAIL_RE.sub("", text)  # the signature can share a text line with the last category
        if text and not COLUMN_HEADER_RE.match(text):
            block.append(text)
    return block


def continues_item(previous: str, text: str) -> bool:
    """True if a non-bullet line is the rest of the previous category (wrapped line), not a new heading or header."""
    if previous.rstrip().endswith((".", ";", ")")):
        return False
    return text[:1].islower() or bool(CONNECTIVE_END_RE.search(previous))


def parse_categories(lines: list[str]) -> list[str]:
    block = category_block(lines)
    if not any(CATEGORY_RE.match(text) for text in block):
        # Unbulleted list: one category per line, e.g. "Industri e lehtë dhe e mesme", "Ndërtesa".
        names = [clean_spaces(text).rstrip(".;") for text in block]
    else:
        items: list[str] = []
        for text in block:
            if CATEGORY_RE.match(text):
                items.append(text)
            elif items and continues_item(items[-1], text):
                items[-1] = f"{items[-1]} {text}"
        names = []
        for item in items:
            match = CATEGORY_RE.match(clean_spaces(item))
            if match:
                names.append(match.group(1))
    cleaned = (LETTER_PREFIX_RE.sub("", name).strip() for name in names)
    return unique(name for name in cleaned if LETTERS_RE.search(name))


def parse_scope(scope: Scope, warnings: list[str]) -> list[dict]:
    flat = " ".join(scope.lines)
    pages = sorted(scope.pages)

    # Some scopes omit "në përputhje me" (e.g. "… menaxhimit të vazhdimësisë së biznesit ISO 22301:2019, për kategoritë:").
    # Searching from the start of the scope is safe: only ISO tokens are matched.
    put_me = PUT_ME_RE.search(flat)
    tail = flat[put_me.end():] if put_me else flat
    stop = SCOPE_STOP_RE.search(tail)
    heading = tail[:stop.start()] if stop else tail[:300]
    standards = unique(canonical_standard(match.group(0)) for match in STANDARD_RE.finditer(heading))
    if not standards:
        warnings.append(f"annex pages {pages}: no ISO standard found in scope; scope skipped")
        return []

    codes, all_iaf = parse_ea_codes(tail, scope.lines)
    # Table layouts (Kategoria / Nën-kategori, Fushat kritike) do not survive text extraction reliably: flag, do not guess.
    is_table = bool(TABLE_HINT_RE.search(tail))
    categories = [] if is_table or not CATEGORY_HINT_RE.search(tail) else parse_categories(scope.lines)

    notes = []
    if not codes and not categories:
        notes.append("no EA/IAF codes or categories detected")
    if is_table:
        notes.append("table layout in annex; categories not extracted, verify manually")

    return [
        {
            "standard": standard,
            "standard_family": standard_family(standard),
            "all_iaf_sectors": all_iaf,
            "ea_codes": codes,
            "categories": categories,
            "annex_pages": pages,
            "needs_review": bool(notes),
            "review_notes": notes,
        }
        for standard in standards
    ]


# --- certificate assembly --------------------------------------------------

def new_certificate_record(pdf_path: Path, base_dir: Path) -> dict:
    return {
        "file_name": pdf_path.name,
        "file_path": pdf_path.relative_to(base_dir).as_posix(),
        "company_name": None,
        "accreditation_number": None,
        "accreditation_body": ACCREDITATION_BODY,
        "valid_from": None,
        "valid_until": None,
        "contact_info": {"address": None, "phone": None, "email": None, "contact_person": None},
        "page_count": 0,
        "scopes": [],
        "warnings": [],
        "status": "error",
    }


def parse_certificate(pdf_path: Path, base_dir: Path) -> dict:
    record = new_certificate_record(pdf_path, base_dir)
    warnings = record["warnings"]

    page_texts = extract_page_texts(pdf_path, warnings)
    record["page_count"] = len(page_texts)
    lines = to_lines(page_texts)

    record["company_name"] = parse_company_name(lines)
    record["accreditation_number"] = parse_accreditation_number(lines, pdf_path.name)
    record["valid_from"] = find_date(lines, VALID_FROM_RE)
    record["valid_until"] = find_date(lines, VALID_UNTIL_RE)
    record["contact_info"] = parse_contact(lines)

    for scope in build_scopes(lines):
        record["scopes"].extend(parse_scope(scope, warnings))

    missing = [name for name in ("company_name", "accreditation_number", "valid_until") if not record[name]]
    if missing:
        warnings.append("could not find: " + ", ".join(missing))

    if not lines:
        record["status"] = "error"
        warnings.append("no text layer found; the PDF needs OCR")
    else:
        needs_review = bool(missing or warnings or not record["scopes"]
                            or any(scope["needs_review"] for scope in record["scopes"]))
        record["status"] = "review" if needs_review else "ok"
    return record


def failed_certificate(pdf_path: Path, base_dir: Path, error: str) -> dict:
    record = new_certificate_record(pdf_path, base_dir)
    record["warnings"].append(f"parse failed: {error}")
    return record


# --- output ----------------------------------------------------------------

def csv_rows(certificates: list[dict]):
    seen = set()  # the same standard can appear on two annex pages; one row per company + standard + code
    for certificate in certificates:
        for scope in certificate["scopes"]:
            # Category-only scopes have no EA code; keep one row so the standard is not lost.
            for code in scope["ea_codes"] or [""]:
                key = (certificate["file_name"], scope["standard"], code)
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "company_name": certificate["company_name"] or "",
                    "accreditation_number": certificate["accreditation_number"] or "",
                    "standard": scope["standard"],
                    "ea_code": code,
                    "valid_until": certificate["valid_until"] or "",
                    "file_name": certificate["file_name"],
                }


def write_json(path: Path, certificates: list[dict], input_dir: Path) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_directory": str(input_dir),
        "certificate_count": len(certificates),
        "certificates": certificates,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_csv(path: Path, certificates: list[dict]) -> int:
    rows = list(csv_rows(certificates))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# --- CLI -------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract ISO accreditation scopes from DPA certificate PDFs.")
    parser.add_argument("--input-dir", type=Path, default=Path("."),
                        help="folder that holds the certificate PDFs (default: current directory)")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="folder for accreditation_data.json and accreditations_flat.csv (default: current directory)")
    parser.add_argument("--no-recursive", action="store_true", help="only look at PDFs directly inside --input-dir")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every scope as it is parsed")
    return parser.parse_args(argv)


def log_certificate(certificate: dict) -> None:
    LOG.info("  company=%s | CS=%s | valid_until=%s | scopes=%d | status=%s",
             certificate["company_name"], certificate["accreditation_number"],
             certificate["valid_until"], len(certificate["scopes"]), certificate["status"])
    for warning in certificate["warnings"]:
        LOG.warning("  %s", warning)
    for scope in certificate["scopes"]:
        LOG.debug("    %s | codes=%d | all_iaf=%s | categories=%d | pages=%s",
                  scope["standard"], len(scope["ea_codes"]), scope["all_iaf_sectors"],
                  len(scope["categories"]), scope["annex_pages"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Root stays at WARNING so pdfminer/pypdf internals do not flood the log in verbose mode.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    LOG.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    for stream in (sys.stdout, sys.stderr):  # never crash on a character the console cannot show
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if pdfplumber is None and PdfReader is None:
        LOG.error("Neither pdfplumber nor pypdf is installed. Run: pip install pdfplumber")
        return 2

    input_dir = args.input_dir.resolve()
    candidates = input_dir.iterdir() if args.no_recursive else input_dir.rglob("*")
    pdf_paths = sorted(path for path in candidates if path.is_file() and path.suffix.lower() == ".pdf")
    if not pdf_paths:
        LOG.warning("No PDF files found under %s", input_dir)
        return 1
    LOG.info("Found %d PDF(s) under %s", len(pdf_paths), input_dir)

    certificates = []
    for index, pdf_path in enumerate(pdf_paths, start=1):
        LOG.info("[%d/%d] %s", index, len(pdf_paths), pdf_path.name)
        try:
            certificate = parse_certificate(pdf_path, input_dir)
        except Exception as exc:  # corrupt or encrypted file: record it and continue
            LOG.error("  could not parse: %s", exc)
            certificate = failed_certificate(pdf_path, input_dir, str(exc))
        certificates.append(certificate)
        log_certificate(certificate)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / JSON_NAME
    csv_path = args.output_dir / CSV_NAME
    write_json(json_path, certificates, input_dir)
    row_count = write_csv(csv_path, certificates)

    scope_count = sum(len(certificate["scopes"]) for certificate in certificates)
    review = [certificate["file_name"] for certificate in certificates if certificate["status"] != "ok"]
    LOG.info("Wrote %s (%d certificates, %d scopes)", json_path, len(certificates), scope_count)
    LOG.info("Wrote %s (%d rows)", csv_path, row_count)
    if review:
        LOG.warning("%d certificate(s) need a look: %s", len(review), ", ".join(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
