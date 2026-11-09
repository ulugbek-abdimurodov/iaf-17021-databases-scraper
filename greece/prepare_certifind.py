#!/usr/bin/env python3
"""Turn the ESYD scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads output/bodies.csv, output/accreditations.csv and the scope annexes downloaded with
`esyd_scraper.py --download-docs en`, and writes:

    <out>/bodies.csv, accreditations.csv, scopes.csv   in the CertiFind importer format
    <review>                                           everything a person should check

Each register row is one scheme ("field") of a body. Its annex gives the sector list, the
certificate number, the certificate's expiry date and the annex date. Nothing is guessed
silently: every normalised value, merge, category-to-EA mapping and fallback is listed in
the review file.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worddoc import read_text  # noqa: E402

AB_CODE = "ESYD"
DEFAULT_COUNTRY = "Greece"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Same checks as backend/.../importer/DatasetReader.java.
PHONE = re.compile(r"\+[0-9][0-9 ()/-]{5,}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
URL = re.compile(r"https?://\S+")

# Bodies that are the same organisation under two register entries: old id -> kept id.
# Delta Cert: the limited partnership (2024) and the single-member company (2025) run by the
# same owner in Heraklion, Crete; the company is the successor.
MERGE_BODIES = {"432090": "444089"}

# Register field -> certification standard. First match wins, so the specific patterns
# (FSSC before ISO 22000, 15224 before 9001, 50003 as energy) come first.
FIELD_PATTERNS = [
    ("FSSC 22000", r"FSSC 22000"),
    ("ISO 22000", r"ISO 22000"),
    ("EN 15224", r"15224"),
    ("ISO 9001", r"ISO 9001"),
    ("ISO 14001", r"ISO 14001"),
    ("ISO 45001", r"ISO 45001|OHSAS"),
    ("ISO 50001", r"ISO 5000[13]"),
    ("ISO/IEC 27001", r"27001"),
    ("ISO/IEC 20000-1", r"20000-1"),
    ("ISO 22301", r"22301"),
    ("ISO 37001", r"37001"),
    ("ISO 37301", r"37301"),
    ("ISO 39001", r"39001"),
    ("ISO 13485", r"13485"),
    ("ISO/IEC 42001", r"42001"),
    ("ISO 41001", r"41001"),
    ("ISO 55001", r"55001"),
    ("ISO 46001", r"46001"),
    ("ISO 21001", r"21001"),
    ("ISO 21401", r"21401"),
    ("ISO 29993", r"29993"),
    ("ISO 18295", r"18295"),
    ("ISO 3834", r"3834"),
    ("ELOT 1429", r"1429"),
    ("ELOT 1435", r"1435"),
    ("AGRO 2", r"AGRO 2"),
    ("EU Directives QA", r"E\.?C\.? DIRECTIVES"),
]

# Certification standard -> (accreditation standard, certificate suffix), as in the RENAR,
# DPA and TÜRKAK datasets. ESYD lists every scheme under one 17021 certificate.
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27017": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27018": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")

# Schemes left out of CertiFind: Greek national standards (ELOT, AGRO) and EU-directive
# notified-body modules, which are not management-system standards. They stay in
# FIELD_PATTERNS so their register rows are recognised and listed in the review file
# instead of being matched to another standard.
EXCLUDED_SCHEMES = {
    "ELOT 1429": "Greek national standard",
    "ELOT 1435": "Greek national standard",
    "AGRO 2": "Greek national scheme",
    "EU Directives QA": "EU-directive notified-body module, not a management-system standard",
}

# ---------------------------------------------------------------------------------------------
# DRAFT category -> EA mappings, the same tables as database/turkey/prepare_certifind.py
# (copied from how data/renar-romania and data/dpa-albania classified these categories).
# ---------------------------------------------------------------------------------------------

# ISO 50003:2021 technical areas, by the names ESYD prints.
ENERGY_AREAS = [
    ("A", ("industry – light", "industry - light", "industry light"), "3-9;12-14;18-19;22-24"),
    ("B", ("industry – heavy", "industry - heavy", "industry heavy"), "10;15-17;20-21;28;34"),
    ("D", ("building complex",), "30;32;36-39"),
    ("C", ("building",), "30;32;36-39"),
    ("E", ("transport",), "31"),
    ("F", ("mining",), "2"),
    ("G", ("agricultur",), "1"),
    ("H", ("energy supply",), "25-27"),
]

# ISO 22003-1:2022 food chain categories (FSSC 22000 uses the same letters).
FOOD_CATEGORIES = {
    "A": "1", "B": "1", "C": "3", "D": "3", "E": "30", "F": "29", "G": "31", "H": "35",
    "I": "7;14;15;17", "J": "18", "K": "12;13",
}

# ISO 13485 main technical areas (IAF MD 8), matched on the start of a table cell.
MEDICAL_AREAS = [
    ("Non-active medical devices", ("non-active", "non active"), "13;14;17"),
    ("Active implantable medical devices", ("active implantable",), "19"),
    ("Active (non-implantable) medical devices", ("active medical", "active (non", "active non"), "19"),
    ("In vitro diagnostic medical devices", ("in vitro",), "12;13;19"),
    ("Sterilization methods", ("steril",), "35"),
    ("Devices incorporating specific substances / technologies", ("devices incorporating",), "13"),
    ("Parts or services", ("parts",), "18;29;31;34;35"),
]

# EU directive / regulation annexes (notified-body quality-assurance modules), by product
# family. A family that is not listed here makes the annex fall back to ALL.
DIRECTIVE_FAMILIES = [
    ("pressure equipment", "17;18"),
    ("boiler", "17;18"),
    ("simple pressure vessel", "17;18"),
    ("transportable pressure", "17;18"),
    ("lift", "18"),
    ("machinery", "18"),
    ("gas appliance", "18"),
    ("appliances burning gaseous", "18"),
    ("medical device", "13;14;19"),
    ("in vitro", "12;13;19"),
    ("construction product", "15;16;17;28"),
    ("explosive atmosphere", "18;19"),
    ("radio equipment", "19"),
    ("measuring instrument", "19"),
    ("non-automatic weighing", "19"),
    ("recreational craft", "20"),
    ("marine equipment", "20"),
    ("personal protective", "4;5;14"),
    ("toy", "14;23"),
    ("cableway", "18"),
    ("railway", "22"),
    ("interoperability", "22"),
]

# NACE Rev. 2 -> EA, after the IAF ID 1 correspondence table. Some ISO 14001 / 45001 annexes
# list NACE codes instead of IAF codes. Keys are a division ("25"), group ("25.4") or class
# ("24.46"); the most specific key wins.
NACE_TO_EA = {
    **{d: 1 for d in ("01", "02", "03")},
    **{d: 2 for d in ("05", "06", "07", "08", "09")},
    **{d: 3 for d in ("10", "11", "12")},
    "13": 4, "14": 4, "15": 5, "16": 6, "17": 7, "18": 9, "58.1": 8, "19": 10, "24.46": 11,
    "20": 12, "21": 13, "22": 14, "23": 15, "23.5": 16, "23.6": 16,
    "24": 17, "25": 17, "33.11": 17,
    "25.4": 18, "28": 18, "30.4": 18, "33.12": 18,
    "26": 19, "27": 19, "33.13": 19, "33.14": 19, "95.1": 19,
    "30.1": 20, "33.15": 20, "30.3": 21, "33.16": 21,
    "29": 22, "30.2": 22, "30.9": 22, "33.17": 22,
    "31": 23, "32": 23, "33.19": 23, "33.2": 18,
    "38.3": 24, "35.1": 25, "35.2": 26, "35.3": 27, "36": 27,
    "41": 28, "42": 28, "43": 28,
    "45": 29, "46": 29, "47": 29, "95.2": 29,
    "55": 30, "56": 30,
    **{d: 31 for d in ("49", "50", "51", "52", "53", "61")},
    **{d: 32 for d in ("64", "65", "66", "68", "77")},
    "58.2": 33, "62": 33, "63": 33,
    "71": 34, "72": 34,
    **{d: 35 for d in ("69", "70", "73", "74", "78", "79", "80", "81", "82")},
    "84": 36, "85": 37, "75": 38, "86": 38, "87": 38, "88": 38,
    **{d: 39 for d in ("37", "38", "39", "59", "60", "90", "91", "92", "93", "94", "96")},
}

# NACE divisions and groups that IAF ID 1 splits over several EA sectors. Listed without a
# finer code, they map to every sector they touch, each marked as a limited scope.
NACE_SPANS = {
    "30": "18;20-22", "33": "17-23", "33.1": "17-23", "35": "25-27", "58": "8;33", "95": "19;29",
}

# Schemes whose annex normally lists sectors. When such an annex is missing, no scope row is
# written: recording ALL would make the body match sectors it may not hold.
SECTOR_SCHEMES = {"ISO 9001", "ISO 14001", "ISO 45001", "ISO 22000", "FSSC 22000", "ISO 50001",
                  "ISO 13485", "EU Directives QA"}

ALL_NOTE = "No sector list in annex; recorded for all EA sectors"

# Greek capitals that look like Latin ones, for matching codes and keywords in the annexes.
LOOKALIKES = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧοιν", "ABEZHIKMNOPTYXoiv")

DATE = r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})"
CERT_NO = re.compile(r"(?:Certificate|Πιστοποιητικ\w*)\s+(?:ESYD\s+|ΕΣΥΔ\s+)?(?:N[oο°]|Αρ)\.?\s*(\d+)(?:\s*[-/]\s*(\d+))?",
                     re.IGNORECASE)
VALID_UNTIL = re.compile(r"(?:valid|extended|παράτασης|ισχύει)\s+(?:up\s+to|until|till|up|μέχρι|έως)\s*(?:the\s*)?"
                         + DATE, re.IGNORECASE)
ANNEX_DATE = re.compile(r"(?:Athens|Αθήνα)\s*,\s*" + DATE)
REPLACES = re.compile(r"replaces the previous one,?\s*dated\s*" + DATE, re.IGNORECASE)


class Review:
    def __init__(self) -> None:
        self.sections: dict[str, list[str]] = defaultdict(list)

    def add(self, section: str, line: str) -> None:
        self.sections[section].append(line)

    def write(self, path: Path, summary: list[str]) -> None:
        order = ["Draft EA mappings (check these)", "Merged duplicates", "Annexes not read",
                 "Annexes without a sector table (recorded as ALL)", "Fallback dates and numbers",
                 "Bodies without scopes", "Excluded schemes", "Unmapped NACE codes", "Normalised values"]
        out = ["# ESYD dataset review", "", *summary, ""]
        for name in order + [s for s in self.sections if s not in order]:
            items = self.sections.get(name)
            if not items:
                continue
            out += [f"## {name} ({len(items)})", "", *[f"- {i}" for i in items], ""]
        path.write_text("\n".join(out), encoding="utf-8")


@dataclass
class Annex:
    """What one scope document says."""
    ea: set[int] = field(default_factory=set)
    limited: set[int] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    has_table: bool = False
    extra_standards: list[str] = field(default_factory=list)
    unmapped_nace: list[str] = field(default_factory=list)
    cert_no: str = ""
    valid_until: str = ""
    annex_date: str = ""


# --------------------------------------------------------------------------------- text helpers
def iso(d: str, m: str, y: str) -> str:
    return date(int(y), int(m), int(d)).isoformat()


def register_date(value: str) -> str:
    m = re.fullmatch(DATE, value.strip())
    return iso(*m.groups()) if m else ""


def cells(text: str) -> list[str]:
    """Table cells and paragraphs as a flat list of cleaned strings."""
    text = text.replace("\r\x07", "\x07")
    parts = re.split(r"[\x07\r]", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts]


def key(cell: str) -> str:
    return cell.translate(LOOKALIKES).lower()


def ea_spec(codes: set[int]) -> str:
    """{1,2,3,5} -> '1-3;5'."""
    parts, run = [], []
    for c in sorted(codes):
        if run and c == run[-1] + 1:
            run.append(c)
        else:
            if run:
                parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [c]
    if run:
        parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ";".join(parts)


def expand(spec: str) -> set[int]:
    codes: set[int] = set()
    for part in spec.split(";"):
        lo, _, hi = part.partition("-")
        codes.update(range(int(lo), int(hi or lo) + 1))
    return codes


# ------------------------------------------------------------------------------ annex parsing
def parse_annex(text: str, standard: str) -> Annex:
    annex = Annex()
    flat = re.sub(r"\s+", " ", text.replace("\x07", " ").replace("\r", " "))
    if m := CERT_NO.search(flat):
        annex.cert_no = m.group(1)
    if m := VALID_UNTIL.search(flat):
        annex.valid_until = iso(*m.groups())
    if m := ANNEX_DATE.search(flat):
        annex.annex_date = iso(*m.groups())

    # The table ends where the closing block ("Address of the Body ...") starts.
    end = re.search(r"Address of the Body|Διεύθυνση (?:του )?Φορέα", text)
    table = cells(text[:end.start()] if end else text)
    header_seen = any("iaf" in key(c) or "ea code" in key(c) or "κωδικός ea" in c.lower() for c in table)
    nace_seen = not header_seen and any("nace" in key(c) for c in table)

    if standard in ("ISO 22000", "FSSC 22000"):
        letters = []
        for c in table:
            m = re.fullmatch(r"([A-K])(?:[0IV]{1,4})?\.?", c.translate(LOOKALIKES))
            if m:
                letters.append(m.group(1))
        letters = sorted(set(letters))
        if letters:
            annex.has_table = True
            for letter in letters:
                annex.ea |= expand(FOOD_CATEGORIES[letter])
            annex.notes.append(f"ISO 22003-1 categories {', '.join(letters)} (classified to EA by sector)")
        return annex

    if standard == "ISO 50001":
        letters = []
        for c in table:
            k = key(c)
            for letter, prefixes, _ in ENERGY_AREAS:
                if k.startswith(prefixes) or re.fullmatch(letter.lower() + r"\.?", k):
                    letters.append(letter)
                    break
        letters = sorted(set(letters))
        if letters:
            annex.has_table = True
            for letter in letters:
                annex.ea |= expand(next(spec for l, _, spec in ENERGY_AREAS if l == letter))
            annex.notes.append(f"ISO 50003 technical areas {', '.join(letters)} (classified to EA by sector)")
        return annex

    if standard == "ISO 13485":
        areas = []
        for c in table:
            k = key(c)
            for name, prefixes, _ in MEDICAL_AREAS:
                if k.startswith(prefixes):
                    areas.append(name)
                    break
        areas = list(dict.fromkeys(areas))
        if areas:
            annex.has_table = True
            for area in areas:
                annex.ea |= expand(next(spec for n, _, spec in MEDICAL_AREAS if n == area))
            annex.notes.append(f"ISO 13485 main technical areas: {'; '.join(areas)} (classified to EA by sector)")
        return annex

    if standard == "EU Directives QA":
        low = key(flat)
        families = [(name, spec) for name, spec in DIRECTIVE_FAMILIES if name in low]
        directives = sorted(set(re.findall(r"(?:Directive|Regulation)\s*\(?(?:EU|EC|EEC)?\)?\s*(?:No\.?\s*)?(\d{2,4}/\d{2,4}(?:/E[UC]{1,2})?)", flat)))
        if directives:
            annex.notes.append("EU directives/regulations " + ", ".join(directives))
        if families:
            annex.has_table = True
            for _, spec in families:
                annex.ea |= expand(spec)
            annex.notes.append("Product families: " + ", ".join(n for n, _ in families)
                               + " (classified to EA by sector)")
        return annex

    if standard == "ISO/IEC 27001":
        for extra in ("27701", "27017", "27018"):
            if re.search(rf"ISO\s*/?\s*IEC\s*{extra}", flat):
                annex.extra_standards.append(f"ISO/IEC {extra}")

    # IAF / EA code table (9001, 14001, 45001, 22301, 15224, ...).
    if header_seen:
        current = None
        for c in table:
            m = re.fullmatch(r"(\d{1,2})\s*([a-zα-ω])?\.?", c.translate(LOOKALIKES))
            if m and 1 <= int(m.group(1)) <= 39:
                current = int(m.group(1))
                annex.ea.add(current)
                annex.has_table = True
                continue
            if current is not None and c.lower() in ("limited", "μερικό", "μερικο", "περιορισμένο"):
                annex.limited.add(current)
    elif nace_seen:
        for c in table:
            m = re.match(r"(\d{2})(?:\.(\d{1,2}))?(?![\d.])", c)
            if not m:
                continue
            division, sub = m.group(1), m.group(2) or ""
            ea = (NACE_TO_EA.get(f"{division}.{sub}") or NACE_TO_EA.get(f"{division}.{sub[:1]}")
                  or NACE_TO_EA.get(division)) if sub else NACE_TO_EA.get(division)
            if ea is None:
                span = NACE_SPANS.get(f"{division}.{sub}" if sub else division)
                if span is None:
                    annex.unmapped_nace.append(m.group(0))
                    continue
                annex.ea |= expand(span)
                annex.limited |= expand(span)
                annex.has_table = True
                continue
            annex.ea.add(ea)
            annex.has_table = True
            if sub or "except" in c.lower() or "εκτός" in c.lower():
                annex.limited.add(ea)
        if annex.has_table:
            annex.notes.append("Annex lists NACE codes; classified to EA with the IAF ID 1 table")
    if annex.limited:
        annex.notes.append("Limited scope (part of the sector) for EA " + ea_spec(annex.limited).replace(";", ", "))
    return annex


# --------------------------------------------------------------------------- body clean-up
def classify(field_name: str) -> str | None:
    probe = field_name.translate(LOOKALIKES)
    for standard, pattern in FIELD_PATTERNS:
        if re.search(pattern, probe, re.IGNORECASE):
            return standard
    return None


def clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip()
    n = re.sub(r"\(\s+", "(", n)
    n = re.sub(r"\s+\)", ")", n)
    # "X (PPC INSPECTRA) (PPC INSPECTRA)" -> "X (PPC INSPECTRA)"
    n = re.sub(r"(\([^()]+\))(?:\s*\1)+", r"\1", n)
    return n


def country_of(body: dict) -> str:
    where = f"{body['address']} {body['city']}".lower()
    if any(w in where for w in ("cyprus", "nicosia", "limassol", "paphos", "latsia", "larnaca")):
        return "Cyprus"
    if any(w in where for w in ("malta", "valletta")):
        return "Malta"
    return DEFAULT_COUNTRY


DIAL = {"Greece": ("30", 10), "Cyprus": ("357", 8), "Malta": ("356", 8)}
# Country code -> national number length, for numbers written with the code but no "+".
NATIONAL_LENGTH = {"30": 10, "357": 8, "356": 8, "40": 9}


def normalise_phone(raw: str, country: str) -> str:
    first = re.split(r"[,;]|\s-\s", raw.strip())[0]
    first = re.sub(r"[^\d+\- ]", " ", first).strip()   # drops names and notes after the number
    first = re.split(r"\s{2,}", first)[0]
    prefix, length = DIAL[country]
    if "-" in first:
        before, after = first.split("-", 1)
        b, a = re.sub(r"\D", "", before), re.sub(r"\D", "", after)
        first = before if len(b) >= length or len(a) <= 3 else before + after
    plus = first.startswith("+")
    digits = re.sub(r"\D", "", first)
    if not digits:
        return ""
    if plus:
        return re.sub(r"\s+", " ", first).strip()
    if digits.startswith("00"):
        digits = digits[2:]
        for code, national in NATIONAL_LENGTH.items():
            if digits.startswith(code) and len(digits) == len(code) + national:
                return f"+{code} {digits[len(code):]}"
        return "+" + digits
    for code, national in NATIONAL_LENGTH.items():
        if digits.startswith(code) and len(digits) == len(code) + national:
            return f"+{code} {digits[len(code):]}"
    if len(digits) == length:
        return f"+{prefix} {digits}"
    return ""


FREE_MAIL = ("gmail.", "yahoo.", "hotmail.", "outlook.", "otenet.gr")


def normalise_email(raw: str) -> str:
    """One address: info@ first, then the company's own domain, then the first listed."""
    found = [p.lower() for p in re.split(r"[,;\s]+", raw.strip()) if EMAIL.fullmatch(p)]
    if not found:
        return ""
    for pick in (lambda e: e.startswith(("info@", "office@")),
                 lambda e: not any(f in e.split("@")[1] for f in FREE_MAIL)):
        for email in found:
            if pick(email):
                return email
    return found[0]


