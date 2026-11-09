#!/usr/bin/env python3
"""Convert the DANAK scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by danak_ms_scraper.py (bodies.csv: one row per DANAK registration;
scopes.csv: one row per "detail" / "item" entry of each registration's scheme tables).

DANAK splits one company over several registrations (5xxx quality, 6xxx environment / energy,
65xx occupational health and safety). CertiFind allows one accreditation per body, accreditation
body and standard, so a company's registrations are merged: the rows use the lowest registration
number and its dates, and each scope row's note names the registration it came from.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]
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

AB_CODE = "DANAK"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the DANAK scope; recorded for all EA sectors"

# DANAK scheme title -> CertiFind standard. Anything else is not imported and listed in the
# review: Danish Executive Orders (wind turbines, lifts, meter installers, energy labelling,
# mandatory energy audits, health and safety certificate), Insurance & Pension Denmark, DS 21001
# (Danish railway safety), AQAP-2110 and the PED / RED directive modules.
STANDARDS = {
    "ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001": "ISO 45001",
    "ISO 50001": "ISO 50001", "ISO/IEC 27001": "ISO/IEC 27001", "ISO 13485": "ISO 13485",
    "ISO 22000": "ISO 22000", "FSSC 22000": "FSSC 22000", "ISO 55001": "ISO 55001",
}
# Certification standard -> (accreditation standard, certificate-number suffix), as in the
# DAkkS and RvA datasets.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
IAF_LINE = re.compile(r"(?m)^\s*(\d{1,2})\s+\S")
FOOD_LINE = re.compile(r"(?m)^\s*([A-K])(?:I{1,3}|IV)?\s*[/:]")
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
# ISO 50003 technical areas by the first words of a DANAK table line ("Building complexes"
# before "Buildings").
ENERGY = [("A", "industry - light"), ("B", "industry - heavy"), ("D", "building complex"),
          ("C", "building"), ("E", "transport"), ("F", "mining"), ("G", "agricultur"),
          ("H", "energy supply")]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
MEDICAL = [  # IAF MD 8 main technical areas, by the start of the DANAK table cell
    ("non-active", "Non-active medical devices"),
    ("active implantable", "Active implantable medical devices"),
    ("active medical", "Active (non-implantable) medical devices"),
    ("in vitro", "In vitro diagnostic medical devices"),
    ("steril", "Sterilization methods"),
    ("devices incorporat", "Devices incorporating specific substances / technologies"),
    ("parts", "Parts or services"),
]


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def phone(raw: str) -> str:
    """'39454836' -> '+45 39 45 48 36'; '00447736199040' -> '+44 7736 199040'."""
    p = raw.strip()
    digits = re.sub(r"\D", "", p)
    if p.startswith("+"):
        return re.sub(r"\s+", " ", p)
    if digits.startswith("0044"):
        return f"+44 {digits[4:8]} {digits[8:]}"
    if len(digits) == 8:
        return "+45 " + " ".join(digits[i:i + 2] for i in range(0, 8, 2))
    return ""


def website(raw: str) -> str:
    w = raw.strip()
    if not w:
        return ""
    if not re.match(r"https?://", w, re.I):
        w = "http://" + w
    scheme, rest = w.split("://", 1)
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}{slash}{path}"


def scope_codes(std: str, items: list[dict]) -> tuple[set[int], str]:
    col1 = "\n".join(i["column1"] for i in items)
    col2 = "\n".join(i["column2"] for i in items)
    if std in IAF_STANDARDS:
        return {int(c) for c in IAF_LINE.findall(col1) if 1 <= int(c) <= 39}, ""
    if std == "ISO 50001":
        areas = set()
        for line in col1.splitlines():
            low = re.sub(r"\s+", " ", line.strip().lower())
            if low.startswith("("):
                continue
            hit = next((letter for letter, key in ENERGY if low.startswith(key)), None)
            if hit:
                areas.add(hit)
        areas = sorted(areas)
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted(set(FOOD_LINE.findall(col2)))
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = []
        for i in items:
            low = i["column1"].strip().lower()
            hit = next((name for key, name in MEDICAL if low.startswith(key)), None)
            if hit and hit not in areas:
                areas.append(hit)
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    if std == "ISO 55001":
        codes = {int(c) for grp in re.findall(r"IAF\s+([\d,\s]+)", col1)
                 for c in re.findall(r"\d+", grp) if 1 <= int(c) <= 39}
        return codes, "IAF codes listed in the DANAK scope"
    return set(ALL), ALL_NOTE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    with open(args.scrape / "bodies.csv", encoding="utf-8-sig", newline="") as f:
        regs = sorted(csv.DictReader(f), key=lambda r: r["ident"])
    with open(args.scrape / "scopes.csv", encoding="utf-8-sig", newline="") as f:
        scope_in = list(csv.DictReader(f))

    # scheme_id -> title per registration; sub-schemes (ISO 22000 / FSSC versions) belong to
    # their parent scheme.
    by_reg: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in scope_in:
        sid = row["parent_scheme_id"] or row["scheme_id"]
        entry = by_reg[row["ident"]].setdefault(sid, {"title": "", "items": [], "url": ""})
        if not row["parent_scheme_id"]:
            entry["title"] = row["scheme_title"].strip()
            entry["url"] = row["scheme_url"]
        if row["row_type"] == "item":
            entry["items"].append(row)

    review, skipped = [], defaultdict(list)
    companies: dict[str, dict] = {}
    for reg in regs:
        rid, name = reg["ident"].removeprefix("01-"), reg["company"].strip()
        if reg["state"] != "Accredited":
            review.append(f"{rid} {name}: state '{reg['state']}'; not imported")
            continue
        found: dict[str, tuple[set[int], list[str]]] = {}
        for sid, entry in by_reg[reg["ident"]].items():
            std = STANDARDS.get(entry["title"])
            if std is None:
                skipped[entry["title"]].append(rid)
                continue
            codes, note = scope_codes(std, entry["items"])
            if not codes:
                review.append(f"{rid} {name}: {std} scheme found but no sectors read — check {entry['url']}")
                continue
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)
        if not found:
            review.append(f"{rid} {name}: no importable standard (only Danish national / directive "
                          f"schemes); registration not imported")
            continue
        c = companies.setdefault(name, {"first": reg, "rid": rid, "found": {}, "regs": []})
        c["regs"].append(rid)
        for std, (codes, notes) in found.items():
            if std in c["found"]:
                review.append(f"{rid} {name}: {std} also in registration {c['found'][std][2]}; merged")
                c["found"][std][0].update(codes)
                continue
            src = f"DANAK registration {rid}" if rid != c["rid"] else ""
            c["found"][std] = (codes, notes + ([src] if src else []), rid)
        if rid != c["rid"]:
            review.append(f"{rid} {name}: second registration of {c['rid']}; its schemes are merged "
                          f"into {c['rid']}'s rows and dates")

    body_rows, accreditations, scope_rows = {}, [], []
    for name, c in companies.items():
        reg, rid = c["first"], c["rid"]
        address = re.sub(r",\s*Danmark\s*$", "", reg["address"].strip())
        body_rows[name] = {"name": name, "country": "Denmark", "registration_no": rid,
                           "phone": phone(reg["phone"]), "email": reg["email"].strip(),
                           "website": website(reg["website"]), "address": address,
                           "source_url": reg["url"], "verified_at": ""}
        if reg["phone"].strip() and not body_rows[name]["phone"]:
            review.append(f"{rid} {name}: phone '{reg['phone']}' not recognised; left empty")
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
        for std, (codes, notes, _) in c["found"].items():
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
                if r["country"] == "Denmark" and r["name"] in body_rows:
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
    with open(HERE / "danak_review.md", "w", encoding="utf-8") as f:
        f.write(f"# DANAK conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Schemes not imported (scheme: registrations)\n\n")
        for title, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {title or '(untitled)'}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'danak_review.md'}")


if __name__ == "__main__":
    main()
