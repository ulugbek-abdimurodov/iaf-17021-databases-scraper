#!/usr/bin/env python3
"""Convert the CAI (Český institut pro akreditaci, Czech Accreditation Institute) management-
system scrape into a CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by cai_scraper.py (bodies.csv, certificates.csv, files.csv and the
PDFs). Each CAI "osvědčení o akreditaci" (certificate of accreditation, e.g. 279/2025) is
issued under ISO/IEC 17021-1 and carries its annex ("Příloha"), one numbered section per
scheme:
- "Certifikace systémů managementu": one row per EA code ("Kód oboru"), with the CZ-NACE codes
  it is limited to ("Omezeno na") and the standards (ISO 9001 / 14001 / 45001, ISO 9001 "ve
  spojení s" ISO 3834-x). Rows with no EA code ("-") are national schemes (HACCP per Věstník
  MZe, SJ-PK road-construction quality system, CFCS forest certification) and are left out.
- information security, IT service management, business continuity, anti-bribery: one row
  without sectors.
- food safety: ISO 22003-1 categories; energy: ISO 50003 technical areas; medical devices:
  IAF MD 8 main technical areas. All three are classified to EA with the ESYD tables.
- EMAS environmental verifier and notified-body sections ("Akreditace pro účely autorizace/
  oznámení") are not management-system certification and are left out.
Only the Czech annex is read; it is the authoritative one.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points are written to cai_review.md next to this script; prune_inactive.prune() then
drops everything that is not currently valid.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
import unicodedata
from collections import Counter, defaultdict
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

AB_CODE = "CAI"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
REGISTER_URL = "https://www.cai.cz/en/?subjekt={slug}"
ALL_NOTE = "No sector list in the CAI annex; recorded for all EA sectors"

# Certification standard -> accreditation standard; everything else is under ISO/IEC 17021-1.
SCHEME_ROWS = {
    "ISO 22000": "ISO 22003-1", "FSSC 22000": "ISO 22003-1",
    "ISO 50001": "ISO 50003",
    "ISO/IEC 27001": "ISO/IEC 27006",
    "ISO/IEC 20000-1": "ISO/IEC 20000-6",
    "ISO 22301": "ISO/IEC 17021-6",
    "ISO 37001": "ISO/IEC 17021-9",
}
SUFFIX = {"ISO 22003-1": "22000", "ISO 50003": "50003", "ISO/IEC 27006": "27006",
          "ISO/IEC 20000-6": "20000", "ISO/IEC 17021-6": "22301", "ISO/IEC 17021-9": "37001"}

# Standards named in a specification cell (spaces removed). ISO 9001 "ve spojení s" ISO 3834-x
# is ISO 3834; it is cut out of the cell before plain ISO 9001 is looked for.
WELDING = re.compile(r"(?:ČSN|STN)?(?:EN)?ISO9001(?::\d{4})?(?:i)?vespojení(?:se|s)?"
                     r"(?:(?:s)?(?:ČSN|STN)?(?:EN)?ISO3834-?\d?(?::\d{4})?)+")
REGULATION = re.compile(r"(?:ČSN|STN)?(?:EN)?ISO9001(?::\d{4})?(?:i)?vespojení(?:se|s)?"
                        r"nařízením[^Č]*?333/2011(?:\([^)]*\))?")
STANDARDS = [
    ("ISO 9001", re.compile(r"ISO9001")),
    ("ISO 14001", re.compile(r"ISO14001")),
    ("ISO 45001", re.compile(r"ISO45001")),
    ("ISO 13485", re.compile(r"ISO13485")),
    ("ISO 50001", re.compile(r"ISO50001")),
    ("FSSC 22000", re.compile(r"FSSC22000")),
    ("ISO 22000", re.compile(r"ISO22000")),
    ("ISO/IEC 27001", re.compile(r"ISO/IEC27001")),
    ("ISO/IEC 20000-1", re.compile(r"ISO/IEC20000-1")),
    ("ISO 22301", re.compile(r"ISO22301")),
    ("ISO 37001", re.compile(r"ISO37001")),
]
NATIONAL = re.compile(r"HACCP|SJ-PK|CFCS|PEFC|Věstník", re.I)

ENERGY_WORDS = [("A", r"průmysl\W*lehk"), ("B", r"průmysl\W*těžk"), ("D", r"komplexy"),
                ("C", r"^budovy"), ("E", r"^doprava"), ("F", r"^těžba"), ("G", r"^zemědělství"),
                ("H", r"^zásobování")]
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


# Some annexes store Czech letters decomposed (u + combining ring); patterns expect NFC.
def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def squash(text: str | None) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


def standards_in(cell: str) -> set[str]:
    flat = squash(cell)
    found = set()
    if WELDING.search(flat):
        found.add("ISO 3834")
        flat = WELDING.sub(" ", flat)
    flat = REGULATION.sub(" ", flat)
    if re.search(r"ISO3834", flat):
        found.add("ISO 3834")
    for std, pattern in STANDARDS:
        if pattern.search(flat):
            found.add(std)
    return found


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


# The complete CZ-NACE list of each EA code, as CAI prints it for an unrestricted row (MPA 50-01
# annex 5; CZ-NACE = NACE Rev. 2). A row whose "Omezeno na" cell lists anything else is limited
# to those NACE codes, which go into the scope note. EA 11 (nuclear fuel) is in no CAI annex.
FULL_NACE = {
    1: "01, 02, 03", 2: "05, 06, 07, 08, 09", 3: "10, 11, 12", 4: "13, 14", 5: "15", 6: "16",
    7: "17", 8: "58.1, 59.2", 9: "18", 10: "19", 12: "20", 13: "21", 14: "22",
    15: "23 vyjma 23.5 a 23.6", 16: "23.5, 23.6", 17: "24 vyjma 24.46, 25 vyjma 25.4, 33.11",
    18: "25.4, 28, 30.4, 33.12, 33.2", 19: "26, 27, 33.13, 33.14, 95.1", 20: "30.1, 33.15",
    21: "30.3, 33.16", 22: "29, 30.2, 30.9, 33.17", 23: "31, 32, 33.19", 24: "38.3",
    25: "35.1", 26: "35.2", 27: "35.3, 36", 28: "41, 42, 43", 29: "45, 46, 47, 95.2",
    30: "55, 56", 31: "49, 50, 51, 52, 53, 61", 32: "64, 65, 66, 68, 77", 33: "58.2, 62, 63.1",
    34: "71, 72, 74 vyjma 74.2 a 74.3", 35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 36: "84",
    37: "85", 38: "75, 86, 87, 88",
    39: "37, 38.1, 38.2, 39, 59.1, 60, 63.9, 79, 90, 91, 92, 93, 94, 96",
}
NACE_TOKEN = re.compile(r"vyjma|mimo|kromě|\d{2}(?:\.\d{1,2})*")


def nace_text(cell: str | None) -> str:
    """The cell as printed, one line: '24 vyjma 24.46,\\n25' -> '24 vyjma 24.46, 25'."""
    t = (cell or "").replace("\n", " ")
    t = re.sub(r"(?<=\d),(\d)(?!\d)", r".\1", t)       # '23,6' is a typo for '23.6'
    t = re.sub(r"(\d)(vyjma|mimo)", r"\1 \2", t)
    t = re.sub(r"(vyjma|mimo)(\d)", r"\1 \2", t)
    t = re.sub(r"(?<=\d)a(?=\d)", " a ", t)
    t = re.sub(r",(?=\S)", ", ", t)
    return clean(t)


def nace_key(text: str) -> tuple[str, ...]:
    """Order-insensitive tokens; '30.40' and '30.4' are the same class."""
    tokens = [re.sub(r"(\.\d)0$", r"\1", t) for t in NACE_TOKEN.findall(nace_text(text))]
    return tuple(sorted("vyjma" if t in ("mimo", "kromě") else t for t in tokens))


def nace_en(text: str) -> str:
    """'24 vyjma 24.46, 25 vyjma 25.4' -> '24 except 24.46, 25 except 25.4'."""
    t = nace_text(text)
    t = re.sub(r"\s*(?:vyjma|mimo)\s*", " except ", t)
    t = re.sub(r"(?<=\d)\s+a\s+(?=\d)", " and ", t)
    return clean(t.replace("( except", "(except"))


# Limits written into the EA name cell instead of the NACE cell.
NAME_LIMITS = {
    "Omezenonavýrobuhutníchakovodělnýchvýrobků":
        "limited to manufacture of metallurgical and fabricated metal products",
}


# --------------------------------------------------------------------------- annex tables
class Annex:
    def __init__(self):
        # EA tables: standard -> EA -> list of (NACE text, name text)
        self.ea: dict[str, dict[int, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
        self.all: set[str] = set()          # standards without a sector list
        self.food: dict[str, set[str]] = defaultdict(set)   # standard -> category letters
        self.energy: set[str] = set()
        self.medical: set[int] = set()
        self.merged: list[int] = []   # EA rows that share the specification cell above them
        self.skipped: list[str] = []


def table_kind(header: str) -> str | None:
    h = squash(header).lower()
    if "kódoboru" in h or "kodoboru" in h:
        return "ea"
    if "klastr" in h or "kategorie" in h:
        return "food"
    if "hlavnítechnick" in h:
        return "medical"
    if "technickáoblast" in h or "technickéoblast" in h:
        return "energy"
    if "produkt" in h or "postup" in h:
        return "notified"
    return None


def parse_annex(pdf: Path) -> Annex:
    annex = Annex()
    with pdfplumber.open(pdf) as doc:
        tables = [t for page in doc.pages for t in page.extract_tables()]
    kind, last = None, None   # last: the EA row a continuation row belongs to
    for table in tables:
        if not table:
            continue
        k = table_kind(" ".join(c or "" for c in table[0]))
        rows = table
        if k:
            kind, rows = k, table[1:]
            if kind != "ea":
                last = None
        if kind == "ea":
            last = ea_rows(rows, annex, last)
        elif kind == "food":
            for row in rows:
                cells = [c or "" for c in row]
                stds = standards_in(" ".join(cells)) & {"ISO 22000", "FSSC 22000"}
                for c in cells[1:4]:
                    for m in re.finditer(r"(?:^|\s)([A-K])(?:0|I{1,3}V?|IV)?\s*[–-]", clean(c)):
                        for s in (stds or {"ISO 22000"}):
                            annex.food[s].add(m.group(1))
                if stds:
                    for s in stds:
                        annex.food.setdefault(s, set())
        elif kind == "energy":
            for row in rows:
                cells = [squash(c).lower() for c in row if c]
                for cell in cells[:2]:
                    for letter, pattern in ENERGY_WORDS:
                        if re.search(pattern, cell):
                            annex.energy.add(letter)
                            break
        elif kind == "medical":
            for row in rows:
                for c in row[1:2]:
                    m = re.match(r"^\s*(\d)\.\s*[^\d\s.]", c or "")
                    if m:
                        annex.medical.add(int(m.group(1)))
    return annex


NO_SECTORS = {"ISO/IEC 27001", "ISO/IEC 20000-1", "ISO 22301", "ISO 37001"}
# Schemes without sectors, by the name cell (some annexes leave out the specification column).
SCHEME_NAMES = [("ISO/IEC 27001", r"informačníbezpečnost"),
                ("ISO/IEC 20000-1", r"služebvoblastiinformačníchtechnologi"),
                ("ISO 22301", r"kontinuit"), ("ISO 37001", r"protikorupční")]
# The EA cell; some annexes print the row number into it as well ("3 6 ." is EA 6).
EA_CELL = re.compile(r"^(?:\d{1,2}\s+)?(\d{1,2})\s*\.?$")


def ea_rows(rows, annex: Annex, last):
    for row in rows:
        if len(row) < 4:
            continue
        cells = [c or "" for c in row] + [""] * 5
        num, code, name, nace, spec = (clean(c) for c in cells[:5])
        if m := EA_CELL.match(code):
            ea = int(m.group(1))
            if code != m.group(1):
                annex.skipped.append(f"EA cell {code!r} read as EA {ea} ({name[:50]})")
            if not 1 <= ea <= 39:
                annex.skipped.append(f"EA cell {code!r} out of range")
                continue
            if not spec and last is not None and last.get("spec"):
                # The specification cell spans several EA rows (merged cell).
                spec = last["spec"]
                if standards_in(spec):
                    annex.merged.append(ea)
            last = {"ea": ea, "nace": nace, "name": name, "stds": set(), "spec": spec}
            add_ea(annex, last, spec)
        elif re.fullmatch(r"[-–—]+", code) or (num and not code):
            # A row without an EA code: either a scheme without sectors or a national scheme.
            stds = standards_in(spec) & NO_SECTORS
            if not stds and not NATIONAL.search(squash(name + spec)):
                stds = {s for s, p in SCHEME_NAMES if re.search(p, squash(name).lower())}
            if stds:
                annex.all |= stds
            elif clean(name + spec):
                annex.skipped.append(f"row without EA code not imported: {clean(name)[:90]}"
                                     f"{' / ' + clean(spec)[:90] if spec else ''}")
            last = None
        elif not num and not code and last is not None:
            if nace and spec:
                # A sub-row: some standards of the same EA code, with their own NACE limits.
                sub = dict(last, nace=nace, stds=set())
                add_ea(annex, sub, spec)
            elif spec:
                add_ea(annex, last, spec)  # the specification cell continues on the next page
                last["spec"] = last["spec"] + " " + spec
            elif nace:
                annex.skipped.append(f"EA {last['ea']}: NACE continuation {nace!r} ignored")
    return last


def add_ea(annex: Annex, row: dict, spec: str) -> None:
    for std in standards_in(spec) - row["stds"]:
        annex.ea[std][row["ea"]].append((row["nace"], row["name"]))
        row["stds"].add(std)


# ------------------------------------------------------------------------------------ main
def website(raw: str) -> str:
    value = clean(raw).rstrip("/")
    if not value or value in ("http:", "https:"):
        return ""
    return value if value.startswith("http") else "https://" + value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()

    bodies_in = {}
    for b in csv.DictReader(open(args.scrape / "bodies.csv", encoding="utf-8-sig")):
        bodies_in.setdefault(b["cab_number"], b)
    certs = list(csv.DictReader(open(args.scrape / "certificates.csv", encoding="utf-8-sig")))
    files: dict[str, dict[str, dict]] = defaultdict(dict)
    for f in csv.DictReader(open(args.scrape / "files.csv", encoding="utf-8-sig")):
        if f["status"] in ("downloaded", "already_present"):
            files[(f["cab_number"], f["certificate_number"])][f["language"]] = f

    review: list[str] = []
    parsed = []
    for c in certs:
        key = (c["cab_number"], c["certificate_number"])
        cs = files.get(key, {}).get("CS")
        name = clean(c["name"])
        if not cs:
            review.append(f"{c['certificate_number']} {name}: no Czech annex in the scrape; not imported")
            continue
        annex = parse_annex(args.scrape / cs["local_path"])
        review.extend(f"{c['certificate_number']} {name}: {s}" for s in annex.skipped)
        if annex.merged:
            review.append(f"{c['certificate_number']} {name}: EA {', '.join(map(str, annex.merged))} "
                          f"share the specification cell of the EA row above them (merged cell)")
        parsed.append((c, cs, annex))

    entries = []
    limited_rows = Counter()
    for c, cs, annex in parsed:
        number, name = c["certificate_number"], clean(c["name"])
        scopes: dict[str, tuple[set[int], str]] = {}
        for std, by_ea in sorted(annex.ea.items()):
            limits = []
            for ea, items in sorted(by_ea.items()):
                naces = []
                for nace, ea_name in items:
                    if ea not in FULL_NACE:
                        review.append(f"{number} {name}: {std} EA {ea} has no CZ-NACE reference list")
                    elif nace_key(nace) and nace_key(nace) != nace_key(FULL_NACE[ea]):
                        naces.append(nace_en(nace))
                    if re.search(r"omezen|pouze", ea_name, re.I):
                        what = NAME_LIMITS.get(squash(ea_name), clean(ea_name))
                        limits.append(f"EA {ea} {what} (CAI annex)")
                        if squash(ea_name) not in NAME_LIMITS:
                            review.append(f"{number} {name}: {std} EA {ea} name cell not translated: "
                                          f"{clean(ea_name)}")
                # A standard listed under one EA code twice (a sub-row with other NACE codes) is
                # limited only if every row is.
                if naces and len(naces) == len(items):
                    limits.append(f"EA {ea} limited to CZ-NACE {'; '.join(naces)}")
                    limited_rows[ea] += 1
            scopes[std] = (set(by_ea), "; ".join(limits))
        for std in sorted(annex.all):
            scopes[std] = (set(range(1, 40)), ALL_NOTE)
        for std, letters in sorted(annex.food.items()):
            if not letters:
                review.append(f"{number} {name}: {std} without readable categories; not imported")
                continue
            codes = set().union(*(esyd.expand(esyd.FOOD_CATEGORIES[l]) for l in letters))
            scopes[std] = (codes, f"ISO 22003-1 categories {', '.join(sorted(letters))} "
                                  f"(classified to EA by sector)")
        if annex.energy:
            codes = set().union(*(esyd.expand(ENERGY_EA[l]) for l in annex.energy))
            names = "; ".join(f"{l} {ENERGY_NAMES[l]}" for l in sorted(annex.energy))
            scopes["ISO 50001"] = (codes, f"ISO 50003 technical areas {names} (classified to EA by sector)")
        if annex.medical:
            names = [MEDICAL_AREAS[a] for a in sorted(annex.medical)]
            codes = set().union(*(esyd.expand(MEDICAL_EA[n]) for n in names))
            scopes["ISO 13485"] = (codes, f"IAF MD 8 main technical areas: {'; '.join(names)} "
                                          f"(classified to EA by sector)")
        if not scopes:
            review.append(f"{number} {name}: no importable scheme in the annex; not imported")
            continue
        entries.append({"cab": c["cab_number"], "number": number, "body": name,
                        "issue": c["issued"], "expiry": c["valid_until"], "scopes": scopes,
                        "proof": cs["url"]})

    # ---- one accreditation per body and accreditation standard; a body's certificates merge
    accreditations, scope_rows = [], []
    by_body: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_body[e["cab"]].append(e)
    body_rows = []
    for cab, group in sorted(by_body.items()):
        group.sort(key=lambda e: (-sum(len(s[0]) for s in e["scopes"].values()), e["number"]))
        primary = group[0]
        if len(group) > 1:
            review.append(f"{primary['body']}: certificates {', '.join(e['number'] for e in group)} "
                          f"merged under {primary['number']}")
        by_acc: dict[str, list[tuple[dict, str]]] = defaultdict(list)
        for e in group:
            for std in e["scopes"]:
                by_acc[SCHEME_ROWS.get(std, BASE)].append((e, std))
        if BASE not in by_acc:
            review.append(f"{primary['body']}: no ISO/IEC 17021-1 scheme (holds "
                          f"{', '.join(sorted(by_acc))}); CAI accredits every body under ISO/IEC "
                          f"17021-1, so the base row is kept without scopes")
            by_acc[BASE] = []
        for acc_std, items in sorted(by_acc.items()):
            owners = [e for e, _ in items] or [primary]
            owner = primary if primary in owners else owners[0]
            cert = owner["number"] + (f" ({SUFFIX[acc_std]})" if acc_std != BASE else "")
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": cert, "body_name": body_name(cab, primary),
                "accreditation_standard": acc_std, "status": "ACTIVE",
                "issue_date": min(e["issue"] for e in owners),
                "expiry_date": max(e["expiry"] for e in owners), "proof_url": owner["proof"]})
            for e, std in sorted(items, key=lambda i: i[1]):
                codes, note = e["scopes"][std]
                if e is not owner:
                    note = "; ".join(filter(None, [note, f"Accredited under CAI {e['number']}, valid "
                                                         f"{e['issue']} to {e['expiry']}"]))
                scope_rows.append({"certificate_number": cert, "certification_standard": std,
                                   "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": note})
        body_rows.append(body_row(cab, bodies_in[cab], primary))

    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda b: b["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda a: a["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda s: (s["certificate_number"], s["certification_standard"])))
    totals = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "cai_review.md", "w", encoding="utf-8") as f:
        f.write("# CAI (Czechia) conversion review\n\n")
        f.write(f"Generated {args.today.isoformat()}: {totals[0]} bodies, {totals[1]} accreditations, "
                f"{totals[2]} scope rows before pruning.\n\n"
                f"Limited EA scopes (CZ-NACE subset, per standard) by EA code: "
                f"{', '.join(f'EA {ea} ×{n}' for ea, n in sorted(limited_rows.items()))}.\n\n"
                f"## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {totals}; removed {len(removed)} rows; review: {HERE / 'cai_review.md'}")


# INTERCERT DOOEL Skopje is also in data/iarm-north-macedonia. The importer matches bodies on
# (country, name) and overwrites their contact fields, so the IARM row is reused verbatim.
FOREIGN = {
    "3265": {"name": "Intercert DOOEL Skopje (Интерцерт ДООЕЛ Скопје)", "country": "North Macedonia",
             "registration_no": "", "phone": "", "email": "", "website": "http://www.inter-cert.net",
             "address": "Železnička 44/2-10, 1000 Skopje, North Macedonia",
             "source_url": "https://iarm.gov.mk/en/2021/07/08/cb-009-intercert-dooel-skopje/",
             "verified_at": ""},
}


def body_name(cab: str, e: dict) -> str:
    return FOREIGN[cab]["name"] if cab in FOREIGN else e["body"]


def body_row(cab: str, b: dict, e: dict) -> dict:
    if cab in FOREIGN:
        return dict(FOREIGN[cab])
    return {"name": e["body"], "country": "Czechia", "registration_no": clean(b["business_id"]),
            "phone": "", "email": "", "website": website(b["website"]), "address": clean(b["address"]),
            "source_url": REGISTER_URL.format(slug=b["entry_slug"]), "verified_at": ""}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