def normalise_website(raw: str) -> str:
    v = raw.strip()
    if not v or not re.search(r"[a-z]\.[a-z]", v, re.IGNORECASE) or "esyd.gr" in v:
        return ""
    if not re.match(r"https?://", v, re.IGNORECASE):
        v = "https://" + v
    return v


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def doc_path(docs: Path, body_id: str, url: str) -> Path | None:
    if not url:
        return None
    for folder in docs.glob(f"{body_id}_*"):
        p = folder / url.rsplit("/", 1)[-1]
        if p.is_file() and p.stat().st_size:
            return p
    return None


def download_greek(docs: Path, rows: list[dict]) -> None:
    """Fetch the Greek annex for every row whose English one is missing (the site 404s some)."""
    session = requests.Session()
    session.headers["User-Agent"] = "esyd-17021-scraper/1.0 (accredited body register export)"
    for row in rows:
        if doc_path(docs, row["body_id"], row["scope_doc_en"]) or not row["scope_doc_el"]:
            continue
        if doc_path(docs, row["body_id"], row["scope_doc_el"]):
            continue
        folder = next(docs.glob(f"{row['body_id']}_*"), None) or docs / row["body_id"]
        folder.mkdir(parents=True, exist_ok=True)
        try:
            resp = session.get(row["scope_doc_el"], timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"greek annex failed {row['scope_doc_el']}: {exc}", flush=True)
            continue
        (folder / row["scope_doc_el"].rsplit("/", 1)[-1]).write_bytes(resp.content)
        print(f"downloaded {row['scope_doc_el']}", flush=True)
        time.sleep(0.3)


