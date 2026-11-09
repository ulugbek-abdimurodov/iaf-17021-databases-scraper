#!/usr/bin/env python3
"""Convert the SNAS (Slovenská národná akreditačná služba, Slovakia) management-system scrape
into a CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by snas_scraper.py (certificates.csv, files.csv and the
"Rozsah akreditácie" annex PDFs). SNAS issues one certificate of accreditation per field
(Q-xxx / R-xxx), each with its own validity and annex. The annex lists, per field:
EA codes with their NACE codes (ISO 9001 / 14001 / 45001 / 3834), ISO 22003-1 food chain
categories (ISO 22000, FSSC 22000), ISO 50003 technical areas (ISO 50001) or IAF MD 8
technical areas (ISO 13485). Rows marked "*" are areas in which the body may not issue
accredited certificates; they are left out.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Needs pdftotext (poppler) on PATH. Open points are written to snas_review.md next to this
script; prune_inactive.prune() then drops everything that is not currently valid.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date
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

AB_CODE = "SNAS"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
SOURCE_URL = "https://ais.snas.sk/web-report"
ALL_NOTE = "No sector list in the SNAS annex; recorded for all EA sectors"

# SNAS accreditation field id -> (certification standard, kind of sector list).
FIELDS = {
    "12": ("ISO 9001", "ea"), "16": ("ISO 14001", "ea"), "17": ("ISO 45001", "ea"),
    "13": ("ISO 3834", "ea"),
    "15": ("ISO 13485", "medical"),
    "19": ("ISO 22000", "food"), "37": ("FSSC 22000", "food"),
    "20": ("ISO 50001", "energy"),
    "18": ("ISO/IEC 27001", "all"), "33": ("ISO 37001", "all"), "34": ("ISO 22301", "all"),
    "35": ("ISO/IEC 20000-1", "all"), "53": ("ISO 21001", "all"), "54": ("ISO 39001", "all"),
}
# Fields CertiFind has no standard for (Slovak national schemes).
SKIPPED_FIELDS = {
    "14": "sustainable forest management (TD SFCS 1002/1003, the Slovak PEFC scheme)",
    "36": "management systems of contractors of designated construction work "
          "(Act No. 25/2025 Coll., Slovak national scheme)",
}
# Certification standard -> accreditation standard; everything else is under ISO/IEC 17021-1.
SCHEME_ROWS = {
    "ISO 22000": "ISO 22003-1", "FSSC 22000": "ISO 22003-1",
    "ISO 50001": "ISO 50003",
    "ISO/IEC 27001": "ISO/IEC 27006",
    "ISO/IEC 20000-1": "ISO/IEC 20000-6",
    "ISO 22301": "ISO/IEC 17021-6",
    "ISO 37001": "ISO/IEC 17021-9",
    "ISO 39001": "ISO/IEC 17021-7",
}
# Marked EA codes ("*" / "**") are left out, except these, whose footnote limits the sector
# instead of excluding it.
BASE_METALS = "no accredited certificates for production of basic metals (SNAS annex footnote)"
LIMITS = {
    ("R-004", 31): "no accredited certificates for transport, storage and communication of "
                   "dangerous goods (SNAS annex footnote)",
    ("R-078", 17): BASE_METALS, ("R-158", 17): BASE_METALS, ("R-165", 17): BASE_METALS,
    ("R-166", 17): BASE_METALS, ("R-167", 17): BASE_METALS,
    # Marked "**" without a footnote; the same mark means base metals in the other annexes.
    ("R-091", 17): "marked ** in the SNAS annex without a footnote (elsewhere: no accredited "
                   "certificates for production of basic metals)",
}
WHY_EXCLUDED = {
    "Q-005": "no accredited certificates until SNAS has carried out a witness assessment",
    "R-060": "the SNAS annex marks EA 17 both as excluded (*) and as limited to production of "
             "basic metals (**); left out",
}
PRIMARY_ORDER = ("ISO 9001", "ISO 14001", "ISO 45001", "ISO 22000", "ISO 50001",
                 "ISO/IEC 27001", "ISO 37001")

# NACE Rev. 2 -> EA (IAF ID 1). A shorter key stands for the part of the division no finer
# key claims. SNAS annexes use NACE Rev. 2, where 38.3 (materials recovery) is EA 24.
NACE_TO_EA = {
    **{d: 1 for d in ("01", "02", "03")},
    **{d: 2 for d in ("05", "06", "07", "08", "09")},
    **{d: 3 for d in ("10", "11", "12")},
    "13": 4, "14": 4, "15": 5, "16": 6, "17": 7, "58": 8, "18": 9, "19": 10, "24.46": 11,
    "20": 12, "21": 13, "22": 14, "23": 15, "23.5": 16, "23.6": 16, "24": 17, "25": 17,
    "25.4": 18, "28": 18, "26": 19, "27": 19, "29": 22, "31": 23, "32": 23,
    "30.1": 20, "30.2": 22, "30.3": 21, "30.4": 18, "30.9": 22,
    "33.11": 17, "33.12": 18, "33.13": 19, "33.14": 19, "33.15": 20, "33.16": 21, "33.17": 22,
    "33.19": 23, "33.2": 18, "35.1": 25, "35.2": 26, "35.3": 27, "36": 27,
    "37": 39, "38.1": 39, "38.2": 39, "38.3": 24, "39": 39, "41": 28, "42": 28, "43": 28,
    "45": 29, "46": 29, "47": 29, "55": 30, "56": 30,
    **{d: 31 for d in ("49", "50", "51", "52", "53", "61")},
    **{d: 32 for d in ("64", "65", "66", "68", "77")},
    "62": 33, "63": 33, "71": 34, "72": 34,
    **{d: 35 for d in ("69", "70", "73", "74", "78", "79", "80", "81", "82")},
    "84": 36, "85": 37, "75": 38, "86": 38, "87": 38, "88": 38,
    **{d: 39 for d in ("59", "60", "90", "91", "92", "93", "94", "95.2", "96")},
    "59.2": 8, "95.1": 19,
}
NACE_TOKEN = re.compile(r"^\d{2}(?:\.\d{1,2})?$")

ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL_AREAS = {1: "Non-active medical devices", 2: "Active (non-implantable) medical devices",
                 3: "Active implantable medical devices", 4: "In vitro diagnostic medical devices",
                 5: "Sterilization methods",
                 6: "Devices incorporating specific substances / technologies",
                 7: "Parts or services"}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}

TABLE_END = re.compile(r"Pracoviská certifikačného|Workplaces of|Premises of|Sites of|"
                       r"^\s*\*{3}\s*$", re.M)
TABLE_START = re.compile(r"Identifikačné číslo akreditovanej osoby|Identification number", re.I)


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def ea_of(code: str) -> int | None:
    while code and code not in NACE_TO_EA:
        code = code[:-1].rstrip(".")
    return NACE_TO_EA.get(code)


def ea_spec(codes: set[int]) -> str:
    if set(range(1, 40)) <= codes:
        return "ALL"
    out, run = [], []
    for c in sorted(codes):
        if run and c == run[-1] + 1:
            run.append(c)
        else:
            if run:
                out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [c]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ";".join(out)


def pdf_text(pdf: Path) -> str | None:
    out = subprocess.run([PDFTOTEXT, "-enc", "UTF-8", "-layout", str(pdf), "-"], capture_output=True)
    if out.returncode:
        return None
    return out.stdout.decode("utf-8", "replace")


def table_text(text: str) -> str:
    """The scope table: from the body's identification number to the first note / site list."""
    m = TABLE_START.search(text)
    body = text[m.end():] if m else text
    e = TABLE_END.search(body)
    return body[:e.start()] if e else body


