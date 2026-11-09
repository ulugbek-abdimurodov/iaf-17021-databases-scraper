#!/usr/bin/env python3
"""Turn the NAAU scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads naau_ms_certification_bodies/bodies.json and each body's scope annex PDF
(annexes/<certificate>/), whose tables are read with pdfplumber. An annex has one table
per kind of scope, each with the standard's name in the last column (a merged cell, so it
is printed on the first row of each standard's block and repeated after a page break):

- "Порядковий № напрямку галузі економіки" (ISO 9001 / 14001 / 45001, EN 15224): the
  number is the IAF / EA sector code 1-39 and the name is the EA sector's Ukrainian name,
  so no conversion is needed. A name that narrows the sector ("Обмежено до …", or a KVED
  code list in brackets) makes a limited scope.
- "Код категорії харчового ланцюга" (ISO 22000): ISO 22003-1 food chain categories A-K,
  classified to EA with the table of the BAS / ESYD / TÜRKAK datasets.
- "Технічна зона" (ISO 50001): ISO 50003 technical areas, classified with the ESYD table.
- "Загальна технічна галузь" (ISO 13485): IAF MD 8 main technical areas, classified with
  the ESYD table.
- A table with only the standard's name (ISO 37001, ISO/IEC 27001, ISO 22716): no sector
  list, recorded for all EA sectors.
- "Назва та позначення технічного регламенту" tables are notified-body modules of
  Ukrainian technical regulations, not management-system standards, and are left out.

Annexes that are scans without text are classified by hand in MANUAL (active bodies) or
left without scope rows (suspended bodies, which search does not show anyway).

Run:  python prepare_certifind.py  [--data naau_ms_certification_bodies]
                                   [--out ../../certifind/data/naau-ukraine]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bas = _load("bas_prepare", HERE.parent / "bulgaria" / "prepare_certifind.py")
esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "NAAU"
COUNTRY = "Ukraine"
REGISTER_URL = "https://naau.org.ua/en/3-reiestr-akreditovanikh-oov"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

STATUSES = {"active": "ACTIVE", "suspended": "SUSPENDED", "expired": "WITHDRAWN", "cancelled": "WITHDRAWN"}

# Standard named in a cell -> certification standard. The earliest match in the cell wins.
STANDARD_PATTERNS = [
    ("ISO 9001", r"ISO\s*9001"), ("ISO 14001", r"ISO\s*14001"), ("ISO 45001", r"ISO\s*45001"),
    ("ISO 22000", r"ISO\s*22000"), ("ISO 50001", r"ISO\s*50001"), ("ISO 13485", r"ISO\s*13485"),
    ("ISO 37001", r"ISO\s*37001"), ("ISO/IEC 27001", r"27001"), ("ISO 22716", r"ISO\s*22716"),
    ("ISO 29001", r"29001"), ("EN 15224", r"EN\s*15224"), ("AQAP-2110", r"AQAP"),
]
# Certification standard -> (accreditation standard, certificate suffix), as in the BAS dataset.
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")
EXCLUDED_SCHEMES = {
    "AQAP-2110": "NATO AQAP-2110 defence quality assurance requirements, not an ISO management-system standard",
}
ALL_NOTE = "No sector list in annex; recorded for all EA sectors"

# ISO 50003 technical areas by the Ukrainian names NAAU prints -> ESYD ENERGY_AREAS letter.
ENERGY_ZONES = [
    (r"легка", "A"), (r"важка", "B"), (r"будівельн\w* комплекс", "D"), (r"будівл", "C"),
    (r"транспорт", "E"), (r"гірни", "F"), (r"сільськ", "G"), (r"енерго|постачання енерг", "H"),
]
# IAF MD 8 main technical areas by the Ukrainian names -> ESYD MEDICAL_AREAS name.
MEDICAL_ZONES = [
    (r"неактивн", "Non-active medical devices"),
    (r"активн\w* медичн\w* (?:вироби|прилади),? які імплантую?ть", "Active implantable medical devices"),
    (r"активн", "Active (non-implantable) medical devices"),
    (r"in vitro|діагностик|лабораторн", "In vitro diagnostic medical devices"),
    (r"стериліз", "Sterilization methods"),
    (r"речовин|технолог", "Devices incorporating specific substances / technologies"),
    (r"частини", "Parts or services"),
]
ENERGY = {letter: (names[0], codes) for letter, names, codes in esyd.ENERGY_AREAS}
MEDICAL = {name: codes for name, _, codes in esyd.MEDICAL_AREAS}
LOOKALIKES = str.maketrans("АВСЕНКІ", "ABCEHKI")
CYRILLIC_TO_LATIN = str.maketrans("АВСЕНКМОРТХІасеорхі", "ABCEHKMOPTXIaceopxi")

# Scanned annexes (no text layer) of active bodies, read from the PDF by hand. Same kinds of
# entries the parser collects: EA codes, food chain letters, IAF MD 8 main areas.
MEDICAL_SIX = ["Non-active medical devices", "Active (non-implantable) medical devices",
               "Active implantable medical devices", "In vitro diagnostic medical devices",
               "Sterilization methods", "Devices incorporating specific substances / technologies"]
MANUAL: dict[str, dict[str, dict[str, list]]] = {
    # Annex of 07.04.2024, 1 page.
    "8O011": {"ISO 9001": {"ea": [14, 17, 18, 19, 28, 33, 34]}},
    # Annex of 23.04.2024, 3 pages.
    "8O043": {"ISO 9001": {"ea": [3, 4, 7, 9, 12, 14, 15, 17, 18, 19, 28, 29, 34, 35, 36, 37, 38]},
              "ISO 14001": {"ea": [7, 12, 14, 17, 18, 19, 28, 34]},
              "ISO 45001": {"ea": [18, 19, 28, 34]},
              "ISO 22000": {"food": ["C", "F", "G", "I"]}},
    # Annex of 29.03.2024, 9 pages; pages 3-9 are technical-regulation modules (left out).
    "8O047": {"ISO 13485": {"medical": MEDICAL_SIX}},
    # Annex of 29.03.2024, 7 pages; the rest are technical-regulation modules (left out).
    "8O070": {"ISO 13485": {"medical": MEDICAL_SIX}, "ISO 9001": {"ea": [38]}},
}

# Limited-scope sector names as the annexes print them -> English, for the scope note.
LIMITED_EN: dict[str, str] = {
    "Обмежено до «Виробництво паперу та картону»": "limited to manufacture of paper and paperboard",
    "Обмежено до “Виготовлення виробів з паперу та картону”":
        "limited to manufacture of articles of paper and paperboard",
    "Інше виробництво, не віднесене до перелічених угруповань (Виробництво меблів, код КВЕД 31)":
        "limited to manufacture of furniture, NACE 31",
    "Інше виробництво, не віднесене до перелічених угруповань (меблі)": "limited to furniture",
    "Будівництво (Інші будівельно-монтажні роботи, код КВЕД 43.29; Монтаж водопровідних мереж, "
    "систем опалення та кондиціонування, код КВЕД 43.22; Інші спеціалізовані будівельні роботи, "
    "н.в.і.у., код КВЕД 43.99)":
        "limited to other construction installation, NACE 43.29; plumbing, heat and air-conditioning "
        "installation, NACE 43.22; other specialised construction activities n.e.c., NACE 43.99",
}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def detect(text: str) -> str | None:
    hits = [(m.start(), std) for std, pat in STANDARD_PATTERNS if (m := re.search(pat, text))]
    return min(hits)[1] if hits else None


PHONE = re.compile(r"\(\s*0?(\d{2,5})\s*\)[\s-]*([\d][\d\s-]*)|(?<![\d(])0(\d{2})[\s-]+(\d[\d\s-]*)")


def phone(raw: str) -> str:
    """The first complete Ukrainian number: '(044) 285-83-83 490-27-41' -> '+380 44 285 83 83'.
    Area code and subscriber number make 9 digits; a number with more or fewer is not used."""
    for m in PHONE.finditer(raw or ""):
        area, rest = (m[1], m[2]) if m[1] else (m[3], m[4])
        need, taken = 9 - len(area), ""
        for i, ch in enumerate(rest):
            taken += ch
            if len(re.sub(r"\D", "", taken)) == need:
                if not (i + 1 < len(rest) and rest[i + 1].isdigit()):
                    return f"+380 {area} {clean(taken.replace('-', ' '))}"
                break
    # Written without brackets: '+380504110964', '0443213263', '+38050-97-999-48'.
    for chunk in re.findall(r"\+?[\d -]{10,}", raw or ""):
        digits = re.sub(r"\D", "", chunk)
        digits = re.sub(r"^(?:380|0)", "", digits)
        if len(digits) == 9:
            return f"+380 {digits[:2]} {digits[2:5]} {digits[5:7]} {digits[7:]}"
    return ""


class Section:
    def __init__(self, standard: str) -> None:
        self.standard = standard
        self.ea: set[int] = set()
        self.limited: dict[int, str] = {}
        self.food: list[str] = []
        self.energy: list[str] = []
        self.medical: list[str] = []
        self.unparsed: list[str] = []

    def codes_and_note(self) -> tuple[str, str]:
        if self.food:
            codes = set()
            for c in self.food:
                codes |= bas.expand(bas.FOOD_CATEGORIES[c])
            return bas.ea_spec(codes), (f"ISO 22003-1 categories {', '.join(sorted(set(self.food)))} "
                                        "(classified to EA by sector)")
        if self.energy:
            codes = set()
            for c in self.energy:
                codes |= bas.expand(ENERGY[c][1])
            names = ", ".join(f"{c} ({ENERGY[c][0]})" for c in sorted(set(self.energy)))
            return bas.ea_spec(codes), f"ISO 50003 technical areas {names} (classified to EA by sector)"
        if self.medical:
            codes = set()
            for m in self.medical:
                codes |= bas.expand(MEDICAL[m])
            names = "; ".join(dict.fromkeys(self.medical))
            return bas.ea_spec(codes), f"IAF MD 8 main technical areas: {names} (classified to EA by sector)"
        if self.ea:
            note = ""
            if self.limited:
                parts = [f"EA {ea} ({LIMITED_EN.get(t, t)})" for ea, t in sorted(self.limited.items())]
                note = "Limited scope (part of the sector): " + "; ".join(parts)
            return bas.ea_spec(self.ea), note
        return "ALL", ALL_NOTE


TABLE_KINDS = [
    ("ea", r"напрямку|галузі економіки"),
    ("food", r"харчового ланцюга"),
    ("energy", r"^Технічна зона"),
    ("medical", r"Загальна технічна галузь"),
    ("regulation", r"технічного регламенту|^№ з/п$|^№$|^з/п$"),
    ("none", r"^Позначення та назва НД"),
]
EA_LIMITED = re.compile(r"Обмежено|обмежено|КВЕД|\(")


def standards_in(text: str) -> list[str]:
    """Every standard a cell names, in order. EN 15224's title ("EN ISO 9001:2015 for
    healthcare") is not an ISO 9001 mention."""
    text = HEALTHCARE_TITLE.sub("", text)
    hits = sorted((m.start(), std) for std, pat in STANDARD_PATTERNS if (m := re.search(pat, text)))
    return [std for _, std in hits]


