#!/usr/bin/env python3
"""Convert armnab_scraper.py output into a CertiFind importer dataset.

Writes bodies.csv, accreditations.csv and scopes.csv to
../../certifind/data/armnab-armenia/ and output/REVIEW.md. Nothing is imported.

NACE_TO_EA, NACE_SPANS, FOOD_CATEGORIES, ENERGY_AREAS, MEDICAL_AREAS, EXCLUDED_SCHEMES,
SCHEMES and SECTOR_SCHEMES are loaded from ../greece/prepare_certifind.py, not copied, so
every dataset classifies categories and splits accreditations the same way.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
AB_CODE = "ARMNAB"
ACCREDITATION_STANDARD = "ISO/IEC 17021-1"
EA_SEPARATOR = ";"
ALL_CODES = "ALL"
TABLE_NAMES = ("NACE_TO_EA", "NACE_SPANS", "FOOD_CATEGORIES", "ENERGY_AREAS",
               "MEDICAL_AREAS", "EXCLUDED_SCHEMES", "SCHEMES", "SECTOR_SCHEMES")
COUNTRY = "Armenia"
ALL_NOTE = "No sector list on the register; recorded for all EA sectors"
ALL_SECTIONS_NOTE = "All NACE sections listed on the register; recorded for all EA sectors"

STATUS_MAP = {"Գործող": "ACTIVE", "Կասեցված": "SUSPENDED", "Դադարեցված": "WITHDRAWN"}

# Accreditation standard per certification standard, on top of the Greek SCHEMES table. The
# register names each one as the scheme's "additional accreditation standard"
# (լրացուցիչ հավատարմագրման ստանդարտ).
SCHEME_OVERRIDES = {
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 28000": ("ISO 28003", " (28000)"),
    "ISO 20121": ("ISO/IEC 17021-4", " (20121)"),
}
# Standards CertiFind does not carry. Rows for them are listed in REVIEW.md, not written.
UNSUPPORTED_STANDARDS = {"OHSAS 18001": "withdrawn standard, replaced by ISO 45001"}

# English names, translated from the Armenian legal names (the register is Armenian only).
# Keyed by the quoted part of the name, upper case.
ENGLISH_NAMES = {
    "ՆԱՐԵԿ": "Narek Scientific Research CJSC",
    "ԻՆՍՏՐՈՒԿՏԱՐԻՈՒՄ": "Instruktarium LLC",
    "ՏԵՍՏՍՎՅԱԶ": "Testsvyaz LLC",
    "ՍՏԱՆԴԱՐՏԱՑՄԱՆ ԵՎ ՉԱՓԱԳԻՏՈՒԹՅԱՆ ԱԶԳԱՅԻՆ ՄԱՐՄԻՆ": "National Body of Standards and Metrology CJSC",
    "ՍԵՐՏԻՖԻԿԱՑՈՒՄ ԵՎ ՈՐԱԿ": "Certification and Quality LLC",
    "ԳԵՐՄԱՆԱԿԱՆ ՍԵՐՏԻՖԻԿԱՑՄԱՆ ՄԱՐՄԻՆ": "German Certification Body LLC",
    "ՍՄԱՐԹԹՐԱՆՍ": "Smarttrans LLC",
    "ՍՏԱՆԴԱՐՏՆԵՐԻ ԱԶԳԱՅԻՆ ԻՆՍՏԻՏՈՒՏ": "National Institute of Standards CJSC",
}

# "Աղյուսակ Ա.1.n" rows of the ISO 13485 scope, by n, as named in the Greek MEDICAL_AREAS.
MEDICAL_TABLES = {
    "1": "Non-active medical devices", "2": "Active (non-implantable) medical devices",
    "3": "Active implantable medical devices", "4": "In vitro diagnostic medical devices",
    "5": "Sterilization methods", "6": "Devices incorporating specific substances / technologies",
    "7": "Parts or services",
}
# Older FSSC 22000 scopes use the ISO/TS 22003:2007 letters: C perishable animal products,
# D perishable plant products, E ambient-stable products, L (bio)chemicals, M packaging.
# Each is mapped to the ISO 22003-1:2022 letter that covers it.
FSSC_LEGACY = {"C": "C", "D": "C", "E": "C", "L": "K", "M": "I"}
FSSC_LEGACY_MARKERS = ("Շուտ փչացող", "կայուն արտադրանքի")
SCOPE_BLOCK = "Հավատարմագրման ոլորտը"
EXTENSION_BLOCK = "Ոլորտի ընդլայնում"
REDUCTION_BLOCK = "Ոլորտի կրճատում"
CHANGES_LABEL = "Փոփոխությունները"

# Certifiable schemes this register uses. Anything else is logged, never written.
STANDARDS = {"9001": "ISO 9001", "14001": "ISO 14001", "22000": "ISO 22000",
             "27001": "ISO/IEC 27001", "45001": "ISO 45001", "18001": "OHSAS 18001",
             "50001": "ISO 50001", "22301": "ISO 22301", "28000": "ISO 28000",
             "13485": "ISO 13485", "7101": "ISO 7101", "20000": "ISO/IEC 20000-1", "20121": "ISO 20121",
             "21001": "ISO 21001", "30301": "ISO 30301", "30401": "ISO 30401", "37001": "ISO 37001",
             "37101": "ISO 37101", "37301": "ISO 37301", "41001": "ISO 41001", "55001": "ISO 55001",
             "56001": "ISO 56001"}
FSSC = "FSSC 22000"
FOOD_STANDARDS = {"ISO 22000", FSSC}
HEADING_KEYWORDS = [
    ("FSSC", FSSC), ("Որակի", "ISO 9001"), ("Շրջակա միջավայրի", "ISO 14001"),
    ("Էկոլոգիական", "ISO 14001"), ("Սննդամթերքի անվտանգության", "ISO 22000"),
    ("Տեղեկատվական անվտանգության", "ISO/IEC 27001"), ("Էներգետիկայի", "ISO 50001"),
    ("Բիզնեսի շարունակականության", "ISO 22301"), ("Մատակարարման շղթայի", "ISO 28000"),
    ("Բժշկական սարքեր", "ISO 13485"), ("առողջության և աշխատանքի", "ISO 45001"),
    ("Աշխատանքի անվտանգության", "ISO 45001"),
]
# Letter in legacy certificate numbers such as 003/E-004.
CERT_LETTERS = {"Q": ["ISO 9001"], "E": ["ISO 14001"], "F": ["ISO 22000", FSSC],
                "L": ["ISO/IEC 27001"], "H": ["OHSAS 18001"]}

EA_ORDER = [str(n) for n in range(1, 17)] + ["17", "17.1", "17.2"]
EA_ORDER += [str(n) for n in range(18, 29)] + ["29", "29/1", "29/2", "30", "31", "31/1", "31/2",
                                                "32", "32/1", "32/2", "33", "34", "34/1", "34/2",
                                                "35", "36", "37", "38", "38/1", "38/2", "38/3", "39"]
ALL_SECTIONS = set("ABCDEFGHIJKLMNOPQRSTU")
SECTION_DIVISIONS = {"A": (1, 3), "B": (5, 9), "C": (10, 33), "D": (35, 35), "E": (36, 39),
                     "F": (41, 43), "G": (45, 47), "H": (49, 53), "I": (55, 56), "J": (58, 63),
                     "K": (64, 66), "L": (68, 68), "M": (69, 75), "N": (77, 82), "O": (84, 84),
                     "P": (85, 85), "Q": (86, 88), "R": (90, 93), "S": (94, 96), "T": (97, 98),
                     "U": (99, 99)}

# Older records number the NACE sections by name, with no letter or EA code.
SECTION_NAMES = [("գյուղատնտեսություն", "A"), ("հանքագործական", "B"), ("մշակող արդյունաբերություն", "C"),
                 ("էլեկտրականության", "D"), ("ջրամատակարարում", "E"), ("շինարարություն", "F"),
                 ("մեծածախ", "G"), ("փոխադրումներ", "H"), ("կացության", "I"), ("տեղեկատվություն", "J"),
                 ("ֆինանսական", "K"), ("անշարժ գույք", "L"), ("մասնագիտական", "M"), ("վարչարարական", "N"),
                 ("պետական կառավարում", "O"), ("կրթություն", "P"), ("առողջապահություն", "Q"),
                 ("մշակույթ", "R"), ("սպասարկման այլ", "S"), ("տնային տնտեսությունների", "T"),
                 ("օտարերկրյա", "U")]
NUMBERED_ROW = re.compile(r"^\d+[.․]?\s+(.+)$")

SKIP_LINE = re.compile(r"^(որպես|Որպես|լրացուցիչ|Ծանոթություն|\(?հավատարմագրման վկայագրի|Հ/հ|ոլորտը դասակարգչի|"
                       r"Օբյեկտի անվանումը|Կատեգորիաների նկարագրությունը|IAF/EA|-+$)")
HEADING_RE = re.compile(r"կառավա\w*\s+համակարգ|Բժշկական սարքեր\.")
REDUCTION_RE = re.compile(r"կրճատվել է.*?՝\s*(.+)$")
LINE_CERT_RE = re.compile(r"\d{3}/[A-Z]-\d{3}")
TRAILING_STANDARD = re.compile(r"\s+Հ?\s?ՍՏ\s.*$|\s+(?:ԳՕՍՏ|ГОСТ)\s.*$")
EA_ROW = re.compile(r"\S\s+(\d{1,2}(?:[./]\d{1,2})?)\.?\s*(?:Բաժին\s*)?"
                    r"(?:[A-U](?:\s*,\s*[A-U])*)?\s*(?:\d{2}\.\d{1,2}(?:\.\d+)?)?\s*$")
SECTION_ROW = re.compile(r"(?:\s-+\s*|\s|,\s*)(?:Բաժին\s*)?([A-U])\s*(\d{2}\.\d+)?\s*$")
FOOD_WITH_SECTION = re.compile(r"\s([A-M])\s+Բաժին\s*[A-U](?:\s*,\s*[A-U])*\s*$")
ONLY_SECTION = re.compile(r"Բաժին\s*[A-U]\s*$")
FOOD_ROW = re.compile(r"\s([A-M])(?:\s+[A-U]|\s*-+)?\s*$")
ENERGY_ROW = re.compile(r"\s([A-H])\s*$")
MEDICAL_ROW = re.compile(r"Աղյուսակ\s*Ա?\.?\s*1\.(\d)")


def to_latin(text: str) -> str:
    text = text.replace("․", ".")
    for armenian, latin in (("ԻՍՕ", "ISO"), ("ԻՍO", "ISO"), ("ԻԷԿ", "IEC"), ("ՕՀՍԱՍ", "OHSAS"),
                            ("ԳՕՍՏ", "GOST"), ("ГОСТ", "GOST"), ("ИСО", "ISO"), ("ՀՍՏ", "AST"), ("ՏՍ", "TS")):
        text = text.replace(armenian, latin)
    return text


def standard_numbers(text: str) -> list[str]:
    return re.findall(r"(?:ISO(?:/IEC)?(?:/TS)?|OHSAS)\s*(\d{4,5})", to_latin(text))


def resolve_heading(line: str) -> tuple[str | None, list[str]]:
    """Return (standard, other standards named on the same line)."""
    if "FSSC" in line:
        return FSSC, []
    numbers = standard_numbers(line)
    for position, number in enumerate(numbers):
        if number in STANDARDS:
            others = numbers[:position] + numbers[position + 1:]
            return STANDARDS[number], [n for n in others if not n.startswith(("170", "2200"))]
    for keyword, standard in HEADING_KEYWORDS:
        if keyword in line:
            return standard, []
    return None, numbers


def expand_reduction(text: str) -> tuple[set[str], list[str]]:
    """Parse "6, 8-ից մինչև 11, 15-17.2, 29/1-30" into codes, plus tokens it can't read.

    A reduction can also name letters ("ԲԱԺԻՆՆԵՐ C, G", "Բաժին T"): NACE sections for
    sector schemes, technical areas for ISO 50001. They are returned as the bare letter.
    """
    codes: set[str] = set()
    unread: list[str] = []
    text = re.sub(r"\s*-?ից\s+մինչև\s+", "-", text.rstrip(" ։:."))
    for token in re.split(r"\s*,\s*", text):
        token = re.sub(r"^(?:ԲԱԺԻՆՆԵՐ|Բաժիններ|Բաժին|ԲԱԺԻՆ)\s*", "", token.strip())
        if re.fullmatch(r"[A-U]", token):
            codes.add(token)
            continue
        match = re.fullmatch(r"([\d./]+)\s*-\s*([\d./]+)", token)
        if match and match[1] in EA_ORDER and match[2] in EA_ORDER:
            start, end = EA_ORDER.index(match[1]), EA_ORDER.index(match[2])
            selected = EA_ORDER[start:end + 1]
            codes.update(selected)
            # A range ending on a parent code covers its sub-codes.
            codes.update(code for code in EA_ORDER if re.split(r"[./]", code)[0] == match[2])
        elif token in EA_ORDER:
            codes.add(token)
            codes.update(code for code in EA_ORDER if re.split(r"[./]", code)[0] == token)
        elif token:
            unread.append(token)
    return codes, unread


def new_scheme(standard: str) -> dict:
    return {"standard": standard, "codes": [], "sections": [], "nace": [], "food": [], "energy": [],
            "medical": [], "certs": [], "removed": set(), "extras": [], "reduction_notes": 0, "wrapped_lines": 0,
            "legacy_food": False}


def parse_scope(lines: list[str], review_lines: list[str] | None = None) -> dict[str, dict]:
    """Split register text into schemes and their sector rows. Unread lines are collected."""
    schemes: dict[str, dict] = {}
    current: dict | None = None
    unparsed = review_lines if review_lines is not None else []
    index = 0
    pending: list[str] = []  # lines with no code yet; a coded next line means they were wrapped

    def flush_pending() -> None:
        unparsed.extend(pending)
        pending.clear()

    def start(standard: str) -> dict:
        return schemes.setdefault(standard, new_scheme(standard))

    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue

        certs = LINE_CERT_RE.findall(line)
        if certs and current is not None and "գրանցահամար" in line:
            current["certs"].extend(certs)
            continue

        reduction = REDUCTION_RE.search(line)
        if "կրճատվել է" in line and "՝" in line:
            # A decision ends with "։" or ":"; until then it is wrapped over several lines.
            while not re.search(r"[։:]\s*$", line) and "։" not in line and index < len(lines):
                line += " " + lines[index].strip()
                index += 1
            reduction = REDUCTION_RE.search(line)
            if reduction and current is not None:
                removed, unread = expand_reduction(reduction[1])
                current["removed"] |= removed
                current["reduction_notes"] += 1
                unparsed.extend(f"reduction token not read: {token}" for token in unread)
            else:
                unparsed.append(line)
            continue
        if line.startswith("Համաձայն") or "ընդլայնվել է" in line or SKIP_LINE.match(line):
            continue

        latin = to_latin(line)
        if HEADING_RE.search(line) and not EA_ROW.search(TRAILING_STANDARD.sub("", line)):
            flush_pending()
            standard, others = resolve_heading(line)
            if (current is not None and not has_rows(current) and not re.match(r"\d", line)
                    and not standard_numbers(line)):
                # An unnumbered subtitle under a heading (the standard's own title), not a new scheme.
                continue
            if standard is None:
                # Some headings only name the scheme; its standard is on the next line.
                following = standard_numbers(lines[index]) if index < len(lines) else []
                if not (following and following[0] in STANDARDS):
                    unparsed.append(f"scheme not recognised: {line}")
                current = None
                continue
            current = start(standard)
            current["certs"].extend(LINE_CERT_RE.findall(line))
            current["extras"].extend(others)
            continue

        row = TRAILING_STANDARD.sub("", line)
        bare = standard_numbers(row)  # a standard after the code is a table column, not a heading
        is_bare_standard = bool(bare) and not EA_ROW.search(row)
        if is_bare_standard or re.search(r"HACCP|CAC/", latin):
            number = next(iter(bare), "")
            known = STANDARDS.get(number)
            if known and (current is None or (current["standard"] != known and has_rows(current))):
                current = start(known)
            elif current is not None and (not known or current["standard"] != known):
                current["extras"].append(line)
            elif current is None:
                unparsed.append(f"standard outside any scheme: {line}")
            continue

        if current is None:
            unparsed.append(f"row outside any scheme: {line}")
            continue
        if read_row(current, row):
            current["wrapped_lines"] += len(pending)
            pending.clear()
        else:
            pending.append(f"{current['standard']}: {line}")
    flush_pending()
    return schemes


def has_rows(scheme: dict) -> bool:
    return any(scheme[key] for key in ("codes", "sections", "nace", "food", "energy", "medical"))


def read_row(scheme: dict, row: str) -> bool:
    standard = scheme["standard"]
    if standard in FOOD_STANDARDS:
        match = FOOD_WITH_SECTION.search(row)
        if not match and not ONLY_SECTION.search(row):
            match = FOOD_ROW.search(row)
        if match:
            scheme["food"].append(match[1])
            if standard == FSSC and (match[1] in "LM" or any(m in row for m in FSSC_LEGACY_MARKERS)):
                scheme["legacy_food"] = True
            return True
        return False
    if standard == "ISO 50001":
        if (match := ENERGY_ROW.search(row)) is None:
            return False
        letter = match[1]
        # The site lists A/B (industrial split) and then the A-H technical areas.
        if scheme["energy"] and letter <= scheme["energy"][-1]:
            scheme["energy"].clear()
        scheme["energy"].append(letter)
        return True
    if standard == "ISO 13485":
        if (match := MEDICAL_ROW.search(row)) is None:
            return False
        scheme["medical"].append(f"A.1.{match[1]}")
        return True
    match = EA_ROW.search(row)
    if match and match[1] in EA_ORDER:
        scheme["codes"].append(match[1])
        return True
    match = SECTION_ROW.search(row)
    if match:
        scheme["nace"].append(match[2]) if match[2] else scheme["sections"].append(match[1])
        return True
    match = NUMBERED_ROW.match(row)
    if match:
        text = match[1].lower()
        for name, letter in SECTION_NAMES:
            if text.startswith(name):
                scheme["sections"].append(letter)
                return True
    return False


def clean_phone(raw: str, address: str, review: "Review", where: str) -> str:
    """Return the first number as "+374 AA NNNNNN" (two-digit area or operator code)."""
    if not raw:
        return ""
    parts = [part for part in re.split(r"[,;/]", raw) if part.strip()]
    if len(parts) > 1:
        review.add("Cleaned values", f"{where}: phone `{raw}` has several numbers, kept the first")
    digits = re.sub(r"\D", "", parts[0])
    if digits.startswith("374") and len(digits) == 11:
        national = digits[3:]
    elif digits.startswith("0") and len(digits) == 9:
        national = digits[1:]
    elif len(digits) == 8:
        national = digits
    elif len(digits) == 6 and "Երևան" in address:
        national = "10" + digits
        review.add("Fallbacks", f"{where}: phone `{raw}` has no area code; added Yerevan 10 from the address")
    else:
        review.add("Fallbacks", f"{where}: phone `{raw}` could not be converted; left blank")
        return ""
    result = f"+374 {national[:2]} {national[2:]}"
    if result != raw:
        review.add("Cleaned values", f"{where}: phone `{raw}` -> `{result}`")
    return result


def short_name(title: str, review: "Review", where: str) -> str:
    match = re.match(r"^(«[^»]+»(?:\s+[^\s-]+)*?\s*(?:ՍՊԸ|ՓԲԸ))", title)
    if match:
        name = re.sub(r"\s+", " ", match[1])
        if name != title:
            review.add("Cleaned values", f"{where}: name `{title}` -> `{name}`")
        return name
    review.add("Fallbacks", f"{where}: no legal form found, kept the full title `{title}`")
    return title


def name_key(title: str) -> str:
    quoted = re.search(r"«([^»]+)»", title)
    return re.sub(r"\s+", " ", quoted[1] if quoted else title).strip().upper()


def display_name(armenian: str, review: "Review", where: str) -> str:
    """"English (Armenian)", like the other datasets' "Latin (local)" names."""
    english = ENGLISH_NAMES.get(name_key(armenian))
    if english is None:
        review.add("Fallbacks", f"{where}: no English name in ENGLISH_NAMES for `{armenian}`; Armenian only")
        return armenian
    return f"{english} ({armenian})"


