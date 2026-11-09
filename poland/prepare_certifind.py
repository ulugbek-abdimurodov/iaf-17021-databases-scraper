#!/usr/bin/env python3
"""Convert the PCA (Polskie Centrum Akredytacji, Poland) management-system scrape into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by pca_scraper.py (bodies.json and pdf_text/, the text of each
body's "Zakres akredytacji" scope annex). PCA gives each body one accreditation number
(AC xxx) with one validity; its annex has a section per certification standard listing the
IAF sectors (ISO 9001 / 14001 / 45001), ISO 22003-1 food chain categories (ISO 22000,
FSSC 22000), ISO 50003 technical areas (ISO 50001) or IAF MD 8 technical areas (ISO 13485).

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points are written to pca_review.md next to this script; prune_inactive.prune() then
drops everything that is not currently valid.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "PCA"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the PCA annex; recorded for all EA sectors"

# Standard line of an annex section -> (CertiFind certification standard, kind of sector list).
# None: a scheme CertiFind does not hold; the section is read so its text is not misread.
STANDARD_LINE = re.compile(
    r"^(?:PN-EN\s+|PN-\s*|PKN-)?(?:ISO(?:/IEC)?\s*(?P<iso>\d{4,5})(?:-\d)?|(?P<fssc>FSSC 22000)|(?P<pefc>PEFC))\b")
STANDARDS = {
    "9001": ("ISO 9001", "iaf"), "14001": ("ISO 14001", "iaf"), "45001": ("ISO 45001", "iaf"),
    "22000": ("ISO 22000", "food"), "FSSC": ("FSSC 22000", "food"),
    "50001": ("ISO 50001", "energy"), "13485": ("ISO 13485", "medical"),
    "27001": ("ISO/IEC 27001", "all"), "22301": ("ISO 22301", "all"),
    "37001": ("ISO 37001", "all"), "3834": ("ISO 3834", "all"), "15378": ("ISO 15378", "all"),
    "PEFC": (None, "skip"),
}
# Certification standard -> (accreditation standard, certificate-number suffix). Everything
# else is certified under the ISO/IEC 17021-1 row with the plain AC number.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
}
# Schemes in the register listing that CertiFind does not import.
SKIPPED = [
    (re.compile(r"PEFC"), "PEFC PL 1003 forest management (national PEFC standard)"),
    (re.compile(r"2014/68"), "2014/68/EU pressure equipment (notified-body activity)"),
    (re.compile(r"2014/33"), "2014/33/EU lifts (notified-body activity)"),
    (re.compile(r"2006/42"), "2006/42/EC machinery (notified-body activity)"),
    (re.compile(r"2019/945"), "(EU) 2019/945 unmanned aircraft systems (notified-body activity)"),
    (re.compile(r"GB/T\s*19001"), "GB/T 19001 (Chinese national adoption of ISO 9001)"),
]
# Register listing standard -> CertiFind standard, to check the annex against the listing.
LISTING = {"PN-EN ISO 9001": "ISO 9001", "PN-EN ISO 14001": "ISO 14001",
           "PN-EN ISO 45001": "ISO 45001", "PN-EN ISO 22000": "ISO 22000",
           "FSSC 22000": "FSSC 22000", "PN-EN ISO 50001": "ISO 50001",
           "PN-EN ISO 13485": "ISO 13485", "PN-EN ISO/IEC 27001": "ISO/IEC 27001",
           "PN-EN ISO 22301": "ISO 22301", "PN-ISO 37001": "ISO 37001",
           "PN-EN ISO 3834": "ISO 3834", "PN-EN ISO 15378": "ISO 15378"}

# Partial suspensions: PCA marks the suspended part of a table only in bold italic, which the
# text does not keep. Read from the PDF by hand: {(AC number, standard): (letters, note)}.
SUSPENDED_PARTS = {
    ("AC 014", "FSSC 22000"): ({"B"}, "Category B (BIII post-harvest handling) suspended at the "
                                      "body's request from 2026-08-18 to 2027-02-17; not included"),
}
SUSPENSION_RE = re.compile(r"zawieszona.*?od\s+(\d{2})\.(\d{2})\.(\d{4})\s*(?:r\.)?\s*do\s+(\d{2})\.(\d{2})\.(\d{4})",
                           re.S)

STANDARD_USES = 3
SECTION_END = re.compile(r"^(Wykaz zmian|Przepis prawa europejskiego|Ocena zgodności)")
NOISE = re.compile(r"Klasyfikacja|PKD|Akredytowan|Wydanie|Rozporządzeni|Wersja strony|"
                   r"Zakres akredytacji|certyfikaty|Dz\. ?U", re.I)
IAF_ROW = re.compile(r"^\s*(\d{1,2})\s+(?!bez\b)([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż])")
NACE_TOKEN = re.compile(r"(?<![\d.])\d{2}(?:\.\d{1,2})?(?![\d.])|\bbez\b")
FOOD_TOKEN = re.compile(r"(?<![\w/.\-*])([A-K])(?:0|IV|V|I{1,3})?(?![\w/.\-])")
ENERGY_WORDS = [("A", r"lekki"), ("B", r"ciężki"), ("C", r"^Budynki"), ("D", r"Kompleks"),
                ("E", r"^Transport"), ("F", r"Górnictw|Wydobyw"), ("G", r"Rolnictw"),
                ("H", r"Dostaw\w* energii|Zaopatr\w* w energi")]
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL_WORDS = [
    ("Non-active medical devices", r"nieaktywn"),
    ("Active (non-implantable) medical devices", r"(?<!nie)aktywne\s+(?:\(nieimplantowane\)\s+)?wyroby"),
    ("Active implantable medical devices", r"(?<!nie)aktywne\s+implant|(?<!nie)aktywne wyroby medyczne do implantacji"),
    ("In vitro diagnostic medical devices", r"in[ -]vitro|\bIVD\b"),
    ("Sterilization methods", r"sterylizac"),
    ("Devices incorporating specific substances / technologies",
     r"specjalne\s+substancje|zawierające\s+produkty\s+lecznicze|tkanki\s+pochodzenia"),
    ("Parts or services", r"Części\s+lub\s+usługi|Usługi\s+dystrybucji"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def ea_spec(codes: set[int]) -> str:
    if set(range(1, 40)) <= codes:
        return "ALL"
    out, run = [], []
    for c in sorted(codes) + [None]:
        if run and c is not None and c == run[-1] + 1:
            run.append(c)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [c] if c is not None else []
    return ";".join(out)


def pl_date(d: str, m: str, y: str) -> str:
    return f"{y}-{m}-{d}"


# --------------------------------------------------------------------------- annex parsing
class Section:
    def __init__(self, key: str, line: str):
        self.standard, self.kind = STANDARDS[key]
        self.line = line
        self.lines: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def split_sections(text: str) -> list[Section]:
    lines = text.splitlines()
    sections: list[Section] = []
    open_section: Section | None = None
    for i, line in enumerate(lines):
        s = line.strip()
        m = STANDARD_LINE.match(s)
        heading = " ".join(lines[max(0, i - 3):i])
        if m and re.search(r"CERTYFIKACJ|SYSTEMU ZARZĄDZANIA|GOSPODARKI|\(GMP\)", heading):
            key = m["iso"] or ("FSSC" if m["fssc"] else "PEFC")
            if open_section is not None and STANDARDS.get(key, (None,))[0] == open_section.standard \
                    and open_section.standard is not None:
                continue  # another edition or part of the same standard (45001:2018 / :2024, 3834-2)
            if key in STANDARDS:
                open_section = Section(key, s)
                sections.append(open_section)
                continue
        if SECTION_END.match(s) or s.startswith("CERTYFIKACJA SYSTEMU") or s.startswith("CERTYFIKACJA GOSPOD"):
            open_section = None
            continue
        if open_section is not None:
            open_section.lines.append(line)
    return sections


class Row:
    def __init__(self):
        self.tokens: list[str] = []
        self.raw: list[str] = []

    @property
    def nace(self) -> str:
        """The row's NACE column in English wording, e.g. '28 excluding 28.21–23; 28.3'."""
        parts = [clean(p).rstrip(" ,;") for p in self.raw if clean(p)]
        text = "; ".join(parts) if any(";" in p for p in parts) else ", ".join(parts)
        text = re.sub(r"\bbez\b", "excluding", text).replace("÷", "–")
        return re.sub(r"\s+i\s+", ", ", text).rstrip(" ,;")