HEALTHCARE_TITLE = re.compile(r"(?:EN\s*)?ISO\s*9001:\s*\d{4}\s*(?:у\s+сфері\s+охорони|for\s+health)", re.I)
SKIP_ROW = re.compile(r"^(?:Реєстраційний номер ООВ|Реєстраційний номер заявки|Н А А У)$")


def parse_annex(pdf: Path) -> tuple[dict[str, Section], list[str]]:
    """Walk the annex tables row by row. A header row sets the table kind (a header repeated
    on the next page keeps the current standard); the standard cell, merged over a block of
    rows, is read from the first row of the block and kept until another one appears."""
    sections: dict[str, Section] = {}
    notes: list[str] = []
    kind, standards = None, []

    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [clean(c) for c in raw]
                    filled = [c for c in cells if c]
                    if not filled or SKIP_ROW.match(filled[0]):
                        continue
                    new_kind = next((k for k, pat in TABLE_KINDS if re.search(pat, filled[0])), None)
                    if new_kind:
                        if new_kind != kind:
                            standards = []
                        kind = new_kind
                        continue
                    if len(filled) > 1 and all(re.fullmatch(r"\d\.?|1 1", c) for c in filled):
                        continue          # column numbers "1 | 2 | 3"
                    if kind == "regulation":
                        continue
                    if kind == "none" or len(filled) == 1:
                        # A standard-only table (no sector list), or the rest of a merged
                        # standard cell printed as its own row.
                        found = standards_in(" ".join(filled))
                        if found and kind == "none":
                            standards = found
                            for std in found:
                                sections.setdefault(std, Section(std))
                        elif found and not set(found) <= set(standards):
                            standards = found
                        elif not found and kind != "none" and standards:
                            # A lone sector cell (e.g. a second technical area with the
                            # merged standard cell above it); anything else is cell overflow.
                            for std in standards:
                                add_row(sections[std], kind, cells, filled, lone=True)
                        continue
                    min_cells = 2 if kind == "energy" else 3
                    if len(filled) >= min_cells and (found := standards_in(filled[-1])):
                        standards = found
                    if not standards:
                        notes.append(f"row before any standard: {' | '.join(filled)[:120]}")
                        continue
                    for std in standards:
                        sec = sections.setdefault(std, Section(std))
                        add_row(sec, kind, cells, filled)
    return sections, notes


