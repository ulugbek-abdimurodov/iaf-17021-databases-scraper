#!/usr/bin/env python3
"""Turn the LATAK scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads latak_S2/bodies.json and, per body, <ID>_annex_tables.csv (the annex tables cell by
cell) and <ID>_text.txt (page text). Each annex lists, per certification standard:

- ISO 9001 / 14001 / 45001: "IAF n" (or a bare number, "Global ACI-TECH-3-021" tables) with
  the sector name and a NACE list. The EA code is read from the NACE list with the IAF ID 1
  table (database/bulgaria/prepare_certifind.py) and checked against the printed number;
  when they differ the NACE list wins (the annexes have a few typos, e.g. "6 Betons…" for
  16). A NACE list narrower than the sector makes a limited scope.
- ISO 22000 / FSSC 22000: ISO 22003-1 food chain categories (letters), classified to EA
  with the BAS / ESYD table.
- ISO 13485: IAF MD 8 main technical areas, classified with the ESYD table.
- Other standards (ISO 50001 "assessed according to ISO 50003", ISO/IEC 27001, 27701,
  20000-1, ISO 22301, 37001, 21001, 3834): no sector list; recorded for all EA sectors.

Left out: national and regulatory schemes that are not management-system standards —
competent institutions in labour protection, environmental management with energy
audits, EU end-of-waste regulations 333/2011 etc., MLC 2006, pressure equipment module H,
PEFC forest management and PAS 24000. Bodies holding only such schemes are not imported.

Some annex tables lose the standard column; the standard is then read from the page text.

Run:  python prepare_certifind.py  [--data latak_S2] [--out ../../certifind/data/latak-latvia]
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

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bas = _load("bas_prepare", HERE.parent / "bulgaria" / "prepare_certifind.py")
esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "LATAK"
COUNTRY = "Latvia"
REGISTER_URL = "https://www.latak.gov.lv/lv/akreditetas-institucijas"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Earliest match in a cell wins; FSSC before ISO 22000 (an FSSC cell also cites ISO 22000).
STANDARD_PATTERNS = [
    ("FSSC 22000", r"FSSC\s*22000"),
    ("ISO 9001", r"ISO\s*9001"), ("ISO 14001", r"ISO\s*14001"), ("ISO 45001", r"ISO\s*45001"),
    ("ISO 22000", r"ISO\s*22000"), ("ISO 50001", r"ISO\s*50001"), ("ISO 13485", r"ISO\s*13485"),
    ("ISO/IEC 27701", r"27701"), ("ISO/IEC 27001", r"27001"), ("ISO/IEC 20000-1", r"20000-1"),
    ("ISO 22301", r"ISO\s*22301"), ("ISO 37001", r"ISO\s*37001"), ("ISO 21001", r"ISO\s*21001"),
    ("ISO 3834", r"ISO[\s-]*3834"),
]
# Rows of schemes that are not management-system standards (their cells cite ISO 9001 /
# 14001 as a basis, so they are recognised before any standard is read).
EXCLUDED = [
    (r"Kompetento institūciju", "certification of competent institutions in labour protection (Cabinet Regulation No. 723)"),
    (r"enerģijas patēriņa izvērtēšanas", "environmental management with continuous energy consumption evaluation (Cabinet Regulation No. 487)"),
    (r"ES regulām|333/2011", "quality management under EU end-of-waste regulations 333/2011, 1179/2012, 715/2013"),
    (r"Darba organizācijas|MLC", "quality management combined with the Maritime Labour Convention 2006"),
    (r"Spiedieniekārt", "pressure equipment module H (Directive 2014/68/EU), a notified-body module"),
    (r"PEFC", "PEFC forest management, not an international management-system standard"),
    (r"PAS 24000|Sociālās pārvaldības", "PAS 24000 social management, not an international management-system standard"),
]
SCHEMES = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"), "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"), "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000-6)"),
}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")
ALL_NOTES = {
    "ISO 50001": "Assessed according to ISO 50003; no technical-area list in annex, recorded for all EA sectors",
}
ALL_NOTE = "No sector list in annex; recorded for all EA sectors"

MEDICAL_ZONES = [
    (r"non[- ]?active", "Non-active medical devices"),
    (r"active implantable", "Active implantable medical devices"),
    (r"active medical devices|active \(non", "Active (non-implantable) medical devices"),
    (r"in vitro", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation", "Sterilization methods"),
    (r"incorporating|specific substances", "Devices incorporating specific substances / technologies"),
    (r"parts (?:or|and) services", "Parts or services"),
]
MEDICAL = {name: codes for name, _, codes in esyd.MEDICAL_AREAS}

SECTOR_CELL = re.compile(r"^(?:IAF\s*)?0?(\d{1,2})\s+[^\d\s]")
FOOD_IN_CELL = re.compile(r"(?:^|[\s;/])([A-K])\s*[–-]\s*\S")
FSSC_CATEGORY = re.compile(r"\b([A-K])\s+kategorij")
HEADER_LINE = re.compile(r"AKREDITĀCIJAS STANDARTS|ACCREDITATION STANDARD|AKREDITĒTĀ INSTITŪCIJA|"
                         r"NUMBER OF ACCREDITATION|Tehniskās jomas saskaņā|technical areas according")
MONTHS = {"janvār": 1, "februār": 2, "mart": 3, "aprīl": 4, "maij": 5, "jūnij": 6, "jūlij": 7,
          "august": 8, "septembr": 9, "oktobr": 10, "novembr": 11, "decembr": 12}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def standards_in(text: str) -> list[str]:
    hits = sorted((m.start(), std) for std, pat in STANDARD_PATTERNS if (m := re.search(pat, text)))
    found = [std for _, std in hits]
    if "FSSC 22000" in found:
        return ["FSSC 22000"]
    return found


def excluded(text: str) -> str | None:
    return next((why for pat, why in EXCLUDED if re.search(pat, text)), None)


def lv_date(text: str) -> str:
    """'2024. gada 18. februāra' -> '2024-02-18'."""
    m = re.search(r"(\d{4})\.\s*gada\s+(\d{1,2})\.\s*(\w+)", text)
    if not m:
        return ""
    month = next((n for stem, n in MONTHS.items() if m[3].startswith(stem)), None)
    return f"{m[1]}-{month:02d}-{int(m[2]):02d}" if month else ""


def phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if raw.strip().startswith("+") and not digits.startswith("371"):
        return "+" + digits[:2] + " " + digits[2:]          # foreign number as given
    digits = digits[3:] if digits.startswith("371") else digits
    return f"+371 {digits}" if len(digits) == 8 else ""


class Section:
    def __init__(self, standard: str) -> None:
        self.standard = standard
        self.ea: dict[int, list] = {}           # EA -> NACE list
        self.food: list[str] = []
        self.medical: list[str] = []
        self.notes: list[str] = []

    def result(self) -> tuple[str, str]:
        if self.food:
            codes = set()
            for c in self.food:
                codes |= bas.expand(bas.FOOD_CATEGORIES[c])
            return bas.ea_spec(codes), (f"ISO 22003-1 categories {', '.join(sorted(set(self.food)))} "
                                        "(classified to EA by sector)")
        if self.medical:
            codes = set()
            for m in self.medical:
                codes |= bas.expand(MEDICAL[m])
            names = "; ".join(dict.fromkeys(self.medical))
            return bas.ea_spec(codes), f"IAF MD 8 main technical areas: {names} (classified to EA by sector)"
        if self.ea:
            limited = [f"EA {ea} (NACE {nace_label(nace)})"
                       for ea, nace in sorted(self.ea.items()) if nace and is_limited(ea, nace)]
            note = "Limited scope (part of the sector): " + "; ".join(limited) if limited else ""
            return bas.ea_spec(set(self.ea)), note
        return "ALL", ALL_NOTES.get(self.standard, ALL_NOTE)


def nace_text(text: str) -> str:
    """Latvian 'izņemot' / 'bet izņemot' (except), '&' / 'un' (and), ';' as list separator."""
    text = re.sub(r"(?:bet\s+)?izņem\w*\s*/?\s*(?:except)?", " except ", text)
    text = re.sub(r"\s*(?:&|\bun\b|\band\b)\s*", ", ", text).replace(";", ",")
    # The Latvian and English copies of an 'except' list are printed one after the other.
    return re.split(r"(?<=\d)\s+(?=\d{1,2}(?:\.\d+)?,? except)", text)[0]


# ---- NACE lists, compared as digit strings so that class 23.51 falls in group 23.5.
def digits(code: str) -> str:
    """'23.51' -> '2351'. A class ending in 0 is the only class of its group (59.20 = 59.2,
    12.00 = 12), so the trailing zero is dropped."""
    div, _, rest = code.partition(".")
    if len(rest) == 2 and rest.endswith("0"):
        rest = rest[0] if rest[0] != "0" else ""
    return div.zfill(2) + rest


def parse_nace(text: str) -> list[tuple[str, frozenset]]:
    """'24 except 24.46, 25 except 25.4, 33.11' -> [('24', {'2446'}), ('25', {'254'}), ('3311', {})]."""
    items: list[list] = []
    excepting = False
    for tok in re.findall(r"except|\d{1,2}(?:\.\d{1,2})?", text):
        if tok == "except":
            excepting = bool(items)
            continue
        code = digits(tok)
        if excepting and code.startswith(items[-1][0]) and code != items[-1][0]:
            items[-1][1].add(code)
            continue
        excepting = False
        items.append([code, set()])
    return [(c, frozenset(e)) for c, e in items]


REFERENCE = {ea: parse_nace(text) for ea, text in bas.IAF_ID1.items()}


def overlaps(item, ref) -> bool:
    a, b = item[0], ref[0]
    if not (a.startswith(b) or b.startswith(a)):
        return False
    return not any(a.startswith(e) for e in ref[1]) and not any(b.startswith(e) for e in item[1])


def ea_of_nace(listed) -> set[int]:
    return {ea for ea, refs in REFERENCE.items() for ref in refs for item in listed if overlaps(item, ref)}


def is_limited(ea: int, listed) -> bool:
    """A reference code is covered by a listed code at its level or above with no further
    exclusions, or by an enumeration of at least two of its sub-codes (the annexes list
    whole sectors class by class). Otherwise the row is a limited scope."""
    for code, excl in REFERENCE[ea]:
        above = [x for c, x in listed if code.startswith(c)]
        if any(all(any(e.startswith(r) for r in excl) for e in x) for x in above):
            continue
        parts = {c for c, _ in listed if c.startswith(code) and c != code}
        if len(parts) >= 2:
            continue
        return True
    return False


def nace_label(nace) -> str:
    def fmt(code: str) -> str:
        return code[:2] + ("." + code[2:] if len(code) > 2 else "")
    return ", ".join(fmt(c) + (f" except {', '.join(fmt(e) for e in sorted(x))}" if x else "") for c, x in nace)


# English sector names in the annexes -> EA, to settle a printed code that the NACE list
# contradicts.
EA_NAMES = [
    (r"other transport", 22), (r"transport,? storage|transport and storage", 31), (r"agricultur", 1),
    (r"mining", 2), (r"food products", 3), (r"textile", 4), (r"leather", 5), (r"wood", 6),
    (r"pulp|paper", 7), (r"publishing", 8), (r"printing", 9), (r"coke", 10), (r"nuclear", 11),
    (r"pharmaceutical", 13), (r"chemical", 12), (r"rubber|ruber", 14), (r"non-metallic", 15),
    (r"concrete", 16), (r"basic metal", 17), (r"machinery", 18), (r"electrical", 19),
    (r"shipbuilding", 20), (r"aerospace", 21), (r"not elsewhere", 23), (r"recycling", 24),
    (r"electricity", 25), (r"gas supply", 26), (r"water supply", 27), (r"construction", 28),
    (r"wholesale", 29), (r"hotels", 30), (r"financial", 32), (r"information technology", 33),
    (r"engineering", 34), (r"other services", 35), (r"public administration", 36),
    (r"education", 37), (r"health", 38), (r"social services", 39),
]


def ea_of_name(text: str) -> int | None:
    return next((ea for pat, ea in EA_NAMES if re.search(pat, text, re.I)), None)


TABLE_KINDS = [("food", r"22003"), ("medical", r"IAF MD 8|ACI-TECH-3-006"),
               ("sector", r"IAF ID 1|ACI-TECH-3-021|NACE"), ("docs", r"Normatīv|PEFC|Sertificēšanas shēma")]
SCOPE_HEADER = re.compile(r"Akreditācijas sfēra|Accreditation scope|Sertificēšanas objekts")
SECTOR_STANDARDS = ("ISO 9001", "ISO 14001", "ISO 45001")
LISTED_STANDARDS = SECTOR_STANDARDS + ("ISO 13485", "ISO 22000", "FSSC 22000")


def parse_body(folder: Path, body_id: str, review: dict[str, list[str]]) -> dict[str, Section]:
    """Walk the annex tables row by row. A header row ("Akreditācijas sfēra / Accreditation
    scope …") sets the table kind; the first column, when filled, names the standard (or an
    excluded scheme) for the rows that follow."""
    sections: dict[str, Section] = {}
    text = (folder / f"{body_id}_text.txt").read_text(encoding="utf-8")
    parts = re.split(r"--- page (\d+) ---", text)
    pages_text = {int(parts[i]): "\n".join(l for l in parts[i + 1].splitlines() if not HEADER_LINE.search(l))
                  for i in range(1, len(parts), 2)}

    def section(std: str) -> Section:
        return sections.setdefault(std, Section(std))

    # Sector standards in the order the sector tables name them (pages with IAF rows), for
    # tables whose standard column is empty: a block ends where the EA numbering restarts.
    sequence: list[str] = []
    for page, page_text in sorted(pages_text.items()):
        if re.search(r"IAF \d|ACI-TECH-3-021", page_text):
            for std in standards_in(page_text):
                if std in SECTOR_STANDARDS and std not in sequence:
                    sequence.append(std)

    rows = list(csv.reader(open(folder / f"{body_id}_annex_tables.csv", encoding="utf-8-sig")))[1:]
    kind, current, skipping, prev_ea = None, [], None, 0
    for row in rows:
        page = int(row[0])
        cells = [clean(c) for c in row[3:]]
        filled = [c for c in cells if c]
        if not filled or all(re.fullmatch(r"\d", c) for c in filled):
            continue
        joined = " ".join(filled)
        if SCOPE_HEADER.search(filled[0]) and (new := next((k for k, pat in TABLE_KINDS if re.search(pat, joined)), None)):
            kind, skipping = new, None
            continue
        lead = cells[0]
        if lead and not SECTOR_CELL.match(lead):
            why = excluded(lead)
            if why:
                skipping = why
                review["Excluded schemes"].append(f"{body_id}: {why}")
                continue
            skipping = None
            if found := standards_in(lead):
                if kind == "sector" and found[0] in SECTOR_STANDARDS:
                    fresh = found[0] not in current
                    current = found
                    if fresh:
                        prev_ea = 0
                else:
                    current = found
        if skipping:
            continue

        if kind == "sector":
            idx = next((i for i, c in enumerate(cells) if SECTOR_CELL.match(c)), None)
            if idx is None or idx + 1 >= len(cells) or not re.search(r"\d", cells[idx + 1]):
                continue
            printed = int(SECTOR_CELL.match(cells[idx])[1])
            nace = parse_nace(nace_text(cells[idx + 1]))
            from_nace = ea_of_nace(nace)
            mismatch = bool(from_nace) and printed not in from_nace
            # A printed code the NACE list contradicts: of the two, the one that keeps the
            # list in ascending order (the annexes list sectors in EA order).
            candidates = sorted({printed} | (from_nace if len(from_nace) == 1 else set())) if mismatch else [printed]
            later = [c for c in candidates if c > prev_ea]
            if not current and sequence:
                current = [sequence[0]]
                ea = later[0] if later else printed
            elif not later:
                # The numbering restarts: the next standard's block.
                if current and current[0] in sequence and sequence.index(current[0]) + 1 < len(sequence):
                    current = [sequence[sequence.index(current[0]) + 1]]
                ea = next(iter(from_nace)) if mismatch and len(from_nace) == 1 else printed
            else:
                ea = later[0]
            prev_ea = ea
            if mismatch:
                nace = []          # the NACE list belongs to another sector: no limited-scope note
                review["Printed code differs from NACE"].append(
                    f"{body_id} {'/'.join(current)}: printed {printed} '{cells[idx][:60]}', "
                    f"NACE {cells[idx + 1][:60]} -> EA {ea}")
            if not current:
                review["Unparsed rows"].append(f"{body_id} (no standard): {joined[:140]}")
                continue
            for std in current:
                sec = section(std)
                sec.ea.setdefault(ea, [])
                sec.ea[ea] += [n for n in nace if n not in sec.ea[ea]]
        elif kind == "food":
            if "FSSC" in lead:
                current = ["FSSC 22000"]
                section("FSSC 22000").food += FSSC_CATEGORY.findall(joined)
            else:
                if current != ["ISO 22000"] and "FSSC" not in joined:
                    current = ["ISO 22000"]
                if current == ["ISO 22000"]:
                    section("ISO 22000").food += FOOD_IN_CELL.findall(" " + " ".join(cells[1:]))
        elif kind == "medical":
            current = ["ISO 13485"]
            area = next((a for pat, a in MEDICAL_ZONES if re.search(pat, cells[1] if len(cells) > 1 else "", re.I)), None)
            if area:
                section("ISO 13485").medical.append(area)
        else:
            # "Normative documents" tables: standards without a sector list.
            for std in standards_in(joined):
                if std not in LISTED_STANDARDS:
                    section(std)
    return sections


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    entries = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    entries = entries["bodies"] if isinstance(entries, dict) else entries
    review: dict[str, list[str]] = defaultdict(list)
    bodies, accreditations, scopes = [], [], []

    for entry in sorted(entries, key=lambda e: e["id"]):
        body_id = entry["id"]
        cert = entry.get("certificate", {})
        name = clean(entry["name"]).replace("„", "\"").replace("“", "\"").replace("”", "\"")
        sections = parse_body(args.data / body_id, body_id, review)
        rows = [(std, *sec.result()) for std, sec in sections.items()]
        if not rows:
            review["Not imported (no management-system standard in scope)"].append(f"{body_id} {name}: {entry['scope'][:120]}")
            continue
        status = "ACTIVE" if entry["status"] == "active" else "WITHDRAWN"
        period = cert.get("accreditation_period", "")
        issue = lv_date(period.split("līdz")[0])
        expiry = lv_date(period.split("līdz")[1]) if "līdz" in period else ""
        address = clean(re.sub(r"^(?:Juridiskā adrese:?\s*)", "", entry["addresses"].split(";")[-1]))
        address = re.sub(r"LV\s*-\s*(\d{4})", r"LV-\1", re.sub(r"^Adrese:\s*", "", address))
        bodies.append({"name": name, "country": COUNTRY, "registration_no": cert.get("registration_number", ""),
                       "phone": phone(entry["phone"]), "email": "", "website": "",
                       "address": f"{address}, Latvia" if address and "Latvij" not in address else address.replace("Latvija", "Latvia"),
                       "source_url": REGISTER_URL, "verified_at": ""})
        number = cert.get("certificate_number") or body_id
        schemes = sorted({SCHEMES.get(std, DEFAULT_SCHEME) for std, _, _ in rows} | {DEFAULT_SCHEME})
        for acc_std, suffix in schemes:
            accreditations.append({"ab_code": AB_CODE, "certificate_number": body_id + suffix, "body_name": name,
                                   "accreditation_standard": acc_std, "status": status, "issue_date": issue,
                                   "expiry_date": expiry, "proof_url": next((d["url"] for d in entry.get("documents", []) if d.get("url")),
                                                                     REGISTER_URL)})
        for std, codes, note in rows:
            if codes == "ALL":
                review["Recorded as ALL"].append(f"{body_id} {std}")
            if note.startswith("Limited"):
                review["Limited scopes"].append(f"{body_id} {std}: {note}")
            scopes.append({"certificate_number": body_id + SCHEMES.get(std, DEFAULT_SCHEME)[1],
                           "certification_standard": std, "ea_codes": codes, "status": status, "scope_note": note})
        if not issue or not expiry:
            review["Dates"].append(f"{body_id}: accreditation period '{period}' not read")
        review["Certificate numbers"].append(f"{body_id}: LATAK certificate {number}")

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda b: b["name"].lower()))
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    out = ["# LATAK dataset review", "", f"{len(bodies)} bodies, {len(accreditations)} accreditations, "
           f"{len(scopes)} scopes", ""]
    for section, items in review.items():
        out += [f"## {section} ({len(items)})", "", *[f"- {i}" for i in dict.fromkeys(items)], ""]
    args.review.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:3]))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=HERE / "latak_S2")
    p.add_argument("--out", type=Path, default=HERE.parent.parent / "certifind" / "data" / "latak-latvia")
    p.add_argument("--review", type=Path, default=HERE / "latak_review.md")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