def iaf_rows(section: Section) -> dict[int, Row]:
    """IAF code -> its row's NACE column (a row continues until the next code row)."""
    rows: dict[int, Row] = {}
    current = None
    for line in section.lines:
        if NOISE.search(line):
            current = None
            continue
        m = IAF_ROW.match(line)
        if m and 1 <= int(m[1]) <= 39:
            current = int(m[1])
            row = rows.setdefault(current, Row())
            tail = line[m.end(1):]
            first = NACE_TOKEN.search(tail)
            row.tokens += NACE_TOKEN.findall(tail)
            if first:
                row.raw.append(tail[first.start():])
        elif current is not None and re.match(r"^\s*(\d|bez\b)", line):
            rows[current].tokens += NACE_TOKEN.findall(line)
            rows[current].raw.append(line)
    return rows


def food_letters(section: Section) -> set[str]:
    letters = set()
    for line in section.lines:
        if NOISE.search(line) or line.strip().startswith(("ISO", "Kod", "ul.")):
            continue
        letters |= set(FOOD_TOKEN.findall(line))
    return letters


def energy_letters(section: Section) -> list[str]:
    stripped = [l.strip() for l in section.lines if not NOISE.search(l)]
    return [letter for letter, pattern in ENERGY_WORDS
            if any(re.search(pattern, l) for l in stripped)]