def load_tables(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Greece converter not found at {path}. Pass --greece.")
    spec = importlib.util.spec_from_file_location("greece_prepare_certifind", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [name for name in TABLE_NAMES if not hasattr(module, name)]
    if missing:
        raise SystemExit(f"{path} does not define: {', '.join(missing)}")
    return {name: getattr(module, name) for name in TABLE_NAMES}


def expand_ea_spec(spec) -> set[int]:
    """Turn 18, "18" or "18;20-22" into {18, 20, 21, 22}."""
    codes: set[int] = set()
    for part in str(spec).split(";"):
        part = part.strip()
        if part:
            low, _, high = part.partition("-")
            codes.update(range(int(low), int(high or low) + 1))
    return codes


def ea_spec(codes: set[int]) -> str:
    """{1, 2, 3, 5} -> "1-3;5", the importer's format."""
    parts, run = [], []
    for code in sorted(codes):
        if run and code == run[-1] + 1:
            run.append(code)
            continue
        if run:
            parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [code]
    if run:
        parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ";".join(parts)


# Register sub-sectors ("17.1", "29/1", ...) by their EA sector.
SUB_CODES: dict[str, list[str]] = defaultdict(list)
for _code in EA_ORDER:
    if not _code.isdigit():
        SUB_CODES[re.split(r"[./]", _code)[0]].append(_code)


def nace_section(code: str) -> str:
    division = int(code.split(".")[0])
    return next((letter for letter, (low, high) in SECTION_DIVISIONS.items() if low <= division <= high), "")


def base_code(code: str) -> int:
    return int(re.split(r"[./]", code)[0])


def apply_reduction(codes: list[str], removed: set[str]) -> tuple[list[str], list[str]]:
    """Drop reduced codes. A listed sector whose sub-sector was reduced keeps its other sub-sectors."""
    kept: list[str] = []
    for code in codes:
        if code in removed:
            continue
        subs = SUB_CODES.get(code, [])
        replacement = [s for s in subs if s not in removed] if any(s in removed for s in subs) else [code]
        kept.extend(c for c in replacement if c not in kept)
    return kept, [code for code in codes if code in removed]


def to_ea(codes: list[str]) -> tuple[set[int], dict[int, list[str]]]:
    """Collapse register codes to EA sectors, and name the sectors held only in part."""
    whole = {int(code) for code in codes if code.isdigit()}
    parts: dict[int, list[str]] = defaultdict(list)
    for code in codes:
        if not code.isdigit() and base_code(code) not in whole:
            parts[base_code(code)].append(code)
    partial = {sector: subs for sector, subs in parts.items() if set(subs) != set(SUB_CODES[str(sector)])}
    return whole | set(parts), partial


class Mapper:
    """Looks codes up in the Greek tables. Each failed lookup goes to REVIEW.md."""

    def __init__(self, tables: dict):
        self.tables = tables
        self.energy = {letter: spec for letter, _names, spec in tables["ENERGY_AREAS"]}
        self.medical = {name: spec for name, _keys, spec in tables["MEDICAL_AREAS"]}
        self.schemes = {**tables["SCHEMES"], **SCHEME_OVERRIDES}

    def nace(self, code: str) -> set[int]:
        parts = code.split(".")
        candidates = [code, f"{parts[0]}.{parts[1][:1]}" if len(parts) > 1 else code, parts[0],
                      parts[0].lstrip("0")]
        for table in ("NACE_TO_EA", "NACE_SPANS"):
            for candidate in candidates:
                if candidate in self.tables[table]:
                    return expand_ea_spec(self.tables[table][candidate])
        return set()

    def section(self, letter: str) -> set[int]:
        low, high = SECTION_DIVISIONS[letter]
        found: set[int] = set()
        for division in range(low, high + 1):
            found |= self.nace(f"{division:02d}")
        return found

    def food(self, letter: str, legacy: bool) -> set[int]:
        current = FSSC_LEGACY.get(letter) if legacy else letter
        spec = self.tables["FOOD_CATEGORIES"].get(current) if current else None
        return expand_ea_spec(spec) if spec else set()

    def energy_area(self, letter: str) -> set[int]:
        return expand_ea_spec(self.energy[letter]) if letter in self.energy else set()

    def medical_area(self, number: str) -> tuple[str, set[int]]:
        name = MEDICAL_TABLES.get(number, "")
        return name, expand_ea_spec(self.medical[name]) if name in self.medical else set()

    def accreditation(self, standard: str) -> tuple[str, str]:
        return self.schemes.get(standard, (ACCREDITATION_STANDARD, ""))


class Review:
    def __init__(self):
        self.sections: dict[str, list[str]] = defaultdict(list)

    def add(self, section: str, message: str) -> None:
        if message not in self.sections[section]:
            self.sections[section].append(message)

    def write(self, path: Path, summary: list[str]) -> None:
        order = ["Decisions to confirm", "Mappings", "Exclusions", "Fallbacks", "Cleaned values",
                 "Unread scope lines", "Additional documents named in scopes", "Missing annexes"]
        lines = ["# ARMNAB dataset review", "", *summary, ""]
        for section in order:
            items = self.sections.get(section, [])
            lines += [f"## {section} ({len(items)})", ""]
            lines += [f"- {item}" for item in items] or ["- none"]
            lines.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")


def block_lines(record: dict, title: str, label: str | None = None) -> list[str]:
    lines: list[str] = []
    for block in record["blocks"]:
        if block["title"] != title:
            continue
        for entry in block["entries"]:
            if label is None or entry["label"] == label:
                lines.extend(entry["lines"])
    return lines


def record_schemes(record: dict, review: Review, where: str) -> dict[str, dict]:
    unread: list[str] = []
    main = parse_scope(block_lines(record, SCOPE_BLOCK), unread)
    extension = parse_scope(block_lines(record, EXTENSION_BLOCK), unread)
    for standard, scheme in extension.items():
        target = main.setdefault(standard, new_scheme(standard))
        for key in ("codes", "sections", "nace", "food", "energy", "medical", "certs", "extras"):
            target[key].extend(scheme[key])
        target["removed"] |= scheme["removed"]
        target["legacy_food"] |= scheme["legacy_food"]
        review.add("Mappings", f"{where}: merged extension block rows into {standard}")
    reductions = parse_scope(block_lines(record, REDUCTION_BLOCK, CHANGES_LABEL), [])
    for standard, scheme in reductions.items():
        if standard in main:
            main[standard]["removed"] |= set(scheme["codes"])
    for line in unread:
        review.add("Unread scope lines", f"{where}: {line}")
    return main


def category_codes(where: str, keys: list[str], lookup, label: str, review: Review) -> tuple[set[int], list[str]]:
    codes: set[int] = set()
    used: list[str] = []
    for key in dict.fromkeys(keys):
        mapped = lookup(key)
        if not mapped:
            review.add("Fallbacks", f"{where}: {label} `{key}` has no EA mapping; left out")
            continue
        codes |= mapped
        used.append(key)
        review.add("Mappings", f"{where}: {label} {key} -> {ea_spec(mapped)}")
    return codes, used


def scheme_codes(record_id: str, scheme: dict, mapper: Mapper, review: Review) -> tuple[str | None, str]:
    """Return (EA spec or None to leave the row out, scope note)."""
    where = f"{record_id} {scheme['standard']}"
    standard = scheme["standard"]
    if scheme["wrapped_lines"]:
        review.add("Cleaned values", f"{where}: {scheme['wrapped_lines']} wrapped line(s) joined to the coded row after them")
    for extra in scheme["extras"]:
        review.add("Additional documents named in scopes", f"{where}: `{extra}` not written as a scope")
    if not has_rows(scheme):
        if standard in mapper.tables["SECTOR_SCHEMES"]:
            review.add("Fallbacks", f"{where}: no sector rows on the register for a sector scheme; row left out")
            return None, ""
        review.add("Mappings", f"{where}: no sector list on the register -> ALL")
        return ALL_CODES, ALL_NOTE

    notes: list[str] = []
    if standard in FOOD_STANDARDS:
        legacy = scheme["legacy_food"]
        codes, used = category_codes(where, scheme["food"], lambda key: mapper.food(key, legacy),
                                     "food category", review)
        if used:
            numbering = "FSSC 22000 categories (ISO/TS 22003:2007 letters)" if legacy else "ISO 22003-1 categories"
            notes.append(f"{numbering} {', '.join(used)} (classified to EA by sector)")
    elif standard == "ISO 50001":
        removed = [letter for letter in dict.fromkeys(scheme["energy"]) if letter in scheme["removed"]]
        kept = [letter for letter in scheme["energy"] if letter not in scheme["removed"]]
        codes, used = category_codes(where, kept, mapper.energy_area, "technical area", review)
        if used:
            notes.append(f"ISO 50003 technical areas {', '.join(used)} (classified to EA by sector)")
        if removed:
            notes.append(f"Scope reduced by ARMNAB: technical areas {', '.join(removed)} removed")
            review.add("Mappings", f"{where}: technical areas removed by reduction: {', '.join(removed)}")
    elif standard == "ISO 13485":
        numbers = [key.rsplit(".", 1)[-1] for key in scheme["medical"]]
        codes, used = category_codes(where, numbers, lambda n: mapper.medical_area(n)[1], "table A.1.", review)
        if used:
            names = "; ".join(mapper.medical_area(n)[0] for n in used)
            notes.append(f"ISO 13485 main technical areas: {names} (classified to EA by sector)")
    else:
        removed_sections = {code for code in scheme["removed"] if code.isalpha()}
        sections = set(scheme["sections"]) - removed_sections
        nace_codes = [code for code in dict.fromkeys(scheme["nace"])
                      if nace_section(code) not in removed_sections]
        # Sections T and U (households, extraterritorial bodies) have no EA sector, so a list
        # of A-S, or a reduction of only T and U, still covers every EA sector.
        if sections >= ALL_SECTIONS - {"T", "U"} and scheme["removed"] <= {"T", "U"}:
            review.add("Mappings", f"{where}: all NACE sections listed -> {ALL_CODES}")
            return ALL_CODES, ALL_SECTIONS_NOTE
        listed, dropped = apply_reduction(list(dict.fromkeys(scheme["codes"])), scheme["removed"])
        dropped_sections = sorted(removed_sections & (set(scheme["sections"])
                                                      | {nace_section(code) for code in scheme["nace"]}))
        codes, partial = to_ea(listed)
        mapped: set[int] = set()
        for letter in sorted(sections):
            found = mapper.section(letter)
            if not found:
                review.add("Fallbacks", f"{where}: NACE section {letter} has no EA mapping; left out")
            review.add("Mappings", f"{where}: section {letter} -> {ea_spec(found) or 'nothing'}")
            mapped |= found
        for nace in nace_codes:
            found = mapper.nace(nace)
            if not found:
                review.add("Fallbacks", f"{where}: NACE {nace} has no EA mapping; left out")
            review.add("Mappings", f"{where}: NACE {nace} -> {ea_spec(found) or 'nothing'}")
            mapped |= found
        reduced = {int(code) for code in scheme["removed"] if code.isdigit()}
        dropped += [str(code) for code in sorted(mapped & reduced - codes) if str(code) not in dropped]
        codes |= mapped - reduced
        if sections or nace_codes:
            listed_as = ", ".join(sorted(sections) + nace_codes)
            notes.append(f"Register lists NACE {listed_as}; classified to EA with the IAF ID 1 table")
        if dropped_sections:
            notes.append(f"Scope reduced by ARMNAB: NACE sections {', '.join(dropped_sections)} removed")
            review.add("Mappings", f"{where}: sections removed by reduction: {', '.join(dropped_sections)}")
        if partial:
            notes.append("Part of the sector (ARMNAB sub-sectors): "
                         + "; ".join(f"EA {sector} ({', '.join(subs)})" for sector, subs in sorted(partial.items())))
        if dropped:
            notes.append(f"Scope reduced by ARMNAB: {', '.join(dropped)} removed")
            review.add("Mappings", f"{where}: removed by reduction: {', '.join(dropped)}")
    if scheme["reduction_notes"] and standard in FOOD_STANDARDS | {"ISO 13485"}:
        review.add("Fallbacks", f"{where}: reduction note on a category scheme was not applied")
    if not codes:
        review.add("Fallbacks", f"{where}: no EA code left after mapping; row left out")
        return None, ""
    return ea_spec(codes), "; ".join(notes)


def assign_certificates(record: dict, schemes: dict[str, dict], review: Review) -> dict[str, list[str]]:
    """Return certificate number -> standards."""
    numbers = record["certificate_numbers"]
    where = record["detail_id"]
    result: dict[str, list[str]] = {number: [] for number in numbers}
    if len(numbers) == 1:
        result[numbers[0]] = list(schemes)
        return result
    for standard, scheme in schemes.items():
        named = [cert for cert in scheme["certs"] if cert in result]
        if named:
            result[named[0]].append(standard)
            continue
        by_letter = [number for number in numbers
                     if standard in CERT_LETTERS.get(number.split("/")[1][0], [])]
        if by_letter:
            result[by_letter[0]].append(standard)
            review.add("Fallbacks", f"{where}: {standard} assigned to {by_letter[0]} from its letter")
        else:
            review.add("Fallbacks", f"{where}: {standard} matches no certificate number; left out")
    for number in numbers:
        if not result[number]:
            standards = [standard for standard in CERT_LETTERS.get(number.split("/")[1][0], [])
                         if standard not in schemes][:1]
            if standards:
                schemes[standards[0]] = new_scheme(standards[0])
                result[number] = standards
                review.add("Fallbacks", f"{where}: {number} has no scope section; "
                                        f"{standards[0]} inferred from its letter")
            else:
                review.add("Fallbacks", f"{where}: {number} has unknown letter and no scope section")
    return result


def is_excluded(standard: str, excluded) -> bool:
    return any(str(item).lower() in standard.lower() for item in excluded)


def convert(data: dict, tables: dict, retrieved: str, active_only: bool = True):
    """Return bodies, accreditations, scopes, review and a count of scope rows per standard.

    Terminated records are left out by default: CertiFind allows one accreditation per body,
    accreditation body and accreditation standard (uq_cb_ab_standard), and ARMNAB keeps each
    renewal (and older per-scheme numbers) as a separate record, so the history cannot be
    imported next to the current accreditation.
    """
    review = Review()
    mapper = Mapper(tables)
    bodies, accreditations, scopes = [], [], []
    records = sorted(data["records"], key=lambda record: record["start_date"], reverse=True)
    body_names: dict[str, str] = {}
    written_bodies: dict[str, dict] = {}
    standards_used: dict[str, int] = defaultdict(int)

    for record in records:
        where = record["detail_id"]
        status = STATUS_MAP.get(record["status"])
        if status is None:
            review.add("Fallbacks", f"{where}: unknown status `{record['status']}`; record skipped")
            continue
        if active_only and status != "ACTIVE":
            review.add("Exclusions", f"{where}: {status} record {', '.join(record['certificate_numbers'])} "
                                     f"({record['start_date']} to {record['end_date']}) left out")
            continue
        key = name_key(record["name"])
        if key not in body_names:
            body_names[key] = display_name(short_name(record["name"], review, where), review, where)
        name = body_names[key]
        if status == "ACTIVE" and record["end_date"] and record["end_date"] < retrieved:
            review.add("Decisions to confirm", f"{where}: marked active but ended {record['end_date']}")

        schemes = record_schemes(record, review, where)
        for number, standards in assign_certificates(record, schemes, review).items():
            groups: dict[tuple[str, str], list[dict]] = {}
            for standard in standards:
                if is_excluded(standard, tables["EXCLUDED_SCHEMES"]):
                    review.add("Exclusions", f"{where}: {standard} is in EXCLUDED_SCHEMES")
                    continue
                if standard in UNSUPPORTED_STANDARDS:
                    review.add("Exclusions", f"{where} {number}: {standard} left out "
                                             f"({UNSUPPORTED_STANDARDS[standard]})")
                    continue
                spec, note = scheme_codes(where, schemes[standard], mapper, review)
                if spec is None:
                    continue
                groups.setdefault(mapper.accreditation(standard), []).append(
                    {"certification_standard": standard, "ea_codes": spec, "status": status, "scope_note": note})
            if not groups:
                review.add("Exclusions", f"{where}: {number} has no scope that can be written; "
                                         "accreditation left out")
                continue
            for (accreditation_standard, suffix), rows in groups.items():
                # One row per accreditation standard, numbered like the other datasets: the
                # ISO/IEC 17021-1 row keeps the ARMNAB number, the others add a suffix.
                certificate = number
                if len(groups) > 1 and accreditation_standard != ACCREDITATION_STANDARD:
                    certificate = f"{number}{suffix}"
                accreditations.append({
                    "ab_code": AB_CODE, "certificate_number": certificate, "body_name": name,
                    "accreditation_standard": accreditation_standard, "status": status,
                    "issue_date": record["start_date"], "expiry_date": record["end_date"],
                    "proof_url": record["source_url"]})
                for row in rows:
                    scopes.append({"certificate_number": certificate, **row})
                    standards_used[row["certification_standard"]] += 1
        if key not in written_bodies:
            address = record["legal_address"] or record["activity_address"]
            if not any(region in address for region in ("Երևան", "ՀՀ", "Կոտայք", "Արարատ", "Արմավիր",
                                                          "Արագածոտն", "Գեղարքունիք", "Լոռի", "Շիրակ",
                                                          "Սյունիք", "Տավուշ", "Վայոց Ձոր")):
                review.add("Decisions to confirm", f"{where}: address `{address}` names no Armenian region")
            written_bodies[key] = {
                "name": name, "country": COUNTRY, "registration_no": "",
                "phone": clean_phone(record["phone"], address, review, where),
                "email": record["email"], "website": "", "address": address,
                "source_url": record["source_url"], "verified_at": ""}
        if not record["documents"]:
            review.add("Missing annexes", f"{where}: no annex or certificate file; scope read from the page")

    with_accreditation = {row["body_name"] for row in accreditations}
    for body in written_bodies.values():
        if body["name"] in with_accreditation:
            bodies.append(body)
        else:
            review.add("Exclusions", f"{body['name']}: no accreditation left, body not written")
    review.add("Decisions to confirm", f"Records before 2015 are written under {ACCREDITATION_STANDARD}; "
                                       "they may have been granted under ISO/IEC 17021:2011")
    review.add("Decisions to confirm", "English names are translations of the Armenian legal names "
                                       "(ENGLISH_NAMES); the register has no English version")
    return bodies, accreditations, scopes, review, dict(standards_used)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=HERE / "output")
    parser.add_argument("--dataset", type=Path, default=HERE / "../../certifind/data/armnab-armenia")
    parser.add_argument("--greece", type=Path, default=HERE / "../greece/prepare_certifind.py")
    parser.add_argument("--include-withdrawn", action="store_true",
                        help="also write terminated records (for review; the importer rejects "
                             "several accreditations per body and accreditation standard)")
    args = parser.parse_args()

    data = json.loads((args.input / "bodies.json").read_text(encoding="utf-8"))
    report_path = args.input / "run_report.json"
    retrieved = date.today().isoformat()
    if report_path.exists():
        retrieved = json.loads(report_path.read_text(encoding="utf-8"))["finished_at"][:10]

    bodies, accreditations, scopes, review, used = convert(
        data, load_tables(args.greece), retrieved, active_only=not args.include_withdrawn)
    write_csv(args.dataset / "bodies.csv", ["name", "country", "registration_no", "phone", "email",
                                            "website", "address", "source_url", "verified_at"], bodies)
    write_csv(args.dataset / "accreditations.csv",
              ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
               "issue_date", "expiry_date", "proof_url"], accreditations)
    write_csv(args.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes",
                                            "status", "scope_note"], scopes)
    summary = [f"- Retrieved: {retrieved}", f"- Bodies: {len(bodies)}",
               f"- Accreditations: {len(accreditations)}", f"- Scope rows: {len(scopes)}",
               "- Standards used: " + ", ".join(f"{k} ({v})" for k, v in sorted(used.items()))]
    review.write(args.input / "REVIEW.md", summary)
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
