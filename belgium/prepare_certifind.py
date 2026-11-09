#!/usr/bin/env python3
"""Convert the BELAC QMS scrape (management system certification bodies) into a CertiFind
dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by belac_qms_scraper.py. bodies.csv gives one accreditation per body
(certification number, e.g. 019-QMS, under EN ISO/IEC 17021-1 with its validity period);
scope.csv is the register's structured scope: one row per body, field (certification scheme)
and keyword (IAF code, ISO 50003 technical area, ISO 22003-1 category or IAF MD 8 area).

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points go to belac_review.md next to this script; prune_inactive.prune() then drops
everything that is not currently valid.
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

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "BELAC"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the register; recorded for all EA sectors"

# Register field -> CertiFind standard; None = deliberately not imported (reason).
FIELDS = {
    "ISO 9001": "ISO 9001",
    "ISO 45001": "ISO 45001",
    "ISO 13485": "ISO 13485",
    "ISO 50001": "ISO 50001",
    "ISO 22000": "ISO 22000",
    "FSSC 22000": "FSSC 22000",
    "ISO/IEC 27001": "ISO/IEC 27001",
}
SKIPPED = {
    "VCA": "VCA (Belgian-Dutch contractor safety checklist; national scheme)",
    "VCU": "VCU (temporary-employment safety checklist; national scheme)",
    "CO2 prestatieladder": "CO2 prestatieladder (Dutch CO2 performance ladder; national scheme)",
    "Food Autocontrol System": "Food Autocontrol System (Belgian FASFC self-checking; national scheme)",
    "Feed Chain Alliance": "Feed Chain Alliance (Belgian feed scheme; national scheme)",
    "Safety, Health and Environmental management": "SHE (Belgian asbestos / soil remediation schemes)",
    "European Directives": "EU directive modules (notified-body activities)",
}
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
}
ENERGY = {"Industry - light to medium": "A", "Industry - heavy": "B", "Buildings": "C",
          "Building complexes": "D", "Transport": "E", "Mining": "F", "Agriculture": "G",
          "Energy supply": "H"}
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL = {"Non-active medical devices": "Non-active medical devices",
           "Active medical devices (non implantable)": "Active (non-implantable) medical devices",
           "Active implantable medical devices": "Active implantable medical devices",
           "In vitro diagnostic medical devices (IVD)": "In vitro diagnostic medical devices",
           "Sterilization methods for medical devices": "Sterilization methods",
           "Devices incorporating/utilizing specific substances/technologies":
               "Devices incorporating specific substances / technologies",
           "Parts or services": "Parts or services"}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
COUNTRY_CODES = {"0031": "+31", "0035": "+35", "0032": "+32"}


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def phone(raw: str) -> str:
    """First number in international form: '(0476)87 44 34 (Name)' -> '+32 476 87 44 34'."""
    first = re.split(r"\s+/|/\s*\(|\s+-\s+", raw)[0]
    first = re.sub(r"\([A-Za-z][^)]*\)", "", first).strip()
    first = first.replace(".", " ")
    if m := re.match(r"\((0\d+)\)\s*(.*)", first):
        first = f"+32 {m.group(1)[1:]} {m.group(2)}"
    elif first.startswith("00"):
        first = "+" + first[2:].lstrip()
    elif first.startswith("0"):
        first = "+32 " + first[1:]
    return re.sub(r"\s+", " ", first).strip()


def field_name(field: str) -> str:
    return field.split(" (")[0].strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    bodies = {b["certificationNumber"]: b for b in read(args.scrape / "bodies.csv")}
    keywords: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in read(args.scrape / "scope.csv"):
        keywords[r["certificationNumber"]][field_name(r["field"])].append(r["keyword"].strip())

    review: list[str] = []
    body_rows, accreditations, scope_rows = [], [], []
    for number, b in sorted(bodies.items()):
        name = b["name"].strip()
        found: dict[str, tuple[set[int], str]] = {}
        for field, kws in keywords[number].items():
            if field in SKIPPED:
                review.append(f"{number} {name}: {SKIPPED[field]} not imported")
                continue
            std = FIELDS.get(field)
            if std is None:
                review.append(f"{number} {name}: unknown field '{field}' — add a rule")
                continue
            note = ""
            if std in ("ISO 9001", "ISO 45001"):
                codes = {int(m.group(1)) for k in kws if (m := re.match(r"IAF (\d+)\b", k))}
            elif std == "ISO 50001":
                areas = sorted({ENERGY[k] for k in kws if k in ENERGY})
                codes = set().union(*(expand(ENERGY_EA[a]) for a in areas)) if areas else set()
                note = ("ISO 50003 technical areas: " + "; ".join(ENERGY_NAMES[a] for a in areas)
                        + " (classified to EA by area)")
            elif std in ("ISO 22000", "FSSC 22000"):
                cats = sorted({m.group(1) for k in kws if (m := re.match(r"([A-K])\b", k))})
                codes = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)) if cats else set()
                note = ("ISO 22003-1 food chain categories: " + ", ".join(cats)
                        + " (classified to EA by category)")
            elif std == "ISO 13485":
                areas = [MEDICAL[k] for k in kws if k in MEDICAL]
                codes = set().union(*(expand(MEDICAL_EA[a]) for a in areas)) if areas else set()
                note = ("IAF MD 8 main technical areas: " + "; ".join(areas)
                        + " (classified to EA by area)")
            else:
                codes, note = set(range(1, 40)), ALL_NOTE
            unknown = [k for k in kws if std != "ISO/IEC 27001" and not (
                re.match(r"IAF \d+", k) or k in ENERGY or k in MEDICAL or re.match(r"[A-K]\b", k))]
            if unknown:
                review.append(f"{number} {name} {std}: keywords not classified: {unknown}")
            if not codes:
                review.append(f"{number} {name} {std}: no sector; recorded for all EA sectors")
                codes, note = set(range(1, 40)), ALL_NOTE
            found[std] = (codes, note)

        if not found:
            review.append(f"body {number} {name}: no importable standard; not imported")
            continue
        rows_needed = {BASE: number}
        for std in found:
            if std in SCHEME_ROWS:
                acc_std, suffix = SCHEME_ROWS[std]
                rows_needed.setdefault(acc_std, number + suffix)
        for acc_std, cert in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": b["valid_from"], "expiry_date": b["valid_to"],
                                   "proof_url": b["pdf_url"]})
        for std, (codes, note) in found.items():
            cert = number + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else number
            scope_rows.append({"certificate_number": cert, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": note})
        if not any(std not in SCHEME_ROWS for std in found):
            review.append(f"{number} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")

        website = b["url"].strip().rstrip("/")
        if website and not website.startswith("http"):
            website = "https://" + website
        street = " ".join(p for p in (b["street"].strip(), b["streetNumber"].strip()) if p)
        if b["postBox"].strip():
            street += f" bus {b['postBox'].strip()}"
        body_rows.append({
            "name": name, "country": b["country"].strip() or "Belgium", "registration_no": number,
            "phone": phone(b["telephone"]), "email": b["email"].split(",")[0].strip(),
            "website": website,
            "address": ", ".join(p for p in (street, f"{b['postCode']} {b['municipality']}".strip()) if p),
            "source_url": b["detail_page"], "verified_at": "",
        })

    body_rows.sort(key=lambda r: r["name"].casefold())
    write(args.out / "bodies.csv", BODY_COLUMNS, body_rows)
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "belac_review.md", "w", encoding="utf-8") as f:
        f.write("# BELAC conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'belac_review.md'}")


if __name__ == "__main__":
    main()