def medical_areas(section: Section) -> list[str]:
    flat = clean(" ".join(l for l in section.lines if not NOISE.search(l)))
    return [name for name, pattern in MEDICAL_WORDS if re.search(pattern, flat, re.I)]


# ------------------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    today = args.today.isoformat()

    data = json.loads((args.scrape / "bodies.json").read_text(encoding="utf-8"))
    review: list[str] = []
    parsed = []  # (body, {standard: (codes, note)}, annex text)
    nace_rows: dict[int, Counter] = defaultdict(Counter)  # for spotting narrowed sectors

    for b in data["bodies"]:
        number = b["accreditation_number"]
        name = clean(b["organization"])
        text = (args.scrape / "pdf_text" / f"{number.replace(' ', '_')}.txt").read_text(encoding="utf-8")
        listing = {LISTING[s["standard"]] for s in b["scopes"] if s["standard"] in LISTING}
        for s in b["scopes"]:
            if s["standard"] not in LISTING:
                why = next((w for p, w in SKIPPED if p.search(s["standard"] + s["scheme"])), None)
                review.append(f"{number} {name}: {why or 'unknown scheme ' + s['standard']} not imported")
        if re.search(r"GB/T\s*19001", text):
            review.append(f"{number} {name}: {SKIPPED[-1][1]} not imported")
        for m in SUSPENSION_RE.finditer(text):
            start, end = pl_date(*m.groups()[:3]), pl_date(*m.groups()[3:])
            if start <= today <= end and not any(k[0] == number for k in SUSPENDED_PARTS):
                review.append(f"{number} {name}: annex marks a partial suspension {start} to {end} "
                              f"in bold italic; add it to SUSPENDED_PARTS")
            elif end < today:
                review.append(f"{number} {name}: partial suspension {start} to {end} has ended; "
                              f"scope imported in full")

        scopes: dict[str, tuple[set[int], str]] = {}
        rows_by_std: dict[str, dict[int, list[str]]] = {}
        for sec in split_sections(text):
            if sec.kind == "skip":
                continue
            note = ""
            if sec.kind == "iaf":
                rows = iaf_rows(sec)
                codes = set(rows)
                if sec.standard in rows_by_std:  # a section printed twice (per location)
                    rows_by_std[sec.standard].update(rows)
                else:
                    rows_by_std[sec.standard] = rows
            elif sec.kind == "food":
                letters = food_letters(sec)
                held = SUSPENDED_PARTS.get((number, sec.standard))
                if held:
                    letters -= held[0]
                    note = held[1]
                codes = set().union(*(esyd.expand(esyd.FOOD_CATEGORIES[l]) for l in letters)) if letters else set()
                note = "; ".join(filter(None, [f"ISO 22003-1 categories {', '.join(sorted(letters))} "
                                               f"(classified to EA by sector)", note]))
            elif sec.kind == "energy":
                letters = energy_letters(sec)
                codes = set().union(*(esyd.expand(ENERGY_EA[l]) for l in letters)) if letters else set()
                note = ("ISO 50003 technical areas " + "; ".join(f"{l} {ENERGY_NAMES[l]}" for l in letters)
                        + " (classified to EA by sector)")
            elif sec.kind == "medical":
                names = medical_areas(sec)
                codes = set().union(*(esyd.expand(MEDICAL_EA[n]) for n in names)) if names else set()
                note = f"IAF MD 8 main technical areas: {'; '.join(names)} (classified to EA by sector)"
            else:
                codes, note = set(range(1, 40)), ALL_NOTE
            if not codes:
                review.append(f"{number} {name}: {sec.standard} section has no sectors; not imported")
                continue
            if sec.standard in scopes:
                old_codes, old_note = scopes[sec.standard]
                codes = codes | old_codes
                note = old_note if old_note == note else "; ".join(filter(None, [old_note, note]))
                review.append(f"{number} {name}: {sec.standard} section appears twice; sectors combined")
            scopes[sec.standard] = (codes, note)
        for std, rows in rows_by_std.items():
            for code, row in rows.items():
                nace_rows[code][tuple(row.tokens)] += 1
        for std in sorted(listing - set(scopes)):
            review.append(f"{number} {name}: register lists {std} but the annex has no section for it; "
                          f"not imported")
        for std in sorted(set(scopes) - listing):
            review.append(f"{number} {name}: annex has {std}, which the register listing does not name")
        parsed.append((b, scopes, rows_by_std, text))

    # PCA prints one standard NACE column per IAF code, in two table editions (the newer moves
    # 74.2 from EA 35 to EA 34). A row matching neither is a limited scope. A variant shared by
    # at least STANDARD_USES annexes counts as a standard edition, not a limitation.
    usual = {code: {t for t, n in counter.items() if n >= STANDARD_USES} for code, counter in nace_rows.items()}
    accreditations, scopes_out, body_rows = [], [], []
    for b, scopes, rows_by_std, text in parsed:
        number = b["accreditation_number"]
        name = clean(b["organization"])
        if not scopes:
            review.append(f"body {number} {name}: no importable scheme; not imported")
            continue
        for std, rows in rows_by_std.items():
            limited = []
            for code, row in sorted(rows.items()):
                if usual.get(code) and tuple(row.tokens) not in usual[code]:
                    limited.append((code, row.nace))
            if limited and std in scopes:
                codes, note = scopes[std]
                detail = "; ".join(f"EA {c}: NACE {n}" for c, n in limited)
                scopes[std] = (codes, "; ".join(filter(None, [note, f"Limited scope (part of the sector) "
                                                                    f"for EA {', '.join(str(c) for c, _ in limited)} "
                                                                    f"({detail})"])))
                review.append(f"{number} {name}: {std} narrower NACE than usual for {detail}")

        cert_date = re.search(r"Certyfikatu Akredytacji Nr AC \d+ z dnia (\d{2})\.(\d{2})\.(\d{4})", text)
        issue = pl_date(*cert_date.groups()) if cert_date else b.get("granted_on", "")
        cycle = re.search(r"Cykl akredytacji od [\d.]+\s*(?:r\.)?\s*do (\d{2})\.(\d{2})\.(\d{4})", text)
        expiry = b.get("valid_until", "")
        if cycle and pl_date(*cycle.groups()) != expiry:
            review.append(f"{number} {name}: register valid until {expiry}, annex cycle ends "
                          f"{pl_date(*cycle.groups())}; register date used")
        url = quote(b["detail_url"], safe=":/,%")
        by_acc: dict[str, list[str]] = defaultdict(list)
        for std in scopes:
            by_acc[SCHEME_ROWS.get(std, (BASE, ""))[0]].append(std)
        by_acc.setdefault(BASE, [])  # search needs the 17021-1 row; PCA grants it to every AC body
        for acc_std, stds in by_acc.items():
            suffix = next((sfx for a, sfx in SCHEME_ROWS.values() if a == acc_std), "")
            cert = number + suffix
            accreditations.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": issue, "expiry_date": expiry, "proof_url": url})
            for std in stds:
                codes, note = scopes[std]
                scopes_out.append({"certificate_number": cert, "certification_standard": std,
                                   "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": note})
        body_rows.append({
            "name": name, "country": "Poland", "registration_no": "",
            "phone": phone(b.get("phone") or b.get("mobile") or ""),
            "email": b.get("email", "") if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", b.get("email", "")) else "",
            "website": website(b.get("website", "")),
            "address": clean(b.get("certification_body_address") or b["organization_address"]).replace(" ;", ",").replace(";", ","),
            "source_url": url, "verified_at": "",
        })

    names = Counter(r["name"] for r in body_rows)
    for n, c in names.items():
        if c > 1:
            review.append(f"body name {n} appears {c} times; the importer matches bodies by name")

    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda a: a["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes_out, key=lambda s: (s["certificate_number"], s["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scopes_out))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "pca_review.md", "w", encoding="utf-8") as f:
        f.write("# PCA (Poland) conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'pca_review.md'}")


def phone(raw: str) -> str:
    value = clean(raw)
    if not re.search(r"\d{3}", value):
        return ""
    return value if value.startswith("+") else "+48 " + value


def website(raw: str) -> str:
    value = clean(raw).rstrip("/")
    if not value or value == "-":
        return ""
    return value if value.startswith("http") else "https://" + value


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
