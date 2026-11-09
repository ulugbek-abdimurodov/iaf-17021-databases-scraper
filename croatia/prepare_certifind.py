#!/usr/bin/env python3
"""Turn the HAA scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads haa_data/bodies.json and each body's document_text.txt (the register's text copy of
the accreditation certificate and its annex) and writes the three CSVs in the importer format.

Annex sector tables (ISO 9001 / 14001 / 45001) list "scope number | name | NACE rev. 2"
"based upon IAF ID 1:2023": the scope number is the EA code. The text comes in two layouts:

- one table cell per line (certificates issued from 2024 on): EA line, Croatian and English
  name lines, NACE line;
- columns separated by runs of spaces (older annex form HAA-Ob-7/7-2/3): the EA code starts
  a line, and a long NACE cell wraps onto the name lines above and below it.

Every parsed row is checked against IAF ID 1: each NACE code must fall in the EA sector it
is listed under, which catches a NACE fragment attached to the wrong row. When the NACE list
is narrower than the sector, the scope note says "Limited scope" (as in the BAS dataset; the
IAF ID 1 table and NACE comparison are reused from database/bulgaria/prepare_certifind.py).

ISO 13485 annexes list IAF MD 8 main technical areas (tables A 1.1-1.7), classified to EA
with the table of the ESYD dataset (database/greece/prepare_certifind.py). The PED module H
annex of HRB is a notified-body directive module, not a management-system standard, and is
left out as in the ESYD dataset.

Run:  python prepare_certifind.py  [--data haa_data] [--out ../../certifind/data/haa-croatia]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bas = _load("bas_prepare", HERE.parent / "bulgaria" / "prepare_certifind.py")
esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "HAA"
COUNTRY = "Croatia"
REGISTER_URL = "https://akreditacija.gov.hr/frontend/registar-akreditacija"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Curated from the certificate header and the register record (register names repeat the
# legal name or give only a department).
NAMES = {
    4014: "Croatian Register of Shipping (Hrvatski registar brodova, HRB) – Sektor certifikacije sustava upravljanja",
    4075: "DNV Adriatica d.o.o.",
    4092: "SGS Adriatica d.o.o. – Sektor Business Assurance",
    4184: "Bureau Veritas Croatia d.o.o. – Sektor certifikacije sustava",
    4534: "UDEM Adriatic d.o.o.",
    4618: "ICR Adriatica d.o.o.",
    4622: "CRO CERT, Centar za certificiranje sustava upravljanja d.o.o.",
}
# The certifying department's address from the certificate header (DNV and Bureau Veritas
# have their seat in Rijeka and certify from Zagreb, which is also the register's address).
ADDRESSES = {
    4014: "Marasovića 67, 21000 Split, Croatia",
    4075: "Radnička cesta 177, 10000 Zagreb, Croatia",
    4092: "Karlovačka cesta 4i, 10000 Zagreb, Croatia",
    4184: "Vrbik 8a, 10000 Zagreb, Croatia",
    4534: "Radnička cesta 54, 10000 Zagreb, Croatia",
    4618: "Ulica Tadije Smičiklasa 18, 10000 Zagreb, Croatia",
    4622: "Frane Bulića 14, 10000 Zagreb, Croatia",
}

STANDARDS = [("ISO 9001", r"ISO 9001"), ("ISO 14001", r"ISO 14001"), ("ISO 45001", r"ISO 45001"),
             ("ISO 13485", r"ISO 13485"), ("PED", r"\(PED\)")]
EXCLUDED = {"PED": "PED module H (Directive 2014/68/EU) is a notified-body module, not a management-system standard"}
SECTION_START = re.compile(r"^\s*(?:\d\.\s+Certifikacija|Akreditacija u reguliranom)", re.M)
TABLE_END = re.compile(r"IAF ID 1|IAF MD 8|Stranica/Page|stranica/page|HAA-Ob-|Odjel za akreditiranje")
PAGE_FURNITURE = re.compile(
    r"Potvrda o akreditaciji|Prilog potvrdi|Accreditation Certificate|Annex to the Accreditation|"
    r"Datum izdanja|Issued on|Zamjenjuje|Replaces|^\s*/\s*$|^\s*\d{4}\s*$|PODRUČJE AKREDITACIJE|"
    r"SCOPE OF ACCREDITATION|Broj područja|Scope number|^\s*Broj\s*$|^\s*područja\s*$|"
    r"Naziv područja|NACE \(rev|Napomena|Notice|stranica/page|Stranica/Page|HAA-Ob-")
EA_ALONE = re.compile(r"^\s*(\d{1,2})\s*$")
EA_COLUMN = re.compile(r"^\s*(\d{1,2})(?:\s{2,}(.*\S))?\s*$")
NACE_TEXT = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})?|izuzev|minus|i|,|\s)+$")
MEDICAL_TABLE = re.compile(r"^\s*A?\s*1\.(\d)\s+\S", re.M)
# IAF MD 8 table A 1.n -> main technical area name in esyd.MEDICAL_AREAS.
MEDICAL_TABLES = {
    "1": "Non-active medical devices", "2": "Active (non-implantable) medical devices",
    "3": "Active implantable medical devices", "4": "In vitro diagnostic medical devices",
    "5": "Sterilization methods", "6": "Devices incorporating specific substances / technologies",
    "7": "Parts or services",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def iso_date(value: str) -> str:
    value = value.strip().rstrip(".")
    if m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value):
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""


def initial_accreditation(text: str) -> str:
    """'Prva akreditacija: 2006-10-30' (column layout) or 'Initial accreditation\\n25.06.2001.'."""
    m = re.search(r"Prva akreditacija:?\s*(\d{4}-\d{2}-\d{2})", text) or \
        re.search(r"Initial accreditation\s*\n\s*(\d{1,2}\.\d{1,2}\.\d{4})", text)
    return iso_date(m[1]) if m else ""


def is_nace(cell: str) -> bool:
    cell = clean(cell)
    return bool(cell) and bool(re.search(r"\d", cell)) and bool(NACE_TEXT.fullmatch(cell))


EA_INDENT = 30          # column layout: the EA code cell starts left of this
OPEN_END = re.compile(r"(?:,|\bi|izuzev|minus)\s*$")


def nace_fragment(line: str) -> str | None:
    """NACE cell of a column-layout line: the last cell after a wide gap, or a NACE-only line."""
    text = line.strip()
    if is_nace(text):
        return text
    cols = re.split(r"\s{2,}", text)
    return cols[-1] if len(cols) > 1 and is_nace(cols[-1]) else None


def continues(nace: str, cell: str) -> bool:
    return bool(OPEN_END.search(nace)) or cell.startswith(("izuzev", "minus"))


def parse_lines(lines: list[str]) -> dict[int, str]:
    """One cell per line: EA, names..., NACE (possibly continued on the next line)."""
    rows: dict[int, str] = {}
    ea, nace, seen_name = None, "", False
    for line in lines:
        cell = clean(line)
        if not cell:
            continue
        if ea is not None and seen_name and is_nace(cell) and (not nace or continues(nace, cell)):
            nace = f"{nace} {cell}".strip()
            continue
        if (m := EA_ALONE.match(cell)) and (ea is None or nace):
            if ea is not None:
                rows[ea] = nace
            ea, nace, seen_name = int(m[1]), "", False
            continue
        seen_name = True
    if ea is not None:
        rows[ea] = nace
    return rows


def to_bas(nace: str) -> str:
    """Croatian 'izuzev' / 'minus' (except) and 'i' (and) in the words the BAS NACE parser
    reads; '33.20' (the only class of group 33.2) as '33.2'."""
    nace = re.sub(r"izuzev|minus", "except", nace)
    nace = re.sub(r"\b(\d{2}\.\d)0\b", r"\1", nace)
    return re.sub(r"\s+i\s+|,\s*i\s+", ", ", nace)


def fits(ea: int, frag: str) -> bool:
    """Every NACE code of the fragment falls in EA sector `ea` (IAF ID 1)."""
    items = bas.parse_nace(to_bas(frag))
    return bool(items) and all(ea in bas.ea_of_nace([i]) for i in items)


def parse_columns(lines: list[str]) -> dict[int, str]:
    """Column layout: EA starts a line; a NACE cell that wraps puts fragments on the name
    lines above and below it. Each fragment joins the previous row when that row's list is
    still open ('…25,' or '…izuzev'), else the next row when its codes fit that EA sector,
    else the previous row when they fit it. Rows are then checked against IAF ID 1."""
    items: list[tuple] = []          # ("ea", code, inline fragment) or ("frag", text)
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r"\s*(\d{1,2})(?=\s|$)(.*)$", line)
        if m and indent < EA_INDENT and 1 <= int(m[1]) <= 39:
            items.append(("ea", int(m[1]), nace_fragment(m[2]) if m[2].strip() else None))
        elif (frag := nace_fragment(line)) is not None:
            items.append(("frag", frag))

    anchors = [i for i, item in enumerate(items) if item[0] == "ea"]
    parts: dict[int, list[tuple[int, str]]] = {items[i][1]: [] for i in anchors}
    for i in anchors:
        if items[i][2]:
            parts[items[i][1]].append((i, items[i][2]))
    for i, item in enumerate(items):
        if item[0] != "frag":
            continue
        prev = next((items[j][1] for j in reversed(anchors) if j < i), None)
        nxt = next((items[j][1] for j in anchors if j > i), None)
        so_far = clean(" ".join(t for _, t in sorted(parts[prev]) if _ < i)) if prev else ""
        if prev and so_far and continues(so_far, item[1]):
            target = prev
        elif nxt and fits(nxt, item[1]):
            target = nxt
        elif prev and fits(prev, item[1]):
            target = prev
        else:
            target = nxt or prev
        parts[target].append((i, item[1]))
    return {ea: clean(" ".join(t for _, t in sorted(p))) for ea, p in parts.items()}


def table_lines(section: str) -> list[str]:
    lines = []
    for line in section.split("\n"):
        if re.search(r"IAF ID 1", line):
            break
        if PAGE_FURNITURE.search(line):
            continue
        lines.append(line)
    # Drop the heading (up to and including the standard's own line).
    for i, line in enumerate(lines):
        if re.search(r"\(.*ISO \d+:\d{4}.*\)|ISO \d+:\d{4}\s*\(", line):
            return lines[i + 1:]
    return lines


def sections_of(text: str) -> list[tuple[str, str]]:
    text = text.replace("\r", "")
    starts = [m.start() for m in SECTION_START.finditer(text)] + [len(text)]
    out = []
    for a, b in zip(starts, starts[1:]):
        chunk = text[a:b]
        head = chunk[:600]
        standard = next((s for s, pat in STANDARDS if re.search(pat, head)), None)
        out.append((standard, chunk))
    return out


# NACE codes an annex lists under an EA sector that IAF ID 1 puts elsewhere; kept as written.
OFF_SECTOR = {("4184", 35, "74.9"): "Bureau Veritas annex lists NACE 74.9 under EA 35 (IAF ID 1: EA 34)"}


def check_row(where: str, ea: int, nace: str, problems: list[str]) -> list:
    listed = bas.parse_nace(to_bas(nace))
    if not listed:
        problems.append(f"{where}: EA {ea} has no NACE codes ('{nace}')")
    for item in listed:
        if (where.split()[0], ea, str(item)) in OFF_SECTOR:
            continue
        if ea not in bas.ea_of_nace([item]):
            problems.append(f"{where}: NACE {item} is not in EA {ea} (IAF ID 1) – row misread?")
    return listed


def run(args: argparse.Namespace) -> int:
    records = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    review: list[str] = []
    bodies, accreditations, scopes = [], [], []

    for rec in sorted(records, key=lambda r: r["BrojPotvrde"]):
        number = rec["BrojPotvrde"]
        cert = str(number)
        text = (args.data / rec["folder"] / "document_text.txt").read_text(encoding="utf-8")
        # Column layout: some line holds an EA code and its NACE cell separated by a wide gap.
        columns = bool(re.search(r"^ *\d{1,2} {10,}\d", text.replace("\r", ""), re.M))
        name = NAMES[number]

        phone = normalise_phone(rec.get("Telefon", ""))
        website = clean(rec.get("WebAdresa", "")).strip("_")
        if website and not website.startswith("http"):
            website = f"http://{website}"
        bodies.append({
            "name": name, "country": COUNTRY, "registration_no": "", "phone": phone, "email": "",
            "website": website, "address": ADDRESSES[number], "source_url": REGISTER_URL, "verified_at": "",
        })
        issued = initial_accreditation(text)
        if not issued:
            problems.append(f"{cert}: no initial accreditation date")
        accreditations.append({
            "ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
            "accreditation_standard": "ISO/IEC 17021-1", "status": "ACTIVE",
            "issue_date": issued, "expiry_date": iso_date(rec["DatumIsteka"]), "proof_url": REGISTER_URL,
        })

        seen = set()
        for standard, chunk in sections_of(text):
            where = f"{cert} {standard}"
            if standard is None:
                problems.append(f"{cert}: section without a known standard: {clean(chunk[:80])}")
                continue
            if standard in EXCLUDED:
                review.append(f"{cert} ({name}): left out – {EXCLUDED[standard]}")
                continue
            if standard in seen:
                problems.append(f"{where}: two sections")
            seen.add(standard)

            if standard == "ISO 13485":
                tables = sorted(set(MEDICAL_TABLE.findall(chunk)))
                areas = [MEDICAL_TABLES[t] for t in tables]
                codes: set[int] = set()
                for area in areas:
                    codes |= bas.expand(next(spec for n, _, spec in esyd.MEDICAL_AREAS if n == area))
                if not areas:
                    problems.append(f"{where}: no IAF MD 8 technical areas found")
                scopes.append(scope_row(cert, standard, codes,
                                        f"ISO 13485 main technical areas (IAF MD 8): {'; '.join(areas)} "
                                        "(classified to EA by sector)"))
                continue

            lines = table_lines(chunk)
            table = parse_columns(lines) if columns else parse_lines(lines)
            if not table:
                problems.append(f"{where}: no sector rows parsed")
                continue
            limited = []
            for ea, nace in table.items():
                listed = check_row(where, ea, nace, problems)
                if listed and bas.is_limited(ea, listed):
                    limited.append(f"EA {ea} (NACE {', '.join(str(n) for n in listed)})")
            notes = [f"Limited scope (part of the sector): {'; '.join(limited)}"] if limited else []
            notes += [text for (c, ea, _), text in OFF_SECTOR.items() if c == cert and ea in table]
            note = "; ".join(notes)
            scopes.append(scope_row(cert, standard, set(table), note))
            if args.verbose:
                print(where, {ea: table[ea] for ea in sorted(table)})

    if problems:
        print("Problems:", *problems, sep="\n  ")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda r: r["name"]))
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    print(*review, sep="\n")
    print(f"{len(bodies)} bodies, {len(accreditations)} accreditations, {len(scopes)} scopes -> {args.out}")
    return 0


def scope_row(cert: str, standard: str, codes: set[int], note: str) -> dict:
    return {"certificate_number": cert, "certification_standard": standard,
            "ea_codes": bas.ea_spec(codes), "status": "ACTIVE", "scope_note": note}


def normalise_phone(raw: str) -> str:
    """'021408116', '099/2646467', '+385 091 1328002', '385996225222' -> '+385 21 408116' etc."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("385"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    if len(digits) < 7:
        return ""
    area = 1 if digits.startswith("1") else 2   # Zagreb is 1, other areas and mobiles are two digits
    return f"+385 {digits[:area]} {digits[area:]}"


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=HERE / "haa_data")
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "certifind" / "data" / "haa-croatia")
    parser.add_argument("--verbose", action="store_true", help="print every parsed sector table")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
