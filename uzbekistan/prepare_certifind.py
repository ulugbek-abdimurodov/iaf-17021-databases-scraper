#!/usr/bin/env python3
"""Turn the O'ZAK (akkred.uz) scraper output into a CertiFind dataset (bodies.csv, accreditations.csv,
scopes.csv).

Reads akkred_uz_management_bodies/organizations.csv (register fields, Uzbek) and documents.csv (the
PDFs linked from each register entry). Each entry has two PDFs: the accreditation certificate (a scan,
no scope) and the scope annex ("Akkreditatsiyadan o'tkazish sohasi"), a text PDF read with pdfplumber.
Every annex page names one certification standard in its header ("Sertifikatlash standarti: O'z DSt
ISO 9001:2015") and holds one table, by the header row:

- "Iaf kodlari" (ISO 9001 / 14001 / 45001): IAF codes = EA codes. A row with "Неполный" coverage has
  activities excluded (last column) and is noted as a partial sector.
- "Kategoriya kodi" (ISO 22000): ISO 22003-1 food chain categories A-K, classified to EA with the ESYD
  table.
- "Texnik maydon kodi" (ISO 13485): IAF MD 9 technical area codes A1..G5; the letter gives the main
  area, classified to EA with the ESYD table.
- "Texnik soha" only: ISO 50001 -> ISO 50003 technical areas by their Russian names (ESYD table);
  ISO/IEC 27001 and ISO 37001 have no sector list -> all EA sectors.

The register's folders sometimes hold stray copies of another body's PDF, so only the files listed
for the body in documents.csv are read.

Run:  python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "OZAK"
REGISTER_URL = "https://akkred.uz/uz/reestr?type_std=20"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Register status (Uzbek) -> CertiFind status.
STATUSES = {"Amaldagi": "ACTIVE", "To'xtagan": "SUSPENDED", "Tugagan": "WITHDRAWN",
            "Muddati tugagan": "WITHDRAWN"}
MONTHS = {"yan": 1, "fev": 2, "mar": 3, "apr": 4, "may": 5, "iyn": 6, "iyl": 7, "avg": 8,
          "sen": 9, "okt": 10, "noy": 11, "dek": 12}

STANDARD_PATTERNS = [
    ("ISO 9001", r"ISO\s*9001"), ("ISO 14001", r"ISO\s*14001"), ("ISO 45001", r"ISO\s*45001"),
    ("ISO 22000", r"ISO\s*22000"), ("ISO 50001", r"ISO\s*50001"), ("ISO 13485", r"ISO\s*13485"),
    ("ISO 37001", r"ISO\s*37001"), ("ISO/IEC 27001", r"27001"),
]
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")
ALL_NOTE = "No sector list in the O'ZAK annex; recorded for all EA sectors"

# ISO 50003 technical areas by the Russian names O'ZAK prints -> ESYD ENERGY_AREAS letter.
# "Энергосбережение" (energy saving) is printed once where the others print "Энергоснабжение".
ENERGY_ZONES = [
    (r"за исключением тяж|легк", "A"), (r"тяж", "B"), (r"комплекс", "D"), (r"здани", "C"),
    (r"транспорт", "E"), (r"горн", "F"), (r"сельск", "G"), (r"энергосна|энергосбер", "H"),
]
# IAF MD 9 technical area letter -> ESYD MEDICAL_AREAS name.
MEDICAL_LETTERS = {
    "A": "Non-active medical devices", "B": "Active (non-implantable) medical devices",
    "C": "Active implantable medical devices", "D": "In vitro diagnostic medical devices",
    "E": "Sterilization methods", "F": "Devices incorporating specific substances / technologies",
    "G": "Parts or services",
}
ENERGY = {letter: (names[0], codes) for letter, names, codes in esyd.ENERGY_AREAS}
MEDICAL = {name: codes for name, _, codes in esyd.MEDICAL_AREAS}
LOOKALIKES = str.maketrans("АВСЕНКІМОРТХ", "ABCEHKIMOPTX")

# Names the register prints in Uzbek / Russian only -> English name used in CertiFind.
NAMES = {
    "O'ZAK.MT.0023": "Uzbekistan Standards Institute (state institution)",
    "O'ZAK.MT.0031": "ACERT Bureau LLC",
    "O'ZAK.MT.0035": "Bishkek Center for Testing, Certification and Metrology",
    "O'ZAK.MT.0039": "Center for Safety of Pharmaceutical Products (state institution)",
}
LEGAL_FORMS = [
    (r"mas.u?i?liyati cheklangan jamiyat", "LLC"),
    (r"xususiy korxona", "Private Enterprise"),
    (r"davlat muassasa", "(state institution)"),
]
COUNTRIES = [(r"Qirg.iziston", "Kyrgyzstan"), (r"Sankt-Peterburg|Rossiya", "Russia")]
DIAL = {"Uzbekistan": "998", "Kyrgyzstan": "996", "Russia": "7"}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def register_date(value: str) -> str:
    m = re.fullmatch(r"(\d{1,2}) (\w+) (\d{4})", clean(value))
    if not m or m[2] not in MONTHS:
        return ""
    return date(int(m[3]), MONTHS[m[2]], int(m[1])).isoformat()


def body_name(cert: str, raw: str) -> str:
    if cert in NAMES:
        return NAMES[cert]
    m = re.search(r"[\"“«]([^\"”»]+)[\"”»]", raw)
    core = clean(m[1]) if m else clean(raw)
    form = next((f for pat, f in LEGAL_FORMS if re.search(pat, raw, re.I)), "")
    return f"{core} {form}".strip()


def country_of(address: str) -> str:
    return next((c for pat, c in COUNTRIES if re.search(pat, address)), "Uzbekistan")


def phone(raw: str, country: str) -> str:
    """The first number, in international form: '(+998 93) 184 10 15' -> '+998 93 184 10 15',
    '(0371) 233-22-07' -> '+998 71 233 22 07'."""
    first = re.split(r"[,;]", raw or "")[0]
    digits = re.sub(r"\D", "", first)
    if country == "Uzbekistan":
        digits = re.sub(r"^(?:998|0?3?(?=71\d{7}$))", "", digits)
        if len(digits) == 9:
            return f"+998 {digits[:2]} {digits[2:5]} {digits[5:7]} {digits[7:]}"
        return ""
    if country == "Kyrgyzstan" and digits.startswith("996") and len(digits) == 12:
        return f"+996 {digits[3:6]} {digits[6:9]} {digits[9:]}"
    if country == "Russia" and digits.startswith("7") and len(digits) == 11:
        return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"
    return ""


def website(raw: str) -> str:
    first = clean(re.split(r"[,\s]+", raw or "")[0]) if raw else ""
    if not first or first == "-":
        return ""
    return first if first.startswith("http") else "https://" + first


class Section:
    def __init__(self, standard: str) -> None:
        self.standard = standard
        self.ea: set[int] = set()
        self.partial: dict[int, str] = {}
        self.food: list[str] = []
        self.energy: list[str] = []
        self.medical: list[str] = []
        self.no_sectors = False
        self.unparsed: list[str] = []
        self.remarks: list[str] = []

    def codes_and_note(self) -> tuple[str, str]:
        if self.food:
            codes: set[int] = set()
            for c in self.food:
                codes |= esyd.expand(esyd.FOOD_CATEGORIES[c])
            return esyd.ea_spec(codes), (f"ISO 22003-1 categories {', '.join(sorted(set(self.food)))} "
                                         "(classified to EA by sector)")
        if self.energy:
            codes = set()
            for c in self.energy:
                codes |= esyd.expand(ENERGY[c][1])
            names = ", ".join(f"{c} ({ENERGY[c][0]})" for c in sorted(set(self.energy)))
            return esyd.ea_spec(codes), f"ISO 50003 technical areas {names} (classified to EA by sector)"
        if self.medical:
            codes = set()
            for m in self.medical:
                codes |= esyd.expand(MEDICAL[m])
            names = "; ".join(sorted(set(self.medical)))
            return esyd.ea_spec(codes), f"IAF MD 9 main technical areas: {names} (classified to EA by sector)"
        if self.ea:
            note = ""
            if self.partial:
                note = ("Partial scope (some activities excluded) for EA "
                        + ", ".join(str(e) for e in sorted(self.partial)))
            return esyd.ea_spec(self.ea), note
        return "ALL", ALL_NOTE


def detect(text: str) -> str | None:
    hits = [(m.start(), std) for std, pat in STANDARD_PATTERNS if (m := re.search(pat, text))]
    return min(hits)[1] if hits else None


def table_kind(header: list[str]) -> str | None:
    joined = " ".join(header)
    if "Iaf" in joined:
        return "ea"
    if "Kategoriya kodi" in joined:
        return "food"
    if "maydon kodi" in joined:
        return "medical"
    if "Texnik soha" in joined:
        return "texnik"
    return None


def parse_annex(pdf: Path, debug: bool = False) -> tuple[dict[str, Section], list[str]]:
    sections: dict[str, Section] = {}
    notes: list[str] = []
    with pdfplumber.open(pdf) as doc:
        for number, page in enumerate(doc.pages, 1):
            text = page.extract_text() or ""
            m = re.search(r"Sertifikatla\S* standarti:\s*(.+)", text)
            if not m:
                continue
            std = detect(m[1])
            if std is None:
                notes.append(f"page {number}: standard not recognised: {clean(m[1])}")
                continue
            sec = sections.setdefault(std, Section(std))
            kind = None
            for table in page.extract_tables():
                for raw in table:
                    cells = [clean(c) for c in raw]
                    if cells and cells[0] == "№":
                        kind = table_kind(cells)
                        if kind is None:
                            notes.append(f"page {number}: unknown table header {' | '.join(cells)}")
                        continue
                    if kind is None or not cells or not re.fullmatch(r"\d+", cells[0]):
                        continue
                    if debug:
                        print(f"  [{std} {kind}] {' | '.join(cells)[:140]}")
                    add_row(sec, kind, cells)
    return sections, notes


def add_row(sec: Section, kind: str, cells: list[str]) -> None:
    text = " | ".join(cells)[:140]
    if kind == "ea":
        code = cells[2] if len(cells) > 2 else ""
        # Printed as '28', 'MT.28' (0041) or '31**' (0022, footnote marker with no footnote).
        m = re.fullmatch(r"(?:MT\.)?(\d{1,2})(\**)", code)
        if m and 1 <= int(m[1]) <= 39:
            ea = int(m[1])
            sec.ea.add(ea)
            if code != m[1]:
                sec.remarks.append(f"IAF code printed as '{code}', read as {ea}")
            coverage = cells[3] if len(cells) > 3 else ""
            if re.search(r"не\s*полный|to.liq\s+emas", coverage, re.I):
                excluded = cells[4] if len(cells) > 4 and cells[4] not in ("", "-", "None") else "?"
                sec.partial[ea] = excluded
        else:
            sec.unparsed.append(text)
    elif kind == "food":
        letter = cells[1].translate(LOOKALIKES) if len(cells) > 1 else ""
        if re.fullmatch(r"[A-K]", letter):
            sec.food.append(letter)
        else:
            sec.unparsed.append(text)
    elif kind == "medical":
        letter = cells[-1].translate(LOOKALIKES)[:1]
        if letter in MEDICAL_LETTERS:
            sec.medical.append(MEDICAL_LETTERS[letter])
        else:
            sec.unparsed.append(text)
    elif kind == "texnik":
        name = cells[1] if len(cells) > 1 else ""
        if sec.standard == "ISO 50001":
            zone = next((z for pat, z in ENERGY_ZONES if re.search(pat, name, re.I)), None)
            if zone:
                sec.energy.append(zone)
                if re.search(r"энергосбер", name, re.I):
                    sec.remarks.append(f"'{name}' (energy saving) read as H (energy supply)")
            else:
                sec.unparsed.append(text)
        else:
            sec.no_sectors = True


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    scrape: Path = args.scrape
    orgs = list(csv.DictReader((scrape / "organizations.csv").open(encoding="utf-8-sig")))
    docs: dict[str, list[dict]] = defaultdict(list)
    for d in csv.DictReader((scrape / "documents.csv").open(encoding="utf-8-sig")):
        docs[d["registry_number"]].append(d)

    review: dict[str, list[str]] = defaultdict(list)
    bodies, accreditations, scopes = [], [], []
    names_seen: set[str] = set()

    for org in sorted(orgs, key=lambda o: o["registry_number"]):
        cert = org["registry_number"]
        status = STATUSES.get(org["status_list"])
        if status is None:
            review["Unknown register status (skipped)"].append(f"{cert}: {org['status_list']}")
            continue
        name = body_name(cert, org["organization_name"])
        if name in names_seen:
            review["Duplicate names"].append(f"{cert}: {name}")
            name = f"{name} ({cert})"
        names_seen.add(name)
        address = clean(org["Yuridik manzil"] or org["Akkreditatsiya subyektining manzili"])
        country = country_of(address)
        tel = phone(org["Telefon"], country)
        if org["Telefon"] and not tel:
            review["Contacts"].append(f"{cert}: phone '{org['Telefon']}' not understood; left empty")

        if status != "ACTIVE":
            review["Not active (dropped by prune)"].append(f"{cert} {name}: register status "
                                                          f"'{org['status_list']}' -> {status}")
            sections: dict[str, Section] = {}
            annex_url = ""
        else:
            sections, annex_url = {}, ""
            for d in docs.get(cert, []):
                path = scrape.parent / d["downloaded_file"].replace("\\", "/")
                if not path.exists():
                    review["Missing files"].append(f"{cert}: {d['downloaded_file']}")
                    continue
                found, notes = parse_annex(path, debug=cert in args.debug)
                for n in notes:
                    review["Parser notes"].append(f"{cert} {path.name}: {n}")
                if found:
                    sections.update(found)
                    annex_url = d["document_url"].split("#")[0]
            if not sections:
                review["No scope annex (body left out)"].append(
                    f"{cert} {name}: register links {len(docs.get(cert, []))} PDF(s), none is a scope annex; "
                    "accredited standards unknown")
                continue

        rows: list[tuple[str, str, str]] = []
        for std, sec in sections.items():
            for u in sec.unparsed:
                review["Unparsed rows"].append(f"{cert} {std}: {u}")
            codes, note = sec.codes_and_note()
            if codes == "ALL" and not sec.no_sectors:
                review["Sector table not understood (standard left out)"].append(f"{cert} {std}")
                continue
            if codes == "ALL":
                codes = "1-39"
                review["Recorded for all EA sectors"].append(f"{cert} {std}")
            for ea, excl in sorted(sec.partial.items()):
                review["Partial sectors (Неполный)"].append(f"{cert} {std} EA {ea}: excluded {excl}")
            for r in sec.remarks:
                review["Interpretation choices"].append(f"{cert} {std}: {r}")
            rows.append((std, codes, note))

        bodies.append({"name": name, "country": country, "registration_no": clean(org["STIR"]),
                       "phone": tel, "email": clean(org["Elektron pochta"].split(",")[0]).replace(" ", ""),
                       "website": website(org["Veb-sayt"]), "address": address,
                       "source_url": REGISTER_URL, "verified_at": ""})
        issue = register_date(org["Ilk akkreditatsiya sanasi"] or org["Akkreditatsiya sanasi"]
                              or org["Takroriy akkreditatsiya sanasi"])
        expiry = register_date(org["Akkreditatsiya to`g`risidagi guvohnomaning amal qilish muddati"])
        proof = annex_url or REGISTER_URL
        for acc_std, suffix in sorted({SCHEMES.get(s, DEFAULT_SCHEME) for s, _, _ in rows} | {DEFAULT_SCHEME}):
            accreditations.append({
                "ab_code": AB_CODE, "certificate_number": cert + suffix, "body_name": name,
                "accreditation_standard": acc_std, "status": status, "issue_date": issue,
                "expiry_date": expiry, "proof_url": proof})
        for std, codes, note in rows:
            scopes.append({"certificate_number": cert + SCHEMES.get(std, DEFAULT_SCHEME)[1],
                           "certification_standard": std, "ea_codes": codes, "status": status,
                           "scope_note": note})

    args.dataset.mkdir(parents=True, exist_ok=True)
    write_csv(args.dataset / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda b: b["name"].lower()))
    write_csv(args.dataset / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.dataset / "scopes.csv", SCOPE_COLUMNS, scopes)
    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.dataset, date.fromisoformat(args.today))
    for line in removed:
        review["Removed by prune_inactive"].append(line)

    kept = list(csv.DictReader((args.dataset / "bodies.csv").open(encoding="utf-8")))
    n_acc = sum(1 for _ in csv.DictReader((args.dataset / "accreditations.csv").open(encoding="utf-8")))
    n_sc = sum(1 for _ in csv.DictReader((args.dataset / "scopes.csv").open(encoding="utf-8")))
    out = ["# O'ZAK dataset review", "", f"{len(kept)} bodies, {n_acc} accreditations, {n_sc} scopes "
           f"(of {len(orgs)} register entries)", ""]
    for section, items in review.items():
        out += [f"## {section} ({len(items)})", "", *[f"- {i}" for i in items], ""]
    args.review.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:3]))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("scrape", type=Path, nargs="?", default=HERE / "akkred_uz_management_bodies")
    p.add_argument("dataset", type=Path, nargs="?",
                   default=HERE.parent.parent / "certifind" / "data" / "ozak-uzbekistan")
    p.add_argument("--today", default=date.today().isoformat())
    p.add_argument("--debug", nargs="*", default=[], help="registry numbers to print parsed rows for")
    p.add_argument("--review", type=Path, default=HERE / "ozak_review.md")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