# --------------------------------------------------------------------------- EA tables
ITEM_CELL = re.compile(r"^(\d{1,2})\)?\s*(\**)$")
EA_CELL = re.compile(r"^(\d{1,2})\s*(\**)$")


def ea_table(pdf: Path) -> tuple[dict[int, str], list[str]]:
    """Reads the "Položka | Kód EA | NACE | Názov činnosti" table cell by cell.

    Returns ({EA code: its mark ("", "*" or "**"), from the item or the EA cell}, problems).
    The text layout is not used here: SNAS prints the EA code in the vertical middle of its
    NACE rows, so lines do not pair them; the table cells do."""
    codes: dict[int, str] = {}
    problems: list[str] = []
    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            for table in page.extract_tables():
                head = " ".join(c or "" for row in table[:3] for c in row)
                if not re.search(r"\bEA\b", head):
                    continue
                for row in table:
                    cells = [clean(c.replace("", "*")) for c in row if c and clean(c)]
                    if len(cells) < 2:
                        continue
                    mark, rest = "", cells
                    if (m := ITEM_CELL.match(cells[0])) and len(cells) >= 3 and EA_CELL.match(cells[1]):
                        mark, rest = m.group(2), cells[1:]
                    m = EA_CELL.match(rest[0])
                    if not m or not re.search(r"\d", rest[1]):
                        continue
                    ea = int(m.group(1))
                    mark = max(mark, m.group(2), key=len)
                    if not 1 <= ea <= 39:
                        problems.append(f"EA cell {rest[0]!r} out of range")
                        continue
                    naces = re.findall(r"(?<![\d.])\d{2}(?:\.\d{1,2})?(?![\d.])", rest[1])
                    if naces and not any(ea_of(n) == ea for n in naces):
                        problems.append(f"EA {ea} row lists NACE {', '.join(naces)}")
                    codes[ea] = max(codes.get(ea, ""), mark, key=len)
    return codes, problems