# ------------------------------------------------------------------------------------- run
def run(args: argparse.Namespace) -> int:
    data: Path = args.data
    docs = data / "scope_documents"
    with open(data / "bodies.csv", encoding="utf-8-sig", newline="") as fh:
        raw_bodies = {b["body_id"]: b for b in csv.DictReader(fh)}
    with open(data / "accreditations.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if args.download_el:
        download_greek(docs, rows)

    review = Review()

    # Merge duplicate bodies -------------------------------------------------------------------
    for old, kept in MERGE_BODIES.items():
        if old in raw_bodies and kept in raw_bodies:
            o, k = raw_bodies.pop(old), raw_bodies[kept]
            for column in ("address", "city", "region", "telephone", "fax", "email", "website"):
                if not k[column] and o[column]:
                    k[column] = o[column]
            review.add("Merged duplicates", f"body {old} `{o['name']}` merged into {kept} `{k['name']}` "
                       "(same owner and brand; contact details filled from the older entry)")
            for row in rows:
                if row["body_id"] == old:
                    row["body_id"] = kept

    # Read every annex, group by (body, certification standard) -------------------------------
    per_body: dict[str, dict[str, dict]] = defaultdict(dict)
    body_meta: dict[str, dict] = defaultdict(lambda: {"cert": Counter(), "valid": Counter(),
                                                      "since": [], "annex_dates": []})
    for row in rows:
        bid = row["body_id"]
        name = clean_name(raw_bodies[bid]["name"])
        standard = classify(row["field"])
        meta = body_meta[bid]
        if row["certificate_number"]:
            meta["cert"][row["certificate_number"].split("-")[0]] += 1
        since = register_date(row["valid_since"])
        if since:
            meta["since"].append(since)
        if standard is None:
            review.add("Annexes not read", f"{bid} {name}: field `{row['field']}` matches no known standard")
            continue
        if standard in EXCLUDED_SCHEMES:
            review.add("Excluded schemes", f"{bid} {name} {standard}: {EXCLUDED_SCHEMES[standard]}")
            continue

        path = doc_path(docs, bid, row["scope_doc_en"]) or doc_path(docs, bid, row["scope_doc_el"])
        annex = Annex()
        if path is None:
            outcome = ("no scope row written (sector scheme)" if standard in SECTOR_SCHEMES
                       else "recorded as ALL")
            review.add("Annexes not read", f"{bid} {name} {standard}: annex not on the ESYD site in English "
                       f"or Greek ({row['scope_doc_en']}); {outcome}")
        else:
            try:
                annex = parse_annex(read_text(path), standard)
            except Exception as exc:  # a broken file should not stop the other 388
                review.add("Annexes not read", f"{bid} {name} {standard}: {path.name} unreadable ({exc}); recorded as ALL")
        if annex.unmapped_nace and annex.has_table:
            review.add("Unmapped NACE codes", f"{bid} {name} {standard}: "
                       f"{', '.join(dict.fromkeys(annex.unmapped_nace))} not in NACE_TO_EA; left out")
        if annex.cert_no:
            meta["cert"][annex.cert_no] += 2       # the annex outranks the register's number
        if annex.valid_until:
            meta["valid"][annex.valid_until] += 1
        if annex.annex_date:
            meta["annex_dates"].append(annex.annex_date)

        entry = per_body[bid].setdefault(standard, {"ea": set(), "notes": [], "all": False,
                                                    "since": [], "docs": 0})
        if entry["docs"]:
            review.add("Merged duplicates", f"{bid} {name}: second register row for {standard} "
                       f"(`{row['field'][:70]}`); sectors combined")
        entry["docs"] += 1
        if since:
            entry["since"].append(since)
        entry["notes"] += annex.notes
        if annex.has_table and annex.ea:
            entry["ea"] |= annex.ea
            mapped = [n for n in annex.notes if "classified to EA" in n]
            if mapped:
                review.add("Draft EA mappings (check these)", f"{bid} {name} {standard}: {mapped[0]}")
        elif path is not None:
            entry["all"] = True
            review.add("Annexes without a sector table (recorded as ALL)", f"{bid} {name} {standard} ({path.name})")
        elif standard not in SECTOR_SCHEMES:
            entry["all"] = True
        for extra in annex.extra_standards:
            per_body[bid].setdefault(extra, {"ea": set(), "notes": [f"Listed in the ISO/IEC 27001 annex ({path.name})"],
                                             "all": True, "since": list(entry["since"]), "docs": 1})

    # Build the dataset ----------------------------------------------------------------------
    bodies, accreditations, scopes = [], [], []
    for bid, raw in raw_bodies.items():
        name = clean_name(raw["name"])
        if name != re.sub(r"\s+", " ", raw["name"]).strip():
            review.add("Normalised values", f"{bid} name `{raw['name']}` -> `{name}`")
        country = country_of(raw)
        phone = normalise_phone(raw["telephone"], country)
        email = normalise_email(raw["email"]) or normalise_email(raw["fax"])
        website = normalise_website(raw["website"])
        for column, before, after in (("phone", raw["telephone"], phone), ("email", raw["email"], email),
                                      ("website", raw["website"], website)):
            if before.strip() != after:
                review.add("Normalised values", f"{bid} {column} `{before}` -> `{after or '(empty)'}`")
        address = raw["address"].strip()
        city = raw["city"].strip()
        if city and re.split(r"[,\s]+", city)[0].lower() not in address.lower():
            address = f"{address}, {city}" if address else city
        bodies.append({"name": name, "country": country, "registration_no": "", "phone": phone,
                       "email": email, "website": website, "address": address,
                       "source_url": raw["detail_url"], "verified_at": ""})

        meta = body_meta[bid]
        if meta["cert"]:
            cert = meta["cert"].most_common(1)[0][0]
        else:
            cert = f"ESYD-{bid}"
            review.add("Fallback dates and numbers", f"{bid} {name}: no certificate number in the register "
                       f"or the annexes; using `{cert}`")
        # Annexes are reissued one by one, so older ones still carry the previous expiry date.
        expiry = max(meta["valid"]) if meta["valid"] else ""
        if len(meta["valid"]) > 1:
            review.add("Fallback dates and numbers", f"{bid} {name}: annexes give several expiry dates "
                       f"{dict(meta['valid'])}; using the latest, {expiry}")
        if expiry and expiry < args.today:
            review.add("Fallback dates and numbers", f"{bid} {name}: latest expiry in the annexes is {expiry}, "
                       "in the past, while ESYD still lists the body; treated as expired and removed")
            # Kept as written: an expired accreditation is not searchable, so prune_inactive drops it.
        elif not expiry:
            review.add("Fallback dates and numbers", f"{bid} {name}: no expiry date in the annexes; left empty")

        standards = per_body.get(bid, {})
        if not standards:
            review.add("Bodies without scopes", f"{bid} {name}: no convertible scheme; body only")
            continue

        by_accreditation: dict[str, tuple[str, list[str]]] = {}
        for standard, entry in sorted(standards.items()):
            accreditation_standard, suffix = SCHEMES.get(standard, DEFAULT_SCHEME)
            number = cert + suffix
            _, dates = by_accreditation.setdefault(number, (accreditation_standard, []))
            dates += entry["since"]
            if not entry["all"] and not entry["ea"]:
                continue   # sector scheme whose annex is missing; listed under "Annexes not read"
            if entry["all"] and not entry["ea"]:
                spec, notes = "ALL", [ALL_NOTE, *entry["notes"]]
            else:
                spec, notes = ("ALL" if len(entry["ea"]) == 39 else ea_spec(entry["ea"])), entry["notes"]
                if entry["all"]:
                    notes = [*notes, "One of the merged annexes had no sector list"]
            scopes.append({"certificate_number": number, "certification_standard": standard,
                           "ea_codes": spec, "status": "ACTIVE",
                           "scope_note": "; ".join(dict.fromkeys(notes))})

        all_dates = meta["since"] or meta["annex_dates"]
        for number, (accreditation_standard, dates) in by_accreditation.items():
            issue = min(dates) if dates else (min(all_dates) if all_dates else "")
            if not dates:
                review.add("Fallback dates and numbers", f"{bid} {name} {number}: no register date for these "
                           f"schemes; issue_date {issue or '(none)'} taken from "
                           f"{'other schemes of the body' if meta['since'] else 'the annex date'}")
            if not issue:
                continue
            expiry_date = expiry if expiry and expiry >= issue else ""
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                "accreditation_standard": accreditation_standard, "status": "ACTIVE",
                "issue_date": issue, "expiry_date": expiry_date, "proof_url": raw["detail_url"],
            })

    known = {a["certificate_number"] for a in accreditations}
    dropped = [s for s in scopes if s["certificate_number"] not in known]
    for s in dropped:
        review.add("Fallback dates and numbers", f"scope {s['certificate_number']} {s['certification_standard']} "
                   "dropped: its accreditation has no date")
    scopes = [s for s in scopes if s["certificate_number"] in known]
    # A body with no accreditation has nothing to search for; keep it out of the directory.
    accredited = {a["body_name"] for a in accreditations}
    for b in bodies:
        if b["name"] not in accredited:
            review.add("Bodies without scopes", f"{b['name']}: no dated accreditation; body not written")
    bodies = [b for b in bodies if b["name"] in accredited]

    args.out.mkdir(parents=True, exist_ok=True)
    scopes.sort(key=lambda s: (s["certificate_number"], s["certification_standard"]))
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
        f"from {len(rows)} register rows.",
        "Category-to-EA mappings are drafts; see ENERGY_AREAS, FOOD_CATEGORIES, MEDICAL_AREAS and "
        "DIRECTIVE_FAMILIES in prepare_certifind.py.",
    ]
    review.write(args.review, summary)
    print(summary[0])
    print(f"Wrote {args.out} and {args.review}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=here / "output", help="scraper output folder")
    parser.add_argument("--out", type=Path, required=True, help="dataset folder, e.g. certifind/data/esyd-greece")
    parser.add_argument("--review", type=Path, default=None, help="review file (default: <data>/REVIEW.md)")
    parser.add_argument("--download-el", action="store_true",
                        help="first download the Greek annex of rows whose English one is missing")
    parser.add_argument("--today", default=date.today().isoformat(),
                        help="expiry dates before this day are treated as stale (default: today)")
    args = parser.parse_args(argv)
    args.review = args.review or args.data / "REVIEW.md"
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