class _Quiet:
    """A Section whose unparsed rows are dropped (for lone cells that are cell overflow)."""

    def __init__(self, sec: Section) -> None:
        self.__dict__.update(sec.__dict__)
        self.unparsed = []


def add_row(sec: Section, kind: str, cells: list[str], filled: list[str], lone: bool = False) -> None:
    text = " | ".join(filled)[:120]
    if lone:
        sec = _Quiet(sec)
    code = filled[0]
    if kind == "ea":
        if re.fullmatch(r"\d{1,2}", code) and 1 <= int(code) <= 39:
            ea = int(code)
            sec.ea.add(ea)
            name = filled[1] if len(filled) > 1 else ""
            if EA_LIMITED.search(name):
                sec.limited[ea] = name
        else:
            sec.unparsed.append(text)
    elif kind == "food":
        letter = code.translate(LOOKALIKES)
        if re.fullmatch(r"[A-K]", letter):
            sec.food.append(letter)
        else:
            sec.unparsed.append(text)
    elif kind == "energy":
        zone = next((z for pat, z in ENERGY_ZONES if re.search(pat, code, re.I)), None)
        if zone:
            sec.energy.append(zone)
        else:
            sec.unparsed.append(text)
    elif kind == "medical":
        general = cells[0]          # positional: the main area column is often empty
        if general:
            area = next((a for pat, a in MEDICAL_ZONES if re.search(pat, general, re.I)), None)
            if area:
                sec.medical.append(area)
            else:
                sec.unparsed.append(text)
    else:
        sec.unparsed.append(f"[{kind}] {text}")