def footnotes(text: str) -> dict[str, str]:
    """The table's footnotes by mark: {"*": "...", "**": "..."}."""
    out = {}
    for m in re.finditer(r"^\s*(\*{1,2})\s*(?:Pozn[a-zá]*\.?:?|Note:)?\s*(\S.*)$", text, re.M):
        if m.group(2).startswith("*"):
            continue
        out.setdefault(m.group(1), clean(m.group(2)))
    return out


# ---------------------------------------------------------------- other sector lists
# ISO 22003-1 food chain categories by their Slovak names (case-sensitive: the group names
# "Stravovanie / služby ...", "Doplnkové služby" and "Biochemikálie" hold one category each).
FOOD_WORDS = [("A", r"Chov zvierat"), ("B", r"Pestovanie alebo manipulácia|\bBIII?\b"),
              ("C", r"Spracovanie potravín,|\bC0\b|\bCI{1,3}V?\b"), ("D", r"Spracovanie krmív"),
              ("E", r"Stravovanie"), ("F", r"Obchodovanie|Sprostredkovanie"),
              ("G", r"Služby prepravy"), ("H", r"(?<!\w)Služby(?! prepravy)|Doplnkové služby"),
              ("I", r"Výroba obalov|Obalový materiál"), ("J", r"Zariadenie|Pomocné zariadenia"),
              ("K", r"Chemikálie|Biochemikálie")]
# ISO 50003 technical areas by their Slovak names (case-sensitive: descriptions reuse words).
ENERGY_WORDS = [("A", r"Priemysel\s*[–-]\s*ľahký"), ("B", r"Priemysel\s*[–-]\s*ťažký"),
                ("C", r"(?<!\w)Budovy\b"), ("D", r"Stavebné komplexy"), ("E", r"(?<!\w)Doprava\b"),
                ("F", r"Ťažobný priemysel"), ("G", r"Poľnohospodárstvo"), ("H", r"Zásobovanie energiou")]


def food_scope(text: str) -> tuple[set[int], str]:
    t = table_text(text)
    letters = [l for l, pattern in FOOD_WORDS if re.search(pattern, t)]
    codes = set().union(*(esyd.expand(esyd.FOOD_CATEGORIES[l]) for l in letters)) if letters else set()
    return codes, f"ISO 22003-1 categories {', '.join(letters)} (classified to EA by sector)"


def energy_scope(text: str) -> tuple[set[int], set[str], str]:
    t = table_text(text)
    letters, restricted = [], set()
    for letter, pattern in ENERGY_WORDS:
        for line in t.splitlines():
            if re.search(pattern, line):
                letters.append(letter)
                if re.match(r"\s*\d{1,2}\s*\*", line):
                    restricted.add(letter)
                break
    kept = [l for l in letters if l not in restricted]
    codes = set().union(*(esyd.expand(ENERGY_EA[l]) for l in kept)) if kept else set()
    names = "; ".join(f"{l} {ENERGY_NAMES[l]}" for l in kept)
    return codes, restricted, f"ISO 50003 technical areas {names} (classified to EA by sector)"


