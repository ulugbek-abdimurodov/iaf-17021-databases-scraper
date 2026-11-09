#!/usr/bin/env python3
"""Convert the Norsk Akkreditering scrape (ISO/IEC 17021-1 management system certification
bodies) into a CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by no_ms_scraper.py (no_ms_output/: bodies.csv with one row per NA
registration "MSYS nnn", scopes.csv with one "standard" row per scheme and one "scope_code" row
per listed code, addresses.csv with the visiting address of each registration's unit).

The register is structured HTML, so no PDF annexes are read. Scope codes per scheme:
IAF codes ("IAF 17") for ISO 9001 / 14001 / 45001, ISO 22003-1 categories ("Category C") for
ISO 22000, EnMS1-EnMS8 (ISO 50003 technical areas A-H) for ISO 50001, IAF MD 8 areas
("1_1_1 Non-Active Medical Devices") for ISO 13485. Other schemes have no sector list.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
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

AB_CODE = "NA"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the NA register; recorded for all EA sectors"

# NA scheme title -> CertiFind standard (first match). Anything else is not imported and listed
# in the review: the Norwegian Eco-Lighthouse scheme (Miljøfyrtårn), the Norwegian PEFC forest
# standards (PEFC N 02 / N 03) and the Danish Executive Order on mandatory energy management
# (BEK 1138/2025 with ISO 14001).
PFX = r"^NS[- ](?:EN[- ])?(?:ISO|IEC)(?:/IEC)?[ /-]*"
STANDARDS = [
    (PFX + r"3834\b", "ISO 3834"),  # "NS-EN ISO 3834-2:2021 and ISO 9001:2015"
    (PFX + r"9001\b", "ISO 9001"),
    (PFX + r"14001\b", "ISO 14001"),  # the 2015 and 2026 editions are separate schemes
    (PFX + r"45001\b", "ISO 45001"),
    (PFX + r"50001\b", "ISO 50001"),
    (PFX + r"27001\b", "ISO/IEC 27001"),
    (PFX + r"27701\b", "ISO/IEC 27701"),
    (PFX + r"22301\b", "ISO 22301"),
    (PFX + r"22000\b", "ISO 22000"),
    (PFX + r"13485\b", "ISO 13485"),
    (PFX + r"37001\b", "ISO 37001"),
    (PFX + r"21001\b", "ISO 21001"),
    (PFX + r"39001\b", "ISO 39001"),
]
STANDARD_RES = [(re.compile(p, re.I), s) for p, s in STANDARDS]

# Certification standard -> (accreditation standard, certificate-number suffix), as in the
# DAkkS and RvA datasets.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
    "AS 9100": ("AS 9104-1", " (9104)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
IAF_CODE = re.compile(r"^IAF\s+(\d{1,2})\b")
FOOD_CODE = re.compile(r"^Category\s+([A-K])\b", re.I)
ENERGY_CODE = re.compile(r"^EnMS\s*([1-8])\b", re.I)  # NA numbers the ISO 50003 areas A-H as 1-8
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
MEDICAL = [  # IAF MD 8 main technical areas, by the cell text after the "1_1_1" code
    ("non-active", "Non-active medical devices"),
    ("active implantable", "Active implantable medical devices"),
    ("active medical", "Active (non-implantable) medical devices"),
    ("in vitro", "In vitro diagnostic medical devices"),
    ("steril", "Sterilization methods"),
    ("dev incorporat", "Devices incorporating specific substances / technologies"),
    ("devices incorporat", "Devices incorporating specific substances / technologies"),
    ("parts", "Parts or services"),
]
NAMES = {"DNV PRODUCT ASSURANCE AS": "DNV Product Assurance AS"}  # register shows it in capitals


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def phone(raw: str) -> str:
    """'67 57 99 00' / '90656399' -> '+47 ...'; 'Tlf. 46 44 60 98 Faks. ...' -> '+47 46 44 60 98'."""
    p = re.sub(r"^\s*(?:Tlf\.?|Tel\.?)\s*", "", raw.strip(), flags=re.I)
    p = re.split(r"\s*(?:Faks|Fax)\b", p, flags=re.I)[0].strip()
    if p.startswith("+"):
        p = re.sub(r"\s+", " ", p)
        return p if re.fullmatch(r"\+\d{1,3}(?: \d+)+", p) else ""
    digits = re.sub(r"\D", "", p)
    if len(digits) == 8:
        if " " in p:  # keep the register's grouping
            return "+47 " + re.sub(r"\s+", " ", p)
        return "+47 " + " ".join(digits[i:i + 2] for i in range(0, 8, 2))
    return ""


def website(raw: str) -> str:
    w = raw.strip()
    if not w:
        return ""
    if not re.match(r"https?://", w, re.I):
        w = "http://" + w
    return w


def address(raw: str) -> str:
    """'Sognsveien 72, 0855 OSLO' -> 'Sognsveien 72, 0855 Oslo'."""
    return re.sub(r"(\d{4} )([A-ZÆØÅ][A-ZÆØÅ -]+)$", lambda m: m.group(1) + m.group(2).title(), raw.strip())


def classify(title: str) -> str | None:
    return next((s for rx, s in STANDARD_RES if rx.search(title)), None)


def scope_codes(std: str, items: list[dict]) -> tuple[set[int], str]:
    col1 = [i["column1"].strip() for i in items]
    if std in IAF_STANDARDS:
        return {int(m.group(1)) for c in col1 if (m := IAF_CODE.match(c)) and 1 <= int(m.group(1)) <= 39}, ""
    if std == "ISO 50001":
        areas = sorted({"ABCDEFGH"[int(m.group(1)) - 1] for c in col1 if (m := ENERGY_CODE.match(c))})
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std == "ISO 22000":
        cats = sorted({m.group(1).upper() for c in col1 if (m := FOOD_CODE.match(c))})
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = []
        for c in col1:
            low = re.sub(r"^[\d_]+\s*", "", c).lower()
            hit = next((name for key, name in MEDICAL if low.startswith(key)), None)
            if hit and hit not in areas:
                areas.append(hit)
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    return set(ALL), ALL_NOTE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[], help="print the schemes of these registrations (e.g. 'MSYS 001')")
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)
    src = args.scrape / "no_ms_output" if (args.scrape / "no_ms_output").is_dir() else args.scrape

    def read(name: str) -> list[dict]:
        with open(src / name, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    regs = sorted(read("bodies.csv"), key=lambda r: r["ident"])
    units = {r["ident"]: r["unit_address"].strip() for r in read("addresses.csv") if r["unit_address"].strip()}
    # ident -> scheme title -> scope_code rows (a scheme title can appear once per registration)
    schemes: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for row in read("scopes.csv"):
        items = schemes[row["ident"]].setdefault(row["scheme_title"].strip(), [])
        if row["row_type"] == "scope_code":
            items.append(row)

    review, skipped = [], defaultdict(list)
    companies: dict[str, dict] = {}
    for reg in regs:
        rid, name = reg["ident"], reg["company"].strip()
        name = NAMES.get(name, name)
        if reg["state"] != "Active":
            review.append(f"{rid} {name}: state '{reg['state']}'; not imported")
            continue
        found: dict[str, tuple[set[int], list[str]]] = {}
        for title, items in schemes[rid].items():
            std = classify(title)
            if rid in args.debug:
                print(f"## {rid} [{std}] {title}\n   " + "\n   ".join(
                    f"{i['column1']} | {i['column2'][:60]}" for i in items[:12]))
            if std is None:
                skipped[title].append(rid)
                continue
            codes, note = scope_codes(std, items)
            if not codes:
                review.append(f"{rid} {name}: {std} scheme '{title}' found but no sectors read — check {reg['url']}")
                continue
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)
        if not found:
            review.append(f"{rid} {name}: no importable standard (only national schemes: "
                          f"{', '.join(schemes[rid]) or 'none'}); not imported")
            continue
        if name in companies:
            first = companies[name]
            for std, (codes, notes) in found.items():
                prev = first["found"].setdefault(std, (set(), []))
                prev[0].update(codes)
                prev[1].extend(n for n in notes if n not in prev[1])
            review.append(f"{rid} {name}: second registration of {first['rid']}; merged into its rows and dates")
            continue
        companies[name] = {"reg": reg, "rid": rid, "found": found}

    body_rows, accreditations, scope_rows = {}, [], []
    for name, c in companies.items():
        reg, rid = c["reg"], c["rid"]
        tel = phone(reg["phone"])
        if reg["phone"].strip() and not tel:
            review.append(f"{rid} {name}: phone '{reg['phone']}' is not an international number; left empty")
        body_rows[name] = {"name": name, "country": "Norway", "registration_no": rid,
                           "phone": tel, "email": reg["email"].strip(),
                           "website": website(reg["website"]),
                           "address": address(units.get(rid) or reg["address"]),
                           "source_url": reg["url"], "verified_at": ""}
        issue = reg["renewed"] or reg["started"]
        rows_needed = {BASE: rid}
        for std in c["found"]:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": issue, "expiry_date": reg["expires"],
                                   "proof_url": reg["url"]})
        for std, (codes, notes) in c["found"].items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE",
                               "scope_note": "; ".join(notes)})
        if all(std in SCHEME_ROWS for std in c["found"]):
            review.append(f"{rid} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")

    # A company already in another dataset (same country and name) is one body in the database.
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() == args.out.resolve():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["country"] == "Norway" and r["name"] in body_rows:
                    body_rows[r["name"]] = {k: r[k] for k in BODY_COLUMNS}
                    review.append(f"{r['name']}: already in {path.parent.name}; that dataset's body row is used")

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "na_review.md", "w", encoding="utf-8") as f:
        f.write(f"# Norsk Akkreditering conversion review\n\nGenerated {today}: {counts[0]} bodies, "
                f"{counts[1]} accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Schemes not imported (scheme: registrations)\n\n")
        for title, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {title}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'na_review.md'}")


if __name__ == "__main__":
    main()