def annex_pdf(folder: Path) -> Path | None:
    """The scope annex with a text layer: the 'scope' link first, else the 'scan' link."""
    if not folder.is_dir():
        return None
    for kind in ("scope", "scan"):
        for pdf in sorted(folder.glob(f"*_{kind}_*.pdf")):
            if pdf.with_suffix(".txt").exists():
                with pdfplumber.open(pdf) as doc:
                    if any(page.extract_tables() for page in doc.pages[:2]):
                        return pdf
    return None


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def body_name(entry: dict) -> str:
    name = clean(entry["name_en"]).replace("“", "\"").replace("”", "\"").replace("„", "\"")
    # Cyrillic letters typed inside Latin words ('Сonformity', 'Сollective').
    return re.sub(r"[А-Яа-яІі](?=[A-Za-z])|(?<=[A-Za-z])[А-Яа-яІі]",
                  lambda m: m[0].translate(CYRILLIC_TO_LATIN), name)


def run(args: argparse.Namespace) -> int:
    entries = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    review: dict[str, list[str]] = defaultdict(list)
    bodies, accreditations, scopes = [], [], []

    for entry in sorted(entries, key=lambda e: e["certificate_no"]):
        cert = entry["certificate_no"]
        status = STATUSES[entry["status"]]
        name = body_name(entry)
        proof = entry["scope_url"] or entry["scan_url"] or REGISTER_URL
        bodies.append({"name": name, "country": COUNTRY, "registration_no": "", "phone": phone(entry["phones"]),
                       "email": "", "website": "", "address": "", "source_url": REGISTER_URL, "verified_at": ""})
        if entry["phones"] and not phone(entry["phones"]):
            review["Contacts"].append(f"{cert}: phone '{entry['phones']}' not understood; left empty")

        sections: dict[str, Section] = {}
        manual = MANUAL.get(cert)
        if status == "WITHDRAWN":
            review["Withdrawn"].append(f"{cert} {name}: register status '{entry['status']}' -> WITHDRAWN, "
                                       "no scopes written")
        elif manual is not None:
            review["Scanned annexes classified by hand"].append(f"{cert} {name}")
        else:
            pdf = annex_pdf(args.data / "annexes" / cert)
            if pdf is None:
                review["No readable annex (no scope rows)"].append(f"{cert} {name} ({entry['status']})")
            else:
                sections, notes = parse_annex(pdf)
                for n in notes:
                    review["Parser notes"].append(f"{cert}: {n}")

        rows: list[tuple[str, str, str]] = []
        if manual is not None and status != "WITHDRAWN":
            for std, data in manual.items():
                sec = sections.setdefault(std, Section(std))
                sec.ea |= set(data.get("ea", []))
                sec.food += data.get("food", [])
                sec.medical += data.get("medical", [])
        for std, sec in sections.items():
            if std in EXCLUDED_SCHEMES:
                review["Excluded schemes"].append(f"{cert}: {std} – {EXCLUDED_SCHEMES[std]}")
                continue
            for u in sec.unparsed:
                review["Unparsed rows"].append(f"{cert} {std}: {u}")
            codes, note = sec.codes_and_note()
            if codes == "ALL":
                review["Recorded as ALL"].append(f"{cert} {std}")
            for ea, text in sec.limited.items():
                review["Limited scopes"].append(f"{cert} {std} EA {ea}: {text}")
            rows.append((std, codes, note))

        # Standards in the register summary but not in the annex.
        listed = {std for std, _, _ in rows} | {s for s in sections}
        summary = {s for s in (detect(p) for p in re.split(r";", entry["standards_iso"])) if s}
        if status != "WITHDRAWN" and (sections or manual) and summary - listed:
            review["Register lists standards the annex does not"].append(
                f"{cert}: {', '.join(sorted(summary - listed))}")

        # Every entry is a 17021-1 accreditation (the register is the 17021-1 register), and
        # search requires it as the base of the scheme accreditations, so it is always written.
        schemes_used = sorted({SCHEMES.get(std, DEFAULT_SCHEME) for std, _, _ in rows} | {DEFAULT_SCHEME})
        for acc_std, suffix in schemes_used:
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": cert + suffix, "body_name": name,
                "accreditation_standard": acc_std, "status": status,
                "issue_date": entry["first_accredited"], "expiry_date": entry["current_valid_to"],
                "proof_url": proof})
        for std, codes, note in rows:
            suffix = SCHEMES.get(std, DEFAULT_SCHEME)[1]
            scopes.append({"certificate_number": cert + suffix, "certification_standard": std,
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
    out = [f"# NAAU dataset review", "", f"{len(bodies)} bodies, {len(accreditations)} accreditations, "
           f"{len(scopes)} scopes", ""]
    for name, items in review.items():
        out += [f"## {name} ({len(items)})", "", *[f"- {i}" for i in items], ""]
    args.review.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:3]))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=HERE / "naau_ms_certification_bodies")
    p.add_argument("--out", type=Path, default=HERE.parent.parent / "certifind" / "data" / "naau-ukraine")
    p.add_argument("--review", type=Path, default=HERE / "naau_review.md")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