def medical_scope(text: str) -> tuple[set[int], str]:
    areas = sorted({int(n) for n in re.findall(r"\bMD\s*(\d)\.\d", table_text(text))})
    names = [MEDICAL_AREAS[a] for a in areas if a in MEDICAL_AREAS]
    codes = set().union(*(esyd.expand(MEDICAL_EA[n]) for n in names)) if names else set()
    return codes, f"IAF MD 8 main technical areas: {'; '.join(names)} (classified to EA by sector)"


# ------------------------------------------------------------------------------------ main
def website(raw: str) -> str:
    value = clean(raw.split(";")[0]).rstrip("/")
    if not value:
        return ""
    return value if value.startswith("http") else "https://" + value


def address(raw: str) -> str:
    parts = [clean(p) for p in raw.split(",")]
    parts = [p for p in parts if p and p != "Slovenská republika"]
    return ", ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()

    certs = list(csv.DictReader(open(args.scrape / "certificates.csv", encoding="utf-8-sig")))
    files = defaultdict(dict)
    for f in csv.DictReader(open(args.scrape / "files.csv", encoding="utf-8-sig")):
        if f["status"] in ("downloaded", "already_present"):
            files[f["certificate_no"]][f["language"]] = args.scrape / f["path"]

    review: list[str] = []
    entries = []  # one per SNAS certificate with an importable scheme
    bodies: dict[str, dict] = {}
    for c in certs:
        number, name = c["certificate_no"], clean(c["body"])
        status = {"valid": "ACTIVE", "suspended": "SUSPENDED"}.get(c["status"], "WITHDRAWN")
        if c["field_id"] in SKIPPED_FIELDS:
            review.append(f"{number} {name}: {SKIPPED_FIELDS[c['field_id']]} not imported")
            continue
        if status == "WITHDRAWN":
            continue  # expired / withdrawn certificates carry no field or annex in the scrape
        if c["field_id"] not in FIELDS:
            review.append(f"{number} {name}: unknown field {c['field_id']} {c['field_en']}; not imported")
            continue
        std, kind = FIELDS[c["field_id"]]
        texts = {lang: t for lang, p in files.get(number, {}).items() if (t := pdf_text(p))}
        text = texts.get("sk") or texts.get("en")
        note = ""
        if kind == "all":
            codes, note = set(range(1, 40)), ALL_NOTE
        elif text is None:
            review.append(f"{number} {name}: {std} annex not available; not imported")
            continue
        elif kind == "ea":
            tables = {}
            for lang in ("sk", "en"):
                if lang in texts:
                    marks, problems = ea_table(files[number][lang])
                    tables[lang] = marks
                    review.extend(f"{number} {name} ({lang.upper()} annex): {p}" for p in problems)
            # The Slovak annex is the authoritative one; the English one is a translation.
            lang = "sk" if tables.get("sk") else "en"
            marks = tables.get(lang, {})
            if lang == "en" and marks:
                review.append(f"{number} {name}: SK annex unreadable; EA codes read from the EN annex")
            other = tables.get("en" if lang == "sk" else "sk")
            if other and set(other) != set(marks):
                review.append(f"{number} {name}: EN annex lists EA {ea_spec(set(other))}, SK annex "
                              f"{ea_spec(set(marks))}; SK used")
            if other and {e for e, m in other.items() if m} != {e for e, m in marks.items() if m}:
                review.append(f"{number} {name}: marked EA codes differ between annexes (SK "
                              f"{ea_spec({e for e, m in marks.items() if m}) or '-'}, EN "
                              f"{ea_spec({e for e, m in other.items() if m}) or '-'}); SK used")
            codes, excluded, limited = set(marks), set(), {}
            for ea, mark in marks.items():
                if not mark:
                    continue
                if (number, ea) in LIMITS:
                    limited[ea] = LIMITS[(number, ea)]
                else:
                    excluded.add(ea)
            notes = []
            if excluded:
                codes -= excluded
                why = WHY_EXCLUDED.get(number, "the SNAS annex marks them as areas where the body "
                                               "may not issue accredited certificates")
                notes.append(f"EA {', '.join(map(str, sorted(excluded)))} left out: {why}")
            for ea, what in sorted(limited.items()):
                notes.append(f"Limited scope for EA {ea}: {what}")
            note = "; ".join(notes)
        elif kind == "food":
            codes, note = food_scope(text)
        elif kind == "energy":
            codes, restricted, note = energy_scope(text)
            if restricted:
                note += (f"; technical area {', '.join(sorted(restricted))} marked as not covered "
                         f"by accredited certificates, left out")
        else:
            codes, note = medical_scope(text)
        if not codes:
            review.append(f"{number} {name}: {std} annex has no readable sectors; not imported")
            continue
        entries.append({"number": number, "member": c["member_no"], "body": name, "status": status,
                        "issue": c["valid_from"], "expiry": c["valid_to"], "standard": std,
                        "codes": codes, "note": note})
        bodies.setdefault(name, c)

    # ---- accreditations and scopes: one per body and accreditation standard, as in NAH
    accreditations, scopes = [], []
    today = args.today.isoformat()
    by_body: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_body[e["body"]].append(e)
    for name, group in by_body.items():
        live = [e for e in group if e["status"] == "ACTIVE" and (not e["expiry"] or e["expiry"] >= today)]
        for e in (e for e in group if e not in live):  # left for prune_inactive to log
            accreditations.append(acc_row(e["number"], name, SCHEME_ROWS.get(e["standard"], BASE), e))
            scopes.append(scope_row(e["number"], e["standard"], e["codes"], e["note"]))
        by_acc: dict[str, list[dict]] = defaultdict(list)
        for e in live:
            by_acc[SCHEME_ROWS.get(e["standard"], BASE)].append(e)
        if live and BASE not in by_acc:
            review.append(f"{name}: no ISO/IEC 17021-1 scheme (holds {', '.join(sorted(by_acc))}); "
                          f"search requires one, so the body is dropped")
        for acc_std, items in by_acc.items():
            primary = min(items, key=lambda e: (PRIMARY_ORDER.index(e["standard"])
                                                if e["standard"] in PRIMARY_ORDER else 99, e["number"]))
            merged = dict(primary, issue=min(e["issue"] for e in items),
                          expiry=max(e["expiry"] for e in items))
            accreditations.append(acc_row(primary["number"], name, acc_std, merged))
            if len(items) > 1:
                review.append(f"{name}: {acc_std} certificates {', '.join(e['number'] for e in items)} "
                              f"merged under {primary['number']}")
            for e in items:
                note = e["note"]
                if e is not primary:
                    note = "; ".join(filter(None, [note, f"Accredited under SNAS {e['number']}, valid "
                                                         f"{e['issue']} to {e['expiry']}"]))
                scopes.append(scope_row(primary["number"], e["standard"], e["codes"], note))

    body_rows = []
    for name in sorted(by_body, key=str.casefold):
        c = bodies[name]
        body_rows.append({
            "name": name, "country": "Slovakia", "registration_no": clean(c["company_id"]),
            "phone": "", "email": "", "website": website(c["web"]), "address": address(c["address"]),
            "source_url": SOURCE_URL, "verified_at": "",
        })

    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out / "bodies.csv", BODY_COLUMNS, body_rows)
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda a: a["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes, key=lambda s: (s["certificate_number"], s["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scopes))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "snas_review.md", "w", encoding="utf-8") as f:
        f.write("# SNAS (Slovakia) conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'snas_review.md'}")


def acc_row(cert: str, body: str, standard: str, e: dict) -> dict:
    return {"ab_code": AB_CODE, "certificate_number": cert, "body_name": body,
            "accreditation_standard": standard, "status": e["status"], "issue_date": e["issue"],
            "expiry_date": e["expiry"], "proof_url": SOURCE_URL}


def scope_row(cert: str, std: str, codes: set[int], note: str) -> dict:
    return {"certificate_number": cert, "certification_standard": std, "ea_codes": ea_spec(codes),
            "status": "ACTIVE", "scope_note": note}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


PDFTOTEXT = shutil.which("pdftotext") or "pdftotext"

if __name__ == "__main__":
    main()
