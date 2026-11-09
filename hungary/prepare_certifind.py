#!/usr/bin/env python3
"""Convert the NAH (Nemzeti Akkreditáló Hatóság, Hungary) management-system scrape into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by nah_scraper.py (organizations.csv, documents.csv and the
"Részletező Okirat" annex PDFs). Each NAH registration number is one accredited status with
its own validity; its current annex lists the certification standards and, per standard,
the IAF sectors (ISO 9001 / 14001 / 45001), ISO 22003-1 food chain categories (ISO 22000),
ISO 50003 technical areas (ISO 50001) or IAF MD 8 technical areas (ISO 13485).

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Needs pdftotext (poppler) on PATH. Open points are written to nah_review.md next to this
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

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "NAH"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the NAH annex; recorded for all EA sectors"

# Standard number in the annex -> (CertiFind certification standard, kind of sector list).
STANDARDS = {
    "9001": ("ISO 9001", "iaf"), "14001": ("ISO 14001", "iaf"), "45001": ("ISO 45001", "iaf"),
    "22000": ("ISO 22000", "food"), "50001": ("ISO 50001", "energy"),
    "13485": ("ISO 13485", "medical"),
    "27001": ("ISO/IEC 27001", "all"), "37001": ("ISO 37001", "all"),
    "22301": ("ISO 22301", "all"), "20000-1": ("ISO/IEC 20000-1", "all"),
    "42001": ("ISO/IEC 42001", "all"), "19443": ("ISO 19443", "all"),
    "56001": ("ISO 56001", "all"),
    "3834-1": ("ISO 3834", "all"), "3834-2": ("ISO 3834", "all"),
    "3834-3": ("ISO 3834", "all"), "3834-4": ("ISO 3834", "all"),
    # Known but not in CertiFind's standards: opens a section so its text is not misread.
    "22163": (None, "skip"),
}
# Certification standard -> (accreditation standard, certificate-number suffix). Everything
# else is certified under the ISO/IEC 17021-1 row with the plain NAH number.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
}
# Schemes named only in the listing that CertiFind has no standard for.
SKIPPED_SCHEMES = {
    "MEES": "Magyar Egészségügyi Ellátási Standardok (Hungarian health-care standards)",
    "MER": "Magyar Erdőtanúsítási Rendszer (Hungarian forest management certification)",
    "22163": "ISO/TS 22163 railway quality management (not in CertiFind's standards)",
    "PED": "2014/68/EU pressure equipment directive, module H (notified-body activity)",
}

STD_RE = re.compile(r"(?:ISO|IEC)(?:\s*/\s*(?:IEC|TS))?\s*(?:TS\s*)?(\d{4,5}(?:-\d+)?)\s*:")
HEADER_WORDS = re.compile(r"szabv|szerint|standard", re.I)
SCOPE_START = re.compile(r"(?:\d\)\s*)?(?:Az akkreditált terület|Detailed scope of accreditation)\s*:")
SCOPE_END = re.compile(r"Az aktuális akkreditált státuszra|Data on the current accredited status")
# An IAF row: the code sits in the left column; NACE continuation lines are indented far more.
IAF_ROW = re.compile(r"^\s{0,14}(\d{1,2})(?=\s|,|$)")
ROMAN_HEADING = re.compile(r"^\s{0,8}[IVX]{1,4}\.\s+[A-ZÁÉÍÓÖŐÚÜŰ]")
FOOTNOTE = re.compile(r"Hatóság|határozat|kiadott|Authority", re.I)
MEDICAL_HEADING = re.compile(r"(?<![\d.])(?:A\.)?1\.([1-7])\.?(?=\s|[A-ZÁÉÍÓÖŐÚÜŰ])")
MEDICAL_AREAS = {1: "Non-active medical devices", 2: "Active (non-implantable) medical devices",
                 3: "Active implantable medical devices", 4: "In vitro diagnostic medical devices",
                 5: "Sterilization methods",
                 6: "Devices incorporating specific substances / technologies",
                 7: "Parts or services"}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
# ISO 50003 technical areas by the names NAH prints (case-sensitive: descriptions reuse words).
ENERGY_WORDS = [("A", r"Könnyű"), ("B", r"Nehézipar"), ("C", r"Épületek\b"),
                ("D", r"Épületkomplexum"), ("E", r"\bSzállítás\b|Közlekedés"),
                ("F", r"\bBányászat"), ("G", r"\bMezőgazdaság"), ("H", r"\bEnergiaellátás")]
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
# ISO 22003-1 food chain categories by their Hungarian names.
FOOD_WORDS = [("A", r"Állattenyésztés|Állattartás"), ("B", r"Növénytermesztés|Gabona és hüvelyes"),
              ("C", r"Romlandó|Állati tetemek|Szobahőmérsékleten"), ("D", r"Takarmány és állati"),
              ("E", r"Vendéglátás"), ("F", r"Nagykereskedelem|Élelmiszer-ügynökség"),
              ("G", r"Szállítási és raktározási"), ("H", r"\bSzolgáltatások\b"),
              ("I", r"Csomagolóanyag"), ("J", r"Berendezésgyártás"), ("K", r"biokémiai|Biokémia")]

# Registration numbers whose annex has no section heading: the standard follows from the
# 17021 part named in the annex (-2 environment, -3 quality, TS -10 OH&S).
PART_STANDARD = {"17021-2": "ISO 14001", "17021-3": "ISO 9001", "17021-10": "ISO 45001"}

# Body names: NAH lists branch offices under the legal entity's name; they are merged.
DISPLAY = {
    "bureauveritasmagyarorszagkft": "BUREAU VERITAS Magyarország Kft.",
    "dekraticvizsgaloellenorzotanusitokft": "DEKRA TIC Vizsgáló, Ellenőrző, Tanúsító Kft.",
    "tamcertmagyarorszagvizsgaloestanusitokft": "TAM CERT Magyarország Vizsgáló és Tanúsító Kft.",
    "neoemkinemzetiorvostechnikaieszkoz":
        "NEOEMKI Nemzeti Orvostechnikai Eszköz Megfelelőségértékelő és Tanúsító Kft.",
    "internationalcerthungaryszolgaltatokft": "INTERNATIONAL CERT Hungary Szolgáltató Kft.",
    "mainstateserviceturkmenstandardlary":
        "Main State Service „Turkmenstandardlary” (Turkmen Standards Information Centre)",
}
COUNTRY = {"mainstateserviceturkmenstandardlary": "Turkmenistan"}
PHONE_OVERRIDE = {"mainstateserviceturkmenstandardlary": "+993 12 392-591"}

ACCENTS = str.maketrans("áéíóöőúüűÁÉÍÓÖŐÚÜŰ", "aeiooouuuAEIOOOUUU")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def body_key(name: str) -> str:
    first = name.split("\n")[0]
    return re.sub(r"[^a-z0-9]", "", first.translate(ACCENTS).casefold())


def display_name(raw: str) -> str:
    key = body_key(raw)
    return DISPLAY.get(key, clean(raw.split("\n")[0]).rstrip(" ,"))


def phone(raw: str, key: str) -> str:
    if key in PHONE_OVERRIDE:
        return PHONE_OVERRIDE[key]
    value = clean(raw).replace("+ ", "+")
    return value if re.fullmatch(r"\+[0-9][0-9 ()/-]{5,}", value) else ""


def email(raw: str) -> str:
    value = clean(raw)
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else ""


def website(raw: str) -> str:
    value = clean(raw).rstrip("/")
    if not value or value == "-":
        return ""
    return value if value.startswith("http") else "https://" + value


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


# --------------------------------------------------------------------------- annex parsing
class Section:
    def __init__(self, number: str, header: str):
        self.number = number
        self.standard, self.kind = STANDARDS[number]
        self.header = header
        self.lines: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def pdf_text(pdf: Path) -> str:
    out = subprocess.run([PDFTOTEXT, "-enc", "UTF-8", "-layout", str(pdf), "-"],
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace")


def accreditation_parts(text: str) -> set[str]:
    head = text[:SCOPE_START.search(text).start()] if SCOPE_START.search(text) else text[:3000]
    return set(re.findall(r"17021-\d+", head))


def split_sections(text: str) -> list[Section]:
    m = SCOPE_START.search(text)
    body = text[m.end():] if m else text
    e = SCOPE_END.search(body)
    body = body[:e.start()] if e else body
    lines = body.splitlines()
    # A heading broken after "ISO" continues on the next line ("... az MSZ ISO" / "45001:2018").
    joined: list[str] = []
    for line in lines:
        if joined and re.search(r"\b(ISO|ISO/IEC|EN|MSZ)\s*$", joined[-1]) and re.match(r"\s*\d{4,5}", line):
            joined[-1] = joined[-1].rstrip() + " " + line.strip()
        else:
            joined.append(line)
    sections: list[Section] = []
    for i, line in enumerate(joined):
        s = line.strip()
        if not s or s.startswith(("Budapest,", "NAD-")):
            continue
        numbers = [n for n in STD_RE.findall(s) if n in STANDARDS]
        # "szabvány szerint" often wraps to the next line; the railway title quotes ISO 9001.
        nxt = next((x for x in joined[i + 1:i + 4] if x.strip()), "")
        if (numbers and HEADER_WORDS.search(s + " " + nxt) and not IAF_ROW.match(line)
                and "vasúti" not in s):
            sections.append(Section(numbers[0], s))
            continue
        if ROMAN_HEADING.match(line) and not numbers:
            # Heading of a scheme without an ISO number (MEES, ...): ends the open section.
            # When its standard follows on the next line, that line opens the new section.
            sections.append(Section("22163", s))
            continue
        if sections:
            sections[-1].lines.append(line)
    return sections


def iaf_codes(section: Section) -> set[int]:
    codes = set()
    for line in section.lines:
        if FOOTNOTE.search(line):
            continue
        m = IAF_ROW.match(line)
        if m and 1 <= int(m.group(1)) <= 39:
            codes.add(int(m.group(1)))
    return codes


def iaf_codes_unsectioned(text: str) -> set[int]:
    m = SCOPE_START.search(text)
    body = text[m.end():] if m else text
    e = SCOPE_END.search(body)
    probe = Section("9001", "")
    probe.lines = (body[:e.start()] if e else body).splitlines()
    return iaf_codes(probe)


def food_scope(section: Section) -> tuple[set[int], str]:
    letters = [l for l, pattern in FOOD_WORDS if re.search(pattern, section.text)]
    codes = set().union(*(esyd.expand(esyd.FOOD_CATEGORIES[l]) for l in letters)) if letters else set()
    return codes, f"ISO 22003-1 categories {', '.join(letters)} (classified to EA by sector)"


def energy_scope(section: Section) -> tuple[set[int], str]:
    letters = [l for l, pattern in ENERGY_WORDS if re.search(pattern, section.text)]
    codes = set().union(*(esyd.expand(ENERGY_EA[l]) for l in letters)) if letters else set()
    names = "; ".join(f"{l} {ENERGY_NAMES[l]}" for l in letters)
    return codes, f"ISO 50003 technical areas {names} (classified to EA by sector)"


def medical_scope(text: str) -> tuple[set[int], str]:
    areas = sorted({int(n) for n in MEDICAL_HEADING.findall(text)})
    names = [MEDICAL_AREAS[a] for a in areas]
    codes = set().union(*(esyd.expand(MEDICAL_EA[n]) for n in names)) if names else set()
    return codes, f"IAF MD 8 main technical areas: {'; '.join(names)} (classified to EA by sector)"


def listing_standards(notes: str) -> set[str]:
    notes = re.sub(r"Vasúti alkalmazások.*?követelmények\)", "", notes, flags=re.S)
    found = {STANDARDS[n][0] for n in STD_RE.findall(notes.replace("\n", " ")) if n in STANDARDS}
    return {s for s in found if s}


def listing_skipped(notes: str) -> list[str]:
    out = []
    if "MEES" in notes:
        out.append("MEES")
    if "MER " in notes or "(MER)" in notes:
        out.append("MER")
    if "22163" in notes:
        out.append("22163")
    if "2014/68/EU" in notes:
        out.append("PED")
    return out


# ------------------------------------------------------------------------------------ main
# Rows whose sector name narrows the IAF sector (the NACE column alone does not show it).
LIMITED = {
    ("NAH-4-0161/2025", "ISO 9001"): {7: "pulp and paper manufacturing"},
    ("NAH-4-0161/2025", "ISO 14001"): {7: "pulp and paper manufacturing"},
    ("NAH-4-0161/2025", "ISO 45001"): {7: "pulp and paper manufacturing"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()

    orgs = list(csv.DictReader(open(args.scrape / "organizations.csv", encoding="utf-8-sig")))
    docs = list(csv.DictReader(open(args.scrape / "documents.csv", encoding="utf-8-sig")))
    current = {clean(d["nah_number"]): args.scrape / d["local_path"]
               for d in docs if d["is_current"] == "true" and d["download_status"] == "downloaded"}

    review: list[str] = []
    bodies: dict[str, dict] = {}
    body_entries: dict[str, list[dict]] = defaultdict(list)
    entries = []  # one per NAH number: dict with scopes per certification standard

    for o in orgs:
        number = clean(o["nah_number"])
        key = body_key(o["name"])
        name = display_name(o["name"])
        status = o["status"] if o["status"] in ("ACTIVE", "SUSPENDED", "WITHDRAWN") else "WITHDRAWN"
        entry = {"number": number, "key": key, "status": status, "issue": o["valid_from"],
                 "expiry": o["valid_to"], "url": clean(o["page_url"]), "scopes": {}}
        notes = o["scope_and_notes"]
        expected = listing_standards(notes)
        for skipped in listing_skipped(notes):
            review.append(f"{number} {name}: {SKIPPED_SCHEMES[skipped]} not imported")

        pdf = current.get(number)
        if status == "ACTIVE" and pdf is None:
            review.append(f"{number} {name}: listed ACTIVE but no current annex; no scopes")
        if pdf is not None:
            text = pdf_text(pdf)
            sections = split_sections(text)
            for sec in sections:
                if sec.kind == "skip" or sec.standard in entry["scopes"]:
                    continue
                if sec.kind == "iaf":
                    codes, note = iaf_codes(sec), ""
                elif sec.kind == "food":
                    codes, note = food_scope(sec)
                elif sec.kind == "energy":
                    codes, note = energy_scope(sec)
                elif sec.kind == "medical":
                    codes, note = medical_scope(sec.text)
                else:
                    codes, note = set(range(1, 40)), ALL_NOTE
                if not codes:
                    review.append(f"{number} {name}: {sec.standard} section has no sectors; not imported")
                    continue
                entry["scopes"][sec.standard] = (codes, note)
            if not sections:
                # Annex without section headings: a bare IAF table or a bare IAF MD 8 table.
                if MEDICAL_HEADING.search(text) and "ISO 13485" in expected:
                    entry["scopes"]["ISO 13485"] = medical_scope(text)
                    review.append(f"{number} {name}: annex has no heading; IAF MD 8 tables read as ISO 13485")
                else:
                    parts = [PART_STANDARD[p] for p in accreditation_parts(text) if p in PART_STANDARD]
                    codes = iaf_codes_unsectioned(text)
                    if len(parts) == 1 and codes:
                        entry["scopes"][parts[0]] = (codes, "")
                        review.append(f"{number} {name}: annex has no heading; IAF table read as "
                                      f"{parts[0]} (from the ISO/IEC 17021 part it names)")
            for std in sorted(expected - set(entry["scopes"])):
                review.append(f"{number} {name}: listing names {std} but the annex has no sector "
                              f"table for it; not imported")
        for std, (codes, note) in list(entry["scopes"].items()):
            if limits := LIMITED.get((number, std)):
                detail = "; ".join(f"EA {ea}: limited to {what}" for ea, what in sorted(limits.items()))
                entry["scopes"][std] = (codes, f"Limited scope (part of the sector) for EA "
                                               f"{', '.join(map(str, sorted(limits)))} ({detail})")
        entries.append(entry)
        body_entries[key].append(entry)
        bodies.setdefault(key, {"name": name, "rows": []})["rows"].append(o)

    # ---- accreditations and scopes
    accreditations, scopes = [], []
    today = args.today.isoformat()

    def valid(e: dict) -> bool:
        return e["status"] == "ACTIVE" and (not e["expiry"] or e["expiry"] >= today)

    kept_keys = set()
    for key, group in body_entries.items():
        name = bodies[key]["name"]
        if not any(e["scopes"] for e in group):
            review.append(f"body {name}: no importable scheme in any NAH status; not imported")
            continue
        kept_keys.add(key)
        for e in group:
            if not e["scopes"] and e["status"] == "ACTIVE":
                review.append(f"{e['number']} {name}: no importable scheme; no accreditation row")
        # Not currently valid: written as they are, so prune_inactive drops and logs them.
        for e in (e for e in group if e["scopes"] and not valid(e)):
            for std, (codes, note) in sorted(e["scopes"].items()):
                acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
                cert = e["number"] + suffix
                if cert not in {a["certificate_number"] for a in accreditations}:
                    accreditations.append(acc_row(cert, name, acc_std, e))
                scopes.append(scope_row(cert, std, codes, e, note))
        # Valid: CertiFind holds one accreditation per body and accreditation standard, so the
        # NAH statuses of one body are merged per accreditation standard (as in NABCB).
        live = sorted((e for e in group if e["scopes"] and valid(e)), key=lambda e: e["number"])
        if not live:
            continue
        by_standard: dict[str, list[tuple[dict, str]]] = defaultdict(list)
        for e in live:
            for std in e["scopes"]:
                by_standard[SCHEME_ROWS.get(std, (BASE, ""))[0]].append((e, std))
        base_only = not by_standard.get(BASE)
        if base_only:
            by_standard[BASE] = []  # search needs a 17021-1 row; NAH grants every status on it
        for acc_std, items in by_standard.items():
            group_entries = list({id(e): e for e, _ in items}.values()) or live[:1]
            primary = min(group_entries, key=lambda e: (
                next((i for i, s in enumerate(("ISO 9001", "ISO 14001", "ISO 45001")) if s in e["scopes"]), 3),
                e["number"]))
            suffix = next((sfx for s, (a, sfx) in SCHEME_ROWS.items() if a == acc_std), "")
            cert = primary["number"] + suffix
            merged = dict(primary, issue=min(e["issue"] for e in group_entries),
                          expiry=max(e["expiry"] for e in group_entries))
            accreditations.append(acc_row(cert, name, acc_std, merged))
            if len(group_entries) > 1:
                review.append(f"{name}: {acc_std} statuses {', '.join(e['number'] for e in group_entries)} "
                              f"merged under {cert}")
            rows: dict[str, list] = {}
            for e, std in items:
                codes, note = e["scopes"][std]
                if e is not primary:
                    note = "; ".join(filter(None, [note, f"Accredited under {e['number']}, valid "
                                                         f"{e['issue']} to {e['expiry']}"]))
                if std in rows:
                    rows[std][0] |= codes
                    rows[std][1] = "; ".join(filter(None, [rows[std][1], note]))
                    review.append(f"{name}: {std} appears in several NAH statuses; sectors combined")
                else:
                    rows[std] = [set(codes), note]
            for std, (codes, note) in sorted(rows.items()):
                scopes.append(scope_row(cert, std, codes, primary, note))

    body_rows = []
    for key in sorted(kept_keys, key=lambda k: bodies[k]["name"].casefold()):
        rows = bodies[key]["rows"]
        active = [r for r in rows if r["status"] == "ACTIVE"] or rows
        first = active[0]
        body_rows.append({
            "name": bodies[key]["name"],
            "country": COUNTRY.get(key, "Hungary"),
            "registration_no": "",
            "phone": next((p for r in active if (p := phone(r["phone"], key))), ""),
            "email": next((m for r in active if (m := email(r["email"]))), ""),
            "website": next((w for r in active if (w := website(r["web"]))), ""),
            "address": clean(first["location"]),
            "source_url": clean(first["page_url"]),
            "verified_at": "",
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

    with open(HERE / "nah_review.md", "w", encoding="utf-8") as f:
        f.write("# NAH (Hungary) conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'nah_review.md'}")


def acc_row(cert: str, body: str, standard: str, e: dict) -> dict:
    return {"ab_code": AB_CODE, "certificate_number": cert, "body_name": body,
            "accreditation_standard": standard, "status": e["status"], "issue_date": e["issue"],
            "expiry_date": e["expiry"], "proof_url": e["url"]}


def scope_row(cert: str, std: str, codes: set[int], e: dict, note: str) -> dict:
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
