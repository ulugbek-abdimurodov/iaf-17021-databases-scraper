#!/usr/bin/env python3
"""Turn the EGAC scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads egac_ms_bodies/cabs.json and each body's schedule of accreditation (the "…B.pdf" in
files/<ref - name>/<status>/<accreditation>/scopes/). The scope tree on the EGAC web page is
the same 300-line catalogue for every body, so the accredited scope comes from the PDF only.

The schedule is rebuilt as layout text from pdfplumber word positions (see pdf_text). It has one
block per standard, headed by the standard's name ("IAF Codes No.  Quality Management System
ISO 9001:2015 According to ISO/IEC 17021-3:2017"); a block runs on across page breaks until
the next heading. Kinds of block:

- IAF code tables (ISO 9001 / 14001 / 45001 and others): the number column is the IAF / EA
  code 1-39, taken as written, from the left-hand number column; a sector name that narrows
  the sector ("Limited to …") goes in the scope note. The sector names are read too, only to
  report tables where numbers and names disagree.
- ISO 22000 / FSSC 22000: ISO 22003-1 food chain categories and sub-categories (C, CI, BIII,
  …), classified to EA with the table of the BAS / ESYD / TÜRKAK datasets.
- ISO 13485: IAF MD 8 main technical areas, classified with the ESYD table.
- A heading with no list under it (ISO 50001, ISO/IEC 27001, ISO 22301, …): no sector list,
  recorded for all EA sectors.

Scanned schedules without text of accredited bodies are classified by hand in MANUAL.

Run:  python prepare_certifind.py  [--data egac_ms_bodies] [--out ../../certifind/data/egac-egypt]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "EGAC"
REGISTER_URL = "https://egac.gov.eg/en/accredited-cabs/"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

STATUSES = {"Accredited": "ACTIVE", "Suspended": "SUSPENDED", "Withdrawn": "WITHDRAWN", "Expired": "WITHDRAWN"}

# Certification standards named in a heading. Accreditation standards (17021-x, 22003-1,
# 27006, 50003, 20000-6, 21030, 28003, 42006) are not listed, so "According to …" is ignored.
STANDARD_PATTERNS = [
    ("ISO 9001", r"ISO\s*9001(?!\d)"), ("ISO 14001", r"ISO\s*14001"), ("ISO 45001", r"ISO\s*45001"),
    ("FSSC 22000", r"FSSC\s*22000"), ("ISO 22000", r"ISO\s*22000"), ("ISO 50001", r"ISO\s*50001"),
    ("ISO 13485", r"ISO\s*13485"), ("ISO/IEC 27001", r"27001"), ("ISO/IEC 27701", r"27701"),
    ("ISO/IEC 20000-1", r"20000-1(?!\d)"), ("ISO 22301", r"22301"), ("ISO 37001", r"ISO\s*37001"),
    ("ISO 37301", r"ISO\s*37301"), ("ISO 39001", r"ISO\s*39001"), ("ISO 41001", r"ISO\s*41001"),
    ("ISO 21001", r"ISO\s*21001"), ("ISO 29993", r"ISO\s*29993"), ("ISO 29994", r"ISO\s*29994"),
    ("ISO 55001", r"ISO\s*55001"), ("ISO/IEC 42001", r"42001"), ("ISO 7101", r"ISO\s*7101"),
    ("ISO 28000", r"ISO\s*28000"), ("ISO 28001", r"ISO\s*28001"), ("ISO 19443", r"ISO\s*19443"),
    ("ISO 30401", r"ISO\s*30401"), ("ISO 18788", r"ISO\s*18788"), ("ISO 56001", r"ISO\s*56001"),
    ("ISO 44001", r"ISO\s*44001"), ("ISO 22716", r"ISO\s*22716"), ("ISO 29001", r"ISO\s*29001"),
    ("EN 15224", r"15224"), ("ISO 37101", r"ISO\s*37101"), ("ISO 20121", r"ISO\s*20121"), ("ISO 46001", r"ISO\s*46001"),
]
# Headings that name the standard but leave out its number.
NAMED_HEADINGS = [
    ("ISO/IEC 27001", r"Information\s*Security\s*Management"),
    ("ISO 22301", r"Business\s*Continuity"),
    ("ISO 21001", r"Educational?\s*organi[sz]ations?"),
    ("ISO 37001", r"Anti-?\s*Bribery"),
    ("ISO 9001", r"^(?:IAF\s*Codes\s*(?:No\.?)?\s*)?Quality\s*Management\s*Systems?\s*(?:According|In\s*accordance)"),
]
# Guidance standards in a heading (not certifiable against); their block is skipped.
EXCLUDED_HEADINGS = {"ISO 37000": r"ISO\s*37000", "ISO 10002": r"ISO\s*10002"}
HEADING_WORDS = re.compile(r"Management|According|accordance|scheme|IAF Codes|Security|Certification",
                           re.I)
# Certification standard -> (accreditation standard, certificate suffix), as in the ESYD dataset.
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")
FOOD_STANDARDS = {"ISO 22000", "FSSC 22000"}
MEDICAL_STANDARDS = {"ISO 13485"}
ALL_NOTE = "No sector list in schedule; recorded for all EA sectors"

FOOD = esyd.FOOD_CATEGORIES
MEDICAL = {name: codes for name, _, codes in esyd.MEDICAL_AREAS}
FOOD_TOKEN = re.compile(r"(?<![\w/.-])([A-K])(0|I{1,3}|IV)?(?![\w/.-])")

# The end of the scope part: the list of countries the body certifies in.
# Matched against the line with its spaces removed: some schedules have no space
# characters at all, so their words run together ("1st Accreditationdate").
STOP = re.compile(r"Thisconformityassessmentbody|Note\*:|countrieslistedbelow", re.I)
# Page header and footer lines.
PAGE_FURNITURE = re.compile(
    r"ScheduleNo|ScheduleofAccreditation|IssuedTo|forCertificationBody|Accreditationdate|"
    r"MinistryofIndustry|EgyptianAccreditation|^EGAC$|Kornish|Tel\.|Fax|madein|egac\.gov|"
    r"Page\d+of\d+|F4WI6C|Validto", re.I)
HEADER_START = re.compile(r"EgyptianAccreditationCouncil", re.I)
HEADER_END = re.compile(r"Accreditationdate", re.I)
CODE_ROW = re.compile(r"^(\s*)(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?=\s|$)(.*)$")
CODE_COLUMN = 30  # a code starts left of this character column
LONE_TOLERANCE = 4  # columns a code without a sector name may sit from the section's code column
MEDICAL_COLUMN = 45  # the IAF MD 8 main technical area column ends left of this column
POINTS_PER_COLUMN = 5.0  # page x position (pt) per character column of the layout text
ROW_TOLERANCE = 3.0  # words whose tops differ by at most this (pt) are on one row
# EA sector names as the schedules print them, used only to cross-check the number column.
EA_NAMES = [(n, re.compile(p, re.I)) for n, p in [
    (1, r"Agricultur"), (2, r"Mining"), (3, r"Food products"), (4, r"Textiles"), (5, r"Leather"),
    (6, r"Wood"), (7, r"Pulp"), (8, r"Publishing"), (9, r"Printing"), (10, r"coke"),
    (11, r"Nuclear fuel"), (12, r"Chemicals"), (13, r"Pharma"), (14, r"Rubber"),
    (15, r"Non-?\s?metallic"), (16, r"Concrete"), (17, r"Basic metals|Base metal"),
    (18, r"Machinery"), (19, r"Electrical"), (20, r"Ship"), (21, r"Aerospace"),
    (22, r"transport equipment"), (23, r"not elsewhere"), (24, r"Recycling"), (25, r"Electricity"),
    (26, r"Gas supply"), (27, r"Water supply"), (28, r"^Construction|\bConstruction\b(?! of)"),
    (29, r"Wholesale"), (30, r"Hotels"), (31, r"Transport,? storage"), (32, r"Financial"),
    (33, r"Information"), (34, r"Engineering"), (35, r"^Other services"),
    (36, r"Public administration"), (37, r"^Education"), (38, r"Health and social"),
    (39, r"Other social"),
]]
LIMITED = re.compile(r"\b(limited|only|except|excluding|restricted)\b", re.I)

# Scanned schedules (no text layer) of accredited bodies, read from the PDF by hand.
# Same kinds of entries the parser collects: EA codes, food chain tokens, IAF MD 8 areas.
PAPER = {7: "Limited to “Paper products”"}
CATEGORY_C = ["C", "C0", "CI", "CII", "CIII", "CIV"]
MANUAL: dict[str, dict[str, dict]] = {
    # Schedule 10600/1B of 06.05.2021 (valid to 05.05.2025), 3 pages.
    "010601/1": {"ISO 9001": {"ea": [1, 3, 7, 8, 10, 12, 29, 30, 32, 33, 35, 36, 37], "limited": PAPER},
                 "ISO 14001": {"ea": [7, 8, 12, 14, 15, 16, 17, 18, 19, 22], "limited": PAPER},
                 "ISO 45001": {"ea": [7, 8, 12, 14, 15, 16, 17, 18, 19, 22], "limited": PAPER},
                 "ISO 22000": {"food": ["C", "CI", "CII", "CIII", "CIV"]}},
    # Schedule 011806 B, issue 03 of 09.02.2023, 4 pages.
    "011806": {"ISO 9001": {"ea": [4, 5, 6, 10, 12, 13, 14, 17, 18, 19, 20, 22, 23, 28, 29, 32, 33, 34, 35,
                                   36, 37, 38]},
               "ISO 14001": {"ea": [7, 10, 12, 13, 14, 15, 16, 17, 18, 19, 22, 28, 29, 32, 33, 34, 35, 36, 37]},
               "ISO 45001": {"ea": [7, 10, 12, 13, 14, 15, 16, 17, 18, 19, 22, 28, 29, 32, 33, 34, 35, 36, 37]}},
    # Schedule 011902, issue 02 of 17.11.2023, 5 pages.
    "011902": {"ISO 9001": {"ea": [1, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 17, 18, 19, 20, 22, 23, 28, 29, 30, 32,
                                   33, 34, 35, 36, 37]},
               "ISO 14001": {"ea": [3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 19, 22, 23, 28, 29, 30, 32,
                                    33, 34, 35, 36, 37]},
               "ISO 45001": {"ea": [3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 17, 18, 19, 22, 23, 28, 29, 30, 32, 33,
                                    34, 35, 36, 37]}},
    # Schedule 012104 B, issue 01 of 26.01.2022 (filed as "012104-A.pdf"), 2 pages.
    "0121004": {"ISO 9001": {"ea": [29, 32, 33, 35, 36, 37]},
                "ISO 14001": {"ea": [29, 32, 33, 35, 36, 37]},
                "ISO 45001": {"ea": [29, 32, 33, 35, 36, 37]}},
    # Schedule 012219B, issue 01 of 31.01.2025, 2 pages.
    "012219": {"ISO 9001": {"ea": [1, 3, 30]}, "ISO 14001": {"ea": [3, 30]}, "ISO 45001": {"ea": [3, 30]},
               "ISO 22000": {"food": CATEGORY_C}},
    # Schedule 012220 B, revision 03 of 27.07.2025, 4 pages. ISO 10002 (guidelines) left out.
    "012220": {"ISO 22000": {"food": CATEGORY_C + ["D", "DI", "DII", "E"]},
               "ISO 50001": {},
               "ISO 13485": {"medical": ["Non-active medical devices", "Active (non-implantable) medical devices",
                                         "Active implantable medical devices", "Parts or services"]},
               "ISO 37001": {}, "ISO 37301": {}, "ISO 44001": {}, "ISO/IEC 20000-1": {}, "ISO 56001": {},
               "ISO 30401": {}},
    # Schedule 012303, issue 01 of 08.12.2023, 1 page.
    "012303": {"ISO 9001": {"ea": [1, 3, 30]}, "ISO 22000": {"food": CATEGORY_C}},
}


@dataclass
class Section:
    standard: str
    ea: set[int] = field(default_factory=set)
    food: list[str] = field(default_factory=list)
    medical: list[str] = field(default_factory=list)
    limited: dict[int, str] = field(default_factory=dict)
    named: set[int] = field(default_factory=set)  # EA codes by sector name, for the cross-check
    columns: list[int] = field(default_factory=list)  # text column of codes that have a sector name
    lone: list[tuple[int, int, int]] = field(default_factory=list)  # (from, to, column) without one
    dropped: list[int] = field(default_factory=list)

    def place_lone_codes(self) -> None:
        """A number without a sector name beside it (the schedule leaves the name out, or it
        sits on the next row) is a code only in the section's code column: a page header's
        stray "1" of "1st Accreditation date" is not."""
        cols = sorted(self.columns)
        typical = cols[len(cols) // 2] if cols else None
        for lo, hi, col in self.lone:
            if typical is None or abs(col - typical) <= LONE_TOLERANCE:
                self.ea |= set(range(lo, hi + 1))
            else:
                self.dropped.append(lo)

    def codes_and_note(self) -> tuple[str, str]:
        notes: list[str] = []
        codes = set(self.ea)
        if self.standard in FOOD_STANDARDS and self.food:
            letters = sorted({t[0] for t in self.food})
            for letter in letters:
                codes |= expand(FOOD[letter])
            subs = [t for t in dict.fromkeys(self.food) if len(t) > 1]
            notes.append(f"ISO 22003-1 categories {', '.join(letters)}"
                         + (f" (sub-categories {', '.join(subs)})" if subs else "")
                         + " (classified to EA by sector)")
        if self.standard in MEDICAL_STANDARDS and self.medical:
            areas = list(dict.fromkeys(self.medical))
            for a in areas:
                codes |= expand(MEDICAL[a])
            notes.append(f"IAF MD 8 main technical areas: {'; '.join(areas)} (classified to EA by sector)")
        for ea, text in sorted(self.limited.items()):
            notes.append(f"EA {ea} {text}")
        if not codes:
            return "ALL", "; ".join([ALL_NOTE] + notes)
        return compress(codes), "; ".join(notes)


def expand(spec: str) -> set[int]:
    out: set[int] = set()
    for part in spec.split(";"):
        a, _, b = part.partition("-")
        out |= set(range(int(a), int(b or a) + 1))
    return out


def compress(codes: set[int]) -> str:
    ordered, parts = sorted(codes), []
    start = prev = ordered[0]
    for c in ordered[1:] + [None]:
        if c is not None and c == prev + 1:
            prev = c
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if c is not None:
            start = prev = c
    return ";".join(parts)


def standards_in(line: str) -> list[str]:
    found = []
    for std, pattern in STANDARD_PATTERNS:
        for m in re.finditer(pattern, line):
            found.append((m.start(), std))
    return [std for _, std in sorted(found)]


def pdf_text(pdf: Path) -> str:
    """The PDF as layout text, one line per row of words that share a baseline.

    Built from pdfplumber word positions rather than a text dump: the number column of a
    schedule is often a separate, taller table cell, and text-order extraction then moves
    the codes several rows away from their sector names (even above the standard's heading).
    """
    out: list[str] = []
    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            rows: list[list[dict]] = []
            for w in sorted(page.extract_words(), key=lambda w: (round(w["top"]), w["x0"])):
                if rows and abs(rows[-1][0]["top"] - w["top"]) <= ROW_TOLERANCE:
                    rows[-1].append(w)
                else:
                    rows.append([w])
            for row in rows:
                line = ""
                for w in sorted(row, key=lambda w: w["x0"]):
                    col = int(w["x0"] / POINTS_PER_COLUMN)
                    line += " " * max(1 if line else 0, col - len(line)) + w["text"]
                out.append(line)
            out.append("")
    return "\n".join(out)


def medical_area(text: str) -> str | None:
    k = text.strip().lower()
    for name, prefixes, _ in esyd.MEDICAL_AREAS:
        if k.startswith(prefixes):
            return name
    return None


def parse_schedule(text: str) -> tuple[dict[str, Section], list[str], list[str]]:
    """Sections by standard, the headings seen, and lines the parser could not place."""
    sections: dict[str, Section] = {}
    headings: list[str] = []
    notes: list[str] = []
    current: list[Section] = []
    prev = ""
    in_header = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        flat = re.sub(r"\s+", " ", line).strip()  # for matching words; `line` keeps the columns
        bare = re.sub(r"\s+", "", line)
        if STOP.search(bare):
            current = []
            prev = flat
            continue
        # Page header: from the council's name down to the "1st Accreditation date" line. It
        # holds the body's name and address, whose numbers are not codes.
        if HEADER_START.search(bare):
            in_header = True
        header_line = in_header
        if in_header and HEADER_END.search(bare):
            in_header = False
        furniture = header_line or bool(PAGE_FURNITURE.search(bare))
        stds = [] if furniture else standards_in(flat)
        excluded = [] if furniture else [s for s, p in EXCLUDED_HEADINGS.items() if re.search(p, flat)]
        if excluded and HEADING_WORDS.search(flat):
            notes.append(f"excluded ({', '.join(excluded)}, not a certification standard): {flat[:120]}")
            current = []
            prev = flat
            continue
        if not furniture and re.search(r"19443|application of ISO\s*9001", flat):
            stds = ["ISO 19443"]
        if not furniture and not stds and re.search(r"Management\s*Systems?.*(?:According|accordance)", flat, re.I):
            stds = [std for std, pattern in NAMED_HEADINGS if re.search(pattern, flat, re.I)][:1]
            if not stds:
                notes.append(f"heading without a known standard: {flat[:120]}")
                current = []
                prev = flat
                continue
        is_heading = bool(stds) and (HEADING_WORDS.search(flat)
                                     or (flat.startswith("ISO") and re.search(r"Management", prev)
                                         and not standards_in(prev)))
        if is_heading:
            current = [sections.setdefault(s, Section(s)) for s in dict.fromkeys(stds)]
            headings.append(flat)
            prev = flat
            continue
        prev = flat
        if furniture:
            continue
        if not current:
            continue
        kind = current[0].standard
        if kind in FOOD_STANDARDS:
            for m in FOOD_TOKEN.finditer(line):
                token = m.group(1) + (m.group(2) or "")
                for sec in current:
                    sec.food.append(token)
            continue
        if kind in MEDICAL_STANDARDS:
            left = re.sub(r"\s+", " ", line[:MEDICAL_COLUMN]).strip()
            if left and (area := medical_area(left)):
                for sec in current:
                    sec.medical.append(area)
            continue
        label = re.sub(r"^\d{1,2}(?:\s*[-–]\s*\d{1,2})?(?=\s|$)", "", flat).strip()
        for n, pattern in EA_NAMES:
            if pattern.search(label):
                for sec in current:
                    sec.named.add(n)
                break
        m = CODE_ROW.match(line)
        if m and len(m.group(1)) < CODE_COLUMN:
            lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
            if 1 <= lo <= hi <= 39:
                rest = m.group(4).strip()
                col = len(m.group(1))
                for sec in current:
                    if not rest:  # placed later, once the section's code column is known
                        sec.lone.append((lo, hi, col))
                        continue
                    sec.ea |= set(range(lo, hi + 1))
                    sec.columns.append(col)
                    if LIMITED.search(rest):
                        sec.limited[lo] = re.sub(r"\s+", " ", rest).rstrip(".")
            else:
                notes.append(f"number out of range: {line.strip()[:100]}")
    for sec in sections.values():
        sec.place_lone_codes()
        if sec.dropped:
            notes.append(f"{sec.standard}: numbers {sec.dropped} outside the code column, not taken as codes")
    return sections, headings, notes


def schedule_pdf(data: Path, accreditation: dict) -> Path | None:
    """The schedule: the file under Scopes, or else a file under Certificates whose name says
    it is the schedule (012403 filed "012403_scope.pdf" there and a certificate under Scopes)."""
    files = [f for f in accreditation["files"] if f["local_path"].lower().endswith(".pdf")
             and (data / f["local_path"]).exists()]
    scopes = [data / f["local_path"] for f in files if f["section"] == "Scopes"]
    named = [data / f["local_path"] for f in files if f["section"] != "Scopes"
             and re.search(r"scope|[-_ ]?B(?:[-_ .(]|$)", Path(f["file_name"]).stem, re.I)]
    for pdf in scopes + named:
        if has_text(pdf):
            return pdf
    return scopes[0] if scopes else None


def has_text(pdf: Path) -> bool:
    with pdfplumber.open(pdf) as doc:
        return sum(len((p.extract_text() or "").strip()) for p in doc.pages) >= 200


def date(value: str) -> str:
    return datetime.strptime(value.strip(), "%d %b %Y").strftime("%Y-%m-%d") if value and value.strip() else ""


def website(value: str) -> str:
    v = (value or "").strip().replace("www..", "www.")
    return "" if not v or re.search(r"none\.com|^https?://(?:www\.)?$|^-+$", v, re.I) else v


# Country codes whose numbers keep a leading 0 after the code (no trunk prefix to drop).
KEEPS_ZERO = {"39", "225", "242"}


def phone(value: str) -> str:
    """The register's number, without the national trunk 0 it often keeps after the
    country code ("+20 0100 675 5251" -> "+20 100 675 5251")."""
    v = re.sub(r"\s+", " ", (value or "").strip())
    m = re.match(r"^\+(\d{1,3}) 0+(?=\d)", v)
    if m and m.group(1) not in KEEPS_ZERO:
        v = f"+{m.group(1)} " + v[m.end():]
    return v


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def run(args: argparse.Namespace) -> int:
    entries = json.loads((args.data / "cabs.json").read_text(encoding="utf-8"))
    review: dict[str, list[str]] = defaultdict(list)
    bodies, accreditations, scopes = [], [], []

    for entry in sorted(entries, key=lambda e: e["reference_no"]):
        ref = entry["reference_no"]
        status = STATUSES[entry["listed_status"]]
        name = re.sub(r"\s+", " ", entry["name"]).strip()
        c = entry.get("contacts") or {}
        bodies.append({"name": name, "country": entry["country"], "registration_no": "",
                       "phone": phone(c.get("Phone No.")), "email": (c.get("Email") or "").strip(),
                       "website": website(c.get("Website")), "address": (c.get("Address") or "").strip(),
                       "source_url": entry["detail_url"] or REGISTER_URL, "verified_at": ""})

        sections: dict[str, Section] = {}
        manual = MANUAL.get(ref)
        if status == "WITHDRAWN":
            review["Withdrawn or expired (no scopes written)"].append(f"{ref} {name} ({entry['listed_status']})")
        elif manual is not None:
            review["Scanned schedules classified by hand"].append(f"{ref} {name}")
            for std, data in manual.items():
                sec = sections.setdefault(std, Section(std))
                sec.ea |= set(data.get("ea", []))
                sec.food += data.get("food", [])
                sec.medical += data.get("medical", [])
                sec.limited.update(data.get("limited", {}))
        elif not entry["accreditations"]:
            review["Detail page not scraped (no schedule, no scopes)"].append(f"{ref} {name}")
        else:
            pdf = schedule_pdf(args.data, entry["accreditations"][0])
            text = pdf_text(pdf) if pdf else ""
            if len(re.sub(r"\s", "", text)) < 200:
                review["No readable schedule (no scopes)"].append(f"{ref} {name}: {pdf.name if pdf else 'no PDF'}")
            else:
                sections, headings, notes = parse_schedule(text)
                for h in headings:
                    review["Headings"].append(f"{ref}: {h}")
                for n in notes:
                    review["Parser notes"].append(f"{ref}: {n}")
                if not sections:
                    review["Schedule without recognised standards"].append(f"{ref} {name}")

        rows: list[tuple[str, str, str]] = []
        for std, sec in sections.items():
            codes, note = sec.codes_and_note()
            if codes == "ALL":
                review["Recorded as ALL"].append(f"{ref} {std}")
            for ea, text in sec.limited.items():
                review["Limited scopes"].append(f"{ref} {std} EA {ea}: {text}")
            if sec.ea and sec.named and sec.ea != sec.named:
                review["Code column and sector names disagree"].append(
                    f"{ref} {std}: only numbers {sorted(sec.ea - sec.named)}, "
                    f"only names {sorted(sec.named - sec.ea)}")
            rows.append((std, codes, note))

        schemes_used = sorted({SCHEMES.get(std, DEFAULT_SCHEME) for std, _, _ in rows} | {DEFAULT_SCHEME})
        issued = date(entry["date_on_page"]) if entry["date_label"] == "Accredited Date" else ""
        issued = issued or date(entry["accreditation_date"])
        for acc_std, suffix in schemes_used:
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": ref + suffix, "body_name": name,
                "accreditation_standard": acc_std, "status": status,
                "issue_date": issued, "expiry_date": date(entry["expiry_date"]),
                "proof_url": entry["detail_url"] or REGISTER_URL})
        for std, codes, note in rows:
            suffix = SCHEMES.get(std, DEFAULT_SCHEME)[1]
            scopes.append({"certificate_number": ref + suffix, "certification_standard": std,
                           "ea_codes": codes, "status": status, "scope_note": note})

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda b: b["name"].lower()))
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    # CertiFind keeps only bodies with a valid accreditation (database/prune_inactive.py).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from prune_inactive import prune
    for line in prune(args.out):
        print(f"removed (not valid): {line}")
    out = ["# EGAC dataset review", "", f"{len(bodies)} bodies, {len(accreditations)} accreditations, "
           f"{len(scopes)} scopes", ""]
    for title, items in review.items():
        out += [f"## {title} ({len(items)})", "", *[f"- {i}" for i in items], ""]
    args.review.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:3]))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=HERE / "egac_ms_bodies")
    p.add_argument("--out", type=Path, default=HERE.parent.parent / "certifind" / "data" / "egac-egypt")
    p.add_argument("--review", type=Path, default=HERE / "egac_review.md")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
