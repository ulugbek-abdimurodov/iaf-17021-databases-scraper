#!/usr/bin/env python3
"""Turn the BAS (NAB) scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads nab_management_system_bodies/bodies.json and the "full scope" annexes that
`nab_scraper.py` downloaded next to it, and writes:

    <out>/bodies.csv, accreditations.csv, scopes.csv   in the CertiFind importer format
    <review>                                           everything a person should check

One register entry is one BAS accreditation certificate ("N ОСС"). Its full-scope annex is
the accreditation order: one numbered section per certification standard, each with a
sector table. The Bulgarian annex is read (it is the official one and usually the newest);
the English annex is compared with it and every difference goes to the review file.

Sector tables come in three formats, all converted to EA codes:

- IAF code | description | NACE rev. 2 (ISO 9001 / 14001 / 45001): the IAF code is the EA
  code. When the NACE list is narrower than the IAF ID 1 sector, the row is a limited scope
  and the NACE codes are kept in the scope note.
- ISO 50003 technical area | IAF code | NACE (ISO 50001): the IAF column gives the EA code.
- ISO 22003-1 categories A-K (ISO 22000): classified to EA by sector, with the same table
  as the RENAR, DPA, TÜRKAK and ESYD datasets.

Standards with no sector table (ISO/IEC 27001, ISO 37001, ISO 39001) are recorded as ALL.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worddoc import read_text  # noqa: E402

AB_CODE = "BAS"
COUNTRY = "Bulgaria"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# ------------------------------------------------------------------------------- curated data
# Latin-script names. The register only has the Cyrillic legal name and a machine translation
# ("TUFF RAINLAND", "IMMERTION CERTIFICATION"), and the certificates are scans, so these come
# from the English annexes, the bodies' e-mail domains and their usual spelling. The
# Cyrillic legal name follows in brackets, as on the certificate.
LATIN_NAMES = {
    "11257": "Emergency Certification OOD",
    "11091": "Alpha Quality Certification EOOD",
    "10485": "NGN OOD",
    "11252": "Q-Aid Europe EOOD",
    "11291": "Q-Aid Europe EOOD",
    "11013": "OTC Bulgaria EOOD",
    "10447": "Center for Testing and European Certification EOOD",
    "11035": "TÜV Rheinland Bulgaria EOOD",
    "10538": "Verification OOD",
    "11259": "MG Global OOD",
    "11364": "Axerta International EOOD",
    "11258": "MS-Cert Bulgaria OOD",
    "10511": "Dedal - Attestation and Certification OOD",
    "11261": "INCERT EOOD",
    "10423": "CSB EOOD",
    "11310": "SGS Bulgaria EOOD",
    "11265": "TÜV NORD Bulgaria EOOD",
    "11268": "National Institute for Research and Certification EOOD",
    "11260": "Certification and Inspection Bulgaria OOD",
    "11314": "Smart Certification EOOD",
}

# Office address (the management address when the annex gives no office), from the annex
# header; English annex wording where it has one, otherwise transliterated from Bulgarian.
# Bodies whose annex has no address get the register's office city.
ADDRESSES = {
    "10447": "2 Industrialna Str., Industrialen district, 6000 Stara Zagora, Bulgaria",
    "10485": "3 Planinski Izgled Str., Kamenets district, 6300 Haskovo, Bulgaria",
    "10511": "54 Macedonia Str., 8000 Burgas, Bulgaria",
    "10538": "104 Pernik Str., floor 7, studio 20, 1309 Sofia, Bulgaria",
    "11013": "12 Hristo Belchev Str., floor 2, 1000 Sofia, Bulgaria",
    "11035": "36 Dragan Tsankov Blvd., block B, floor 8, office 801, Izgrev district, 1040 Sofia, Bulgaria",
    "11091": "8-10 Kishinev Str., 1407 Sofia, Bulgaria",
    "11252": "14 Georgi Benkovski Str., floor 2, Oborishte district, 1000 Sofia, Bulgaria",
    "11258": "26 Vasil Kanchev Str., entr. D, floor 2, Stefan Karadzha Business Centre, 1510 Sofia, Bulgaria",
    "11260": "73 Tsarigradsko Shose Blvd., Business Centre, office 2.10, 4000 Plovdiv, Bulgaria",
    "11261": "45 Kalimantsi Str., office 3, Slatina, 1505 Sofia, Bulgaria",
    "11265": "13 Nayden Gerov Str., 4000 Plovdiv, Bulgaria",
    "11268": "3 Ivan Vazov Str., 1000 Sofia, Bulgaria",
    "11314": "91 Aleksandar Malinov Blvd., office 503, Mladost 4, 1715 Sofia, Bulgaria",
    "11364": "19 Lavele Str., 1000 Sofia, Bulgaria",
}
CITIES = {"Пловдив": "Plovdiv", "София": "Sofia", "Хасково": "Haskovo", "Стара Загора": "Stara Zagora",
          "Бургас": "Burgas"}

# National company IDs (ЕИК) quoted in the annexes.
REGISTRATION_NOS = {"11364": "206269340"}

# Two register entries for one certificate: 11252 is the renewal (valid 2026-04-01 to
# 2030-03-31) without contacts, 11291 the previous certificate (expired 2026-03-31). Dates
# come from 11252, contacts from 11291; the scope from the newest annex of the two.
MERGE = {"11291": "11252"}

# Annex files that are not a scope: 11364's Bulgarian file is the order suspending the
# accreditation (A 504 of 27.12.2024), not a scope.
NOT_A_SCOPE = {("11364", "bg")}

# The annex is the accreditation order: "ЗАПОВЕД № А 313 София, 28.09.2026" / "ORDER № A 153 Sofia, ...".
ORDER = re.compile(r"(?:№|No\.?)\s*[АA]\s*(\d+)\s*/?\s*(?:Sofia|София)?,?\s*(\d{1,2}\.\d{1,2}\.\d{4})")

# Register status -> CertiFind status.
STATUSES = {"Валиден сертификат": "ACTIVE", "Отнета акредитация": "WITHDRAWN",
            "Спряна акредитация": "SUSPENDED"}

# Section heading -> certification standard. The earliest match in the heading wins, so
# "ISO 22000 ... ISO 22003-1" is ISO 22000 and "ISO 50001 ... ISO 50003" is ISO 50001.
STANDARD_PATTERNS = [
    ("ISO 9001", r"9001"),
    ("ISO 14001", r"14001"),
    ("ISO 45001", r"45001"),
    ("ISO 22000", r"ISO 22000"),
    ("ISO/IEC 27001", r"27001"),
    ("ISO 50001", r"50001"),
    ("ISO 39001", r"39001"),
    ("ISO 37001", r"37001"),
    ("PEFC", r"PEFC"),
    ("PAS 24000", r"24000"),
]
HEADING_VERB = re.compile(r"съгласно|according|accordance|в съответствие", re.IGNORECASE)

# Certification standard -> (accreditation standard, certificate suffix), as in the other datasets.
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")

EXCLUDED_SCHEMES = {
    "PEFC": "PEFC sustainable forest management, not an international management-system standard",
    "PAS 24000": "PAS 24000 / FSSC 24000 social management, not an international management-system standard",
}
SECTOR_SCHEMES = {"ISO 9001", "ISO 14001", "ISO 45001", "ISO 22000", "ISO 50001"}
ALL_NOTES = {
    "ISO/IEC 27001": "No sector list in annex; recorded for all EA sectors",
    "ISO 39001": "Annex lists the ISO 39001 Annex A 4.1 activity groups 1-4, not EA sectors; "
                 "recorded for all EA sectors",
    "ISO 37001": "Accredited for the territory of the Republic of Bulgaria; no sector list, "
                 "recorded for all EA sectors",
}

# ISO 22003-1:2022 food chain categories -> EA (same table as the ESYD and TÜRKAK datasets).
FOOD_CATEGORIES = {
    "A": "1", "B": "1", "C": "3", "D": "3", "E": "30", "F": "29", "G": "31", "H": "35",
    "I": "7;14;15;17", "J": "18", "K": "12;13",
}

# IAF ID 1:2023 sector -> NACE rev. 2, as BAS prints it in its annexes. A row whose NACE list
# does not cover all of these is a limited scope.
IAF_ID1 = {
    1: "01, 02, 03", 2: "05, 06, 07, 08, 09", 3: "10, 11, 12", 4: "13, 14", 5: "15", 6: "16",
    7: "17", 8: "58.1, 59.2", 9: "18", 10: "19", 11: "24.46", 12: "20", 13: "21", 14: "22",
    15: "23 except 23.5, 23.6", 16: "23.5, 23.6", 17: "24 except 24.46, 25 except 25.4, 33.11",
    18: "25.4, 28, 30.4, 33.12, 33.2", 19: "26, 27, 33.13, 33.14, 95.1", 20: "30.1, 33.15",
    21: "30.3, 33.16", 22: "29, 30.2, 30.9, 33.17", 23: "31, 32, 33.19", 24: "38.3",
    25: "35.1", 26: "35.2", 27: "35.3, 36", 28: "41, 42, 43", 29: "45, 46, 47, 95.2",
    30: "55, 56", 31: "49, 50, 51, 52, 53, 61", 32: "64, 65, 66, 68, 77",
    33: "58.2, 62, 63.1", 34: "71, 72, 74 except 74.2, 74.3",
    35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 36: "84", 37: "85", 38: "75, 86, 87, 88",
    39: "37, 38.1, 38.2, 39, 59.1, 60, 63.9, 79, 90, 91, 92, 93, 94, 96",
}

# Cyrillic letters that look like Latin ones, for category codes typed in Cyrillic.
LOOKALIKES = str.maketrans("АВСЕНКМОРТХІШ", "ABCEHKMOPTXIШ")

DATE = r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
NAB_FOOTER = re.compile(r"52\s*[АA]\s*[“\"„]?Dr\.?\s*G\.?.*?nab-bas\.bg[^\s]*", re.DOTALL)
CRITICAL = re.compile(r"ритичн|ritical|conditionally provided", re.IGNORECASE)


class Review:
    def __init__(self) -> None:
        self.sections: dict[str, list[str]] = defaultdict(list)

    def add(self, section: str, line: str) -> None:
        self.sections[section].append(line)

    def write(self, path: Path, summary: list[str]) -> None:
        order = ["Withdrawn and merged entries", "Annex versions", "Draft EA mappings (check these)",
                 "Conditionally granted (critical) codes", "Limited scopes",
                 "Bulgarian and English annexes differ", "Annexes without a sector table (recorded as ALL)",
                 "Excluded schemes", "Sections without codes", "Unparsed rows", "Contacts and names"]
        out = ["# BAS dataset review", "", *summary, ""]
        for name in order + [s for s in self.sections if s not in order]:
            items = self.sections.get(name)
            if not items:
                continue
            out += [f"## {name} ({len(items)})", "", *[f"- {i}" for i in items], ""]
        path.write_text("\n".join(out), encoding="utf-8")


# ------------------------------------------------------------------------------------ helpers
def iso(value: str) -> str:
    m = re.fullmatch(DATE, value.strip())
    return date(int(m[3]), int(m[2]), int(m[1])).isoformat() if m else ""


def ea_spec(codes: set[int]) -> str:
    """{1,2,3,5} -> '1-3;5'."""
    parts, run = [], []
    for c in sorted(codes) + [None]:
        if run and c is not None and c == run[-1] + 1:
            run.append(c)
            continue
        if run:
            parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [c] if c is not None else []
    return ";".join(parts)


def expand(spec: str) -> set[int]:
    codes: set[int] = set()
    for part in spec.split(";"):
        lo, _, hi = part.partition("-")
        codes.update(range(int(lo), int(hi or lo) + 1))
    return codes


def clean(cell: str) -> str:
    return re.sub(r"\s+", " ", cell).strip()


# --------------------------------------------------------------------------------- NACE lists
@dataclass(frozen=True)
class Nace:
    code: str
    excl: frozenset[str] = frozenset()

    def __str__(self) -> str:
        return self.code + (f" except {', '.join(sorted(self.excl))}" if self.excl else "")


def norm_code(raw: str) -> str:
    div, _, rest = raw.partition(".")
    return div.zfill(2) + (f".{rest}" if rest else "")


EXCEPT_WORDS = re.compile(r"с\s+изключение\s+на|с\s+изкл\.?\s*на|изкл\.?|без|освен|excluding|except",
                          re.IGNORECASE)
REGULATION = re.compile(r"(?:Регламент\s*\(ЕС\)|Regulation\s*\(EU\))\s*(?:№|No\.?)?\s*(\d+/\d{4})", re.IGNORECASE)


def normalise_nace(text: str) -> str:
    """Bulgarian abbreviations and OCR slips -> '24 except 24.46, 25 except 25.4, 33.11'."""
    text = re.sub(r"(?<=[\d.])З|З(?=[\d.])", "3", text)          # Cyrillic Ze read for a 3
    text = REGULATION.sub("", text).replace("(", " ").replace(")", " ")
    text = EXCEPT_WORDS.sub(" except ", text)
    return re.sub(r"\s+(?:и|and)\s+", ", ", text).strip()


def is_nace_cell(cell: str) -> bool:
    text = normalise_nace(cell)
    return bool(re.search(r"\d", text)) and bool(re.fullmatch(r"(?:[\d\s.,;*]|except)+", text))


def parse_nace(text: str) -> list[Nace]:
    """'24 without 24.46; 25 except 25.4, 33.11' -> [24 except 24.46, 25 except 25.4, 33.11]."""
    text = normalise_nace(text)
    items: list[list] = []
    excepting = False
    for tok in re.findall(r"except|\d{1,2}(?:\.\d{1,2})?", text):
        if tok == "except":
            excepting = bool(items)
            continue
        code = norm_code(tok)
        if excepting and code.startswith(items[-1][0] + "."):
            items[-1][1].add(code)
            continue
        excepting = False
        items.append([code, set()])
    return [Nace(c, frozenset(e)) for c, e in items]


def under(code: str, parent: str) -> bool:
    return code == parent or code.startswith(parent + ".")


def covers(listed: list[Nace], ref: Nace) -> bool:
    for item in listed:
        if item.code == ref.code and item.excl <= ref.excl:
            return True
        if under(ref.code, item.code) and ref.code != item.code and not any(under(ref.code, e) for e in item.excl):
            return True
    return False


REFERENCE = {ea: parse_nace(text) for ea, text in IAF_ID1.items()}


def is_limited(ea: int, listed: list[Nace]) -> bool:
    return not all(covers(listed, ref) for ref in REFERENCE[ea])


def ea_of_nace(listed: list[Nace]) -> set[int]:
    """EA sectors (IAF ID 1) a NACE list falls in, for rows whose IAF cell is blank."""
    found = set()
    for item in listed:
        for ea, refs in REFERENCE.items():
            for ref in refs:
                overlap = under(item.code, ref.code) or under(ref.code, item.code)
                if overlap and not any(under(ref.code, e) for e in item.excl) \
                        and not any(under(item.code, e) for e in ref.excl):
                    found.add(ea)
    return found


# ------------------------------------------------------------------------------ annex parsing
@dataclass
class Section:
    standard: str
    heading: str
    rows: dict[int, list[Nace]] = field(default_factory=dict)   # EA -> NACE list (9001-type, 50001)
    food: set[str] = field(default_factory=set)                 # ISO 22003-1 category letters
    critical: set[int] = field(default_factory=set)
    regulations: dict[int, set[str]] = field(default_factory=dict)   # EA -> EU regulations in the NACE cell
    inferred: dict[int, str] = field(default_factory=dict)           # EA read from NACE (blank IAF cell)
    unparsed: list[str] = field(default_factory=list)

    def ea(self) -> set[int]:
        codes = set(self.rows)
        for letter in self.food:
            codes |= expand(FOOD_CATEGORIES[letter])
        return codes


EA_CELL = re.compile(r"\s*(\d{1,2})(?:\s+\1)?\s*(\*?)\s*")
FOOD_CELL = re.compile(r"([A-K])\s*(?:[0OIVШ]{1,4})?\.?")


def detect_standard(text: str) -> str | None:
    if len(text) < 30 or not HEADING_VERB.search(text):
        return None
    hits = [(m.start(), std) for std, pat in STANDARD_PATTERNS if (m := re.search(pat, text))]
    return min(hits)[1] if hits else None


def critical_codes(text: str) -> set[int]:
    m = re.search(r"IAF\s*(?:код\w*|codes?|№)?\s*(.{0,80}?)(?:се предоставя|предоставя|са предоставени|"
                  r"are granted|is granted|should|of the requested|на заявеното)", text, re.IGNORECASE)
    if not m:
        return set()
    return {int(n) for n in re.findall(r"\b\d{1,2}\b", m.group(1)) if 1 <= int(n) <= 39}


def parse_annex(text: str) -> list[Section]:
    sections: list[Section] = []
    current: Section | None = None
    # .docx cells end in "\r\x07", .doc cells in "\x07"; a row ends with one more "\x07".
    text = NAB_FOOTER.sub("\r", text.replace("\r\x07", "\x07"))
    for chunk in re.split(r"\x07\x07", text):
        cells = chunk.split("\x07")
        # Paragraph text before a table sits in front of the row's first cell.
        *paragraphs, cells[0] = cells[0].split("\r")
        if len(cells) == 1:          # no table here: the whole chunk is paragraphs
            paragraphs.append(cells[0])
            cells = []
        for para in map(clean, paragraphs):
            if std := detect_standard(para):
                current = Section(std, para)
                sections.append(current)
            elif current and CRITICAL.search(para):
                current.critical |= critical_codes(para)
        cells = [clean(c.replace("\r", " ")) for c in cells]
        if not current or not any(cells):
            continue
        if len(cells) == 1 and (std := detect_standard(cells[0])):
            current = Section(std, cells[0])
            sections.append(current)
            continue
        parse_row(current, cells)
    return sections


def parse_row(section: Section, cells: list[str]) -> None:
    if section.standard == "ISO 22000":
        for c in cells:
            if m := FOOD_CELL.fullmatch(c.translate(LOOKALIKES)):
                section.food.add(m.group(1))
        return
    if section.standard not in ("ISO 9001", "ISO 14001", "ISO 45001", "ISO 50001"):
        return
    cells = [re.sub(r"^З(?=\d)|(?<=\d)З$", "3", c) for c in cells]   # Cyrillic Ze read for a 3
    ints = [EA_CELL.fullmatch(c) for c in cells]
    # Column-number header row ("1 | 2 | 3", sometimes "2 | 3 | 4").
    numbers = [int(m.group(1)) for m in ints if m]
    if all(ints) and len(cells) > 1 and numbers == list(range(numbers[0], numbers[0] + len(cells))):
        return
    for i, m in enumerate(ints):
        if not m or not 1 <= int(m.group(1)) <= 39 or i + 1 >= len(cells):
            continue
        # 9001-type: EA | description | NACE; 50001: [no. | area |] EA | NACE | description.
        nace_cell = cells[i + 1] if is_nace_cell(cells[i + 1]) else (cells[i + 2] if i + 2 < len(cells) else "")
        if not is_nace_cell(nace_cell):
            continue
        add_row(section, int(m.group(1)), nace_cell, starred=bool(m.group(2)))
        return
    # 50001 continuation row with a blank IAF cell: "| 24 except 24.46, 25 except 25.4, 33.11 | ...".
    nace_cells = [c for c in cells if is_nace_cell(c)]
    if nace_cells and len(found := ea_of_nace(parse_nace(nace_cells[0]))) == 1:
        ea = found.pop()
        section.inferred[ea] = nace_cells[0]
        add_row(section, ea, nace_cells[0], starred=False)
        return
    # Anything else with a number in it, other than headers ("NACE rev. 2", "IAF №") and the
    # numbered first cell of a 50001 area ("1."), is reported.
    if any(re.search(r"\d", re.sub(r"rev\.?\s*2|ID\s*1", "", c)) for c in cells) \
            and not re.fullmatch(r"\d+\.", cells[0]):
        section.unparsed.append(" | ".join(cells))


def add_row(section: Section, ea: int, nace_cell: str, starred: bool) -> None:
    section.rows[ea] = section.rows.get(ea, []) + parse_nace(nace_cell)
    if regs := REGULATION.findall(nace_cell):
        section.regulations.setdefault(ea, set()).update(regs)
    if starred:
        section.critical.add(ea)


def merge_sections(sections: list[Section]) -> dict[str, Section]:
    merged: dict[str, Section] = {}
    for s in sections:
        if s.standard not in merged:
            merged[s.standard] = s
            continue
        m = merged[s.standard]
        for ea, items in s.rows.items():
            m.rows[ea] = m.rows.get(ea, []) + items
        m.food |= s.food
        m.critical |= s.critical
        m.unparsed += s.unparsed
    return merged


@dataclass
class Annex:
    entry_id: str
    language: str
    path: Path
    order: str            # "A 313", or "" when the header has no order number
    dated: str            # ISO date of the order, or "" when the header has none
    sections: dict[str, Section]

    def label(self) -> str:
        return f"{self.language.upper()} {self.order or 'order ?'} of {self.dated or 'no date'} (entry {self.entry_id})"


def read_annexes(folder: Path, entry_id: str) -> list[Annex]:
    annexes = []
    for path in sorted(folder.iterdir()):
        language = "bg" if path.name.startswith("ПЪЛЕН ОБХВАТ") else "en" if path.name.startswith("FULL SCOPE") else ""
        if not language or (entry_id, language) in NOT_A_SCOPE:
            continue
        text = read_text(path)
        head = re.sub(r"\s+", " ", text.replace("\x07", " ").replace("\r", " "))[:700]
        m = ORDER.search(head)
        annexes.append(Annex(entry_id, language, path, f"A {m[1]}" if m else "", iso(m[2]) if m else "",
                             merge_sections(parse_annex(text))))
    return annexes


# ------------------------------------------------------------------------------------ contacts
def normalise_phone(raw: str) -> str:
    first = re.split(r",|;", raw)[0]
    digits = re.sub(r"\D", "", first)
    if digits.startswith("359"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    if not 8 <= len(digits) <= 9:
        return ""
    if digits.startswith("2"):            # Sofia: 2 + 7 digits
        return f"+359 2 {digits[1:4]} {digits[4:]}"
    if digits[0] in "89" and len(digits) == 9:   # mobile
        return f"+359 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+359 {digits[:2]} {digits[2:5]} {digits[5:]}"  # other area codes (2-digit)


def pick_email(emails: list[str]) -> str:
    found = [e.strip() for raw in emails for e in re.split(r"[;,\s]+", raw) if "@" in e]
    generic = [e for e in found if re.match(r"(office|info|sgs_|exact|ctec)", e, re.IGNORECASE)]
    return (generic or found or [""])[0].lower()


# ----------------------------------------------------------------------------------------- run
def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def folder_of(bodies_dir: Path, body_id: str) -> Path:
    return next(bodies_dir.glob(f"*[[]{body_id}]"))


def describe(sections: dict[str, Section]) -> dict[str, str]:
    return {std: ea_spec(s.ea()) for std, s in sections.items()}


def run(args: argparse.Namespace) -> int:
    review = Review()
    entries = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in entries}
    bodies_dir = args.data / "bodies"

    bodies, accreditations, scopes = [], [], []
    for entry in entries:
        bid = entry["id"]
        if bid in MERGE:
            continue
        donors = [d for d, target in MERGE.items() if target == bid]
        contact_entry = entry if entry["offices"] else (by_id[donors[0]] if donors else entry)
        if donors:
            review.add("Withdrawn and merged entries",
                       f"{entry['certificate_number']} {entry['legal_entity']}: register entries {bid} "
                       f"(certificate {entry['valid_from']}-{entry['valid_to']}) and {donors[0]} "
                       f"(previous certificate, to {by_id[donors[0]]['valid_to']}) merged. Dates from {bid}, "
                       f"contacts from {contact_entry['id']}, scope from the newest annex of both")

        latin = LATIN_NAMES[bid]
        legal = clean(entry["legal_entity"])
        name = f"{latin} ({legal})"
        number = clean(entry["certificate_number"]).replace("OCC", "ОСС")
        if number != clean(entry["certificate_number"]):
            review.add("Contacts and names", f"{bid}: certificate number '{entry['certificate_number']}' "
                       f"typed in Latin letters; written as '{number}'")
        status = STATUSES[entry["status"]]
        if status != "ACTIVE":
            review.add("Withdrawn and merged entries", f"{number} {name}: register status "
                       f"'{entry['status']}' -> {status}; accreditation kept for the record, no scopes written")

        # Contacts.
        office = (contact_entry["offices"] or [{}])[0]
        phone_raw = next(iter(office.get("contacts", {}).values()), "")
        phone = normalise_phone(phone_raw)
        if phone_raw and not phone:
            review.add("Contacts and names", f"{name}: phone '{phone_raw}' is not a complete Bulgarian "
                       "number; left empty")
        email = pick_email(office.get("emails", []))
        if len(office.get("emails", [""])[0].split(";")) > 1:
            review.add("Contacts and names", f"{name}: register lists '{office['emails'][0]}'; kept {email}")
        city = CITIES.get(office.get("city", ""), "")
        address = ADDRESSES.get(bid) or ADDRESSES.get(contact_entry["id"]) or (f"{city}, Bulgaria" if city else "")
        if bid not in ADDRESSES:
            review.add("Contacts and names", f"{name}: annex gives no address; address is the register's "
                       f"office city ({address or 'none'})")
        bodies.append({
            "name": name, "country": COUNTRY, "registration_no": REGISTRATION_NOS.get(bid, ""),
            "phone": phone, "email": email, "website": "", "address": address,
            "source_url": entry["url_en"], "verified_at": "",
        })

        # Scope annexes: the newest order among the entry's (and a merged entry's) files; on
        # a tie the Bulgarian one. An annex whose header has no date is taken as issued with
        # the current certificate (its valid-from date).
        annexes = [a for e in [bid, *donors] for a in read_annexes(folder_of(bodies_dir, e), e)]
        for a in annexes:
            if not a.dated:
                a.dated = iso(by_id[a.entry_id]["valid_from"])
                review.add("Annex versions", f"{number} {name}: {a.language.upper()} annex has no order "
                           f"number or date in its header; taken as issued with the certificate ({a.dated})")
        if (bid, "bg") in NOT_A_SCOPE:
            review.add("Withdrawn and merged entries", f"{number} {name}: Bulgarian full-scope file is the "
                       "suspension order (A 504 of 27.12.2024), not a scope; the English annex was read")
        chosen = max(annexes, key=lambda a: (a.dated, a.language == "bg", a.entry_id == bid))
        sections = chosen.sections
        older = [a for a in annexes if a is not chosen and a.dated < chosen.dated]
        if older:
            review.add("Annex versions", f"{number} {name}: read {chosen.label()}; older: "
                       + ", ".join(a.label() for a in older))
        for twin in (a for a in annexes if a is not chosen and a.dated == chosen.dated):
            mine, theirs = describe(sections), describe(twin.sections)
            diffs = [f"{std}: {chosen.language.upper()} {mine.get(std, '(absent)') or 'no codes'} / "
                     f"{twin.language.upper()} {theirs.get(std, '(absent)') or 'no codes'}"
                     for std in dict.fromkeys([*mine, *theirs]) if mine.get(std) != theirs.get(std)]
            if diffs:
                review.add("Bulgarian and English annexes differ",
                           f"{number} {name}, {chosen.order} ({chosen.language.upper()} used): " + "; ".join(diffs))

        issue = iso(entry["initial_accreditation_date"]) or iso(entry["valid_from"])
        expiry = iso(entry["valid_to"])
        written: dict[str, tuple[str, str]] = {}
        for std, section in sections.items():
            if std in EXCLUDED_SCHEMES:
                review.add("Excluded schemes", f"{number} {name}: {EXCLUDED_SCHEMES[std]} — \"{section.heading[:140]}\"")
                continue
            accreditation_standard, suffix = SCHEMES.get(std, DEFAULT_SCHEME)
            cert = number + suffix
            for row in section.unparsed:
                review.add("Unparsed rows", f"{number} {std}: {row[:200]}")
            codes = section.ea()
            notes: list[str] = []
            if std in SECTOR_SCHEMES:
                if not codes:
                    review.add("Sections without codes", f"{number} {name} {std}: no sector codes found; no scope row")
                    continue
                spec = ea_spec(codes)
                limited = {ea: items for ea, items in section.rows.items()
                           if std != "ISO 50001" and is_limited(ea, items)}
                if limited:
                    notes.append("Limited scope (part of the sector): " + "; ".join(
                        f"EA {ea} (NACE {', '.join(map(str, items))})" for ea, items in sorted(limited.items())))
                    review.add("Limited scopes", f"{number} {std}: EA {ea_spec(set(limited))}")
                if std == "ISO 22000":
                    letters = ", ".join(sorted(section.food))
                    notes.append(f"ISO 22003-1 categories {letters} (classified to EA by sector)")
                    review.add("Draft EA mappings (check these)", f"{number} {name} ISO 22000: categories "
                               f"{letters} -> EA {spec}")
                if std == "ISO 50001":
                    notes.append("EA sectors from the IAF codes of the ISO 50003 technical-area table")
                for ea, nace in section.inferred.items():
                    review.add("Draft EA mappings (check these)", f"{number} {name} {std}: blank IAF cell, "
                               f"EA {ea} read from NACE '{nace}'")
                if section.regulations:
                    regs = sorted({r for rs in section.regulations.values() for r in rs})
                    notes.append(f"EA {ea_spec(set(section.regulations)).replace(';', ', ')} also cover Regulation (EU) "
                                 f"{', '.join(regs)} (end-of-waste criteria)")
                    review.add("Contacts and names", f"{number} {std}: NACE cells for EA "
                               f"{ea_spec(set(section.regulations))} cite Regulation (EU) {', '.join(regs)}; kept in the note")
                crit = section.critical & codes
                if crit:
                    notes.append(f"EA {ea_spec(crit).replace(';', ', ')} granted on condition of a witnessed audit before "
                                 "certification under accreditation")
                    review.add("Conditionally granted (critical) codes", f"{number} {std}: EA {ea_spec(crit)}")
            else:
                spec = "ALL"
                notes.append(ALL_NOTES[std])
                review.add("Annexes without a sector table (recorded as ALL)", f"{number} {name} {std}")
            written[cert] = (accreditation_standard, std)
            if status == "ACTIVE":
                scopes.append({"certificate_number": cert, "certification_standard": std, "ea_codes": spec,
                               "status": "ACTIVE", "scope_note": "; ".join(notes)})

        if "ISO/IEC 17021-1" not in {a for a, _ in written.values()}:
            review.add("Sections without codes", f"{number} {name}: no ISO 9001/14001/45001 section; "
                       "a 17021-1 row is still written so its other schemes stay searchable")
            written[number] = ("ISO/IEC 17021-1", "")
        for cert, (accreditation_standard, _) in written.items():
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
                "accreditation_standard": accreditation_standard, "status": status,
                "issue_date": issue, "expiry_date": expiry, "proof_url": entry["url_en"],
            })

    args.out.mkdir(parents=True, exist_ok=True)
    order = {"ISO 9001": 0, "ISO 14001": 1, "ISO 45001": 2}
    scopes.sort(key=lambda s: (s["certificate_number"].split()[0].zfill(3), s["certificate_number"],
                               order.get(s["certification_standard"], 9), s["certification_standard"]))
    accreditations.sort(key=lambda a: (a["certificate_number"].split()[0].zfill(3), a["certificate_number"]))
    bodies.sort(key=lambda b: b["name"].lower())
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, bodies)
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    # CertiFind keeps only bodies with a valid accreditation (database/prune_inactive.py).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from prune_inactive import prune
    for line in prune(args.out):
        print(f"removed (not valid): {line}")

    summary = [
        f"{len(bodies)} bodies, {len(accreditations)} accreditations, {len(scopes)} scope rows "
        f"from {len(entries)} register entries.",
        "Food-category-to-EA mappings are drafts (FOOD_CATEGORIES in prepare_certifind.py).",
    ]
    review.write(args.review, summary)
    print(summary[0])
    print(f"Wrote {args.out} and {args.review}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=here / "nab_management_system_bodies",
                        help="scraper output folder")
    parser.add_argument("--out", type=Path, required=True, help="dataset folder, e.g. certifind/data/bas-bulgaria")
    parser.add_argument("--review", type=Path, default=None, help="review file (default: <data>/REVIEW.md)")
    args = parser.parse_args(argv)
    args.review = args.review or args.data / "REVIEW.md"
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
