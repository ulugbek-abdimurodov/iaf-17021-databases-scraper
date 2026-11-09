#!/usr/bin/env python3
"""Convert the Swedac management-system register export to CertiFind CSVs."""
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

AB_CODE = "SWEDAC"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"), "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"), "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
    "AS 9100": ("AS 9104-1", " (9104)"),
}
STANDARD_PATTERNS = [
    (r"\bFSSC\s*22000\b", "FSSC 22000"), (r"\bISO\s*9001\b", "ISO 9001"),
    (r"\bISO\s*14001\b", "ISO 14001"), (r"\bISO\s*45001\b", "ISO 45001"),
    (r"\bISO\s*50001\b", "ISO 50001"), (r"\bISO/IEC\s*27001\b", "ISO/IEC 27001"),
    (r"\bISO/IEC\s*27701\b", "ISO/IEC 27701"), (r"\bISO/IEC\s*20000-1\b", "ISO/IEC 20000-1"),
    (r"\bISO/IEC\s*42001\b", "ISO/IEC 42001"), (r"\bISO\s*22301\b", "ISO 22301"),
    (r"\bISO\s*22000\b", "ISO 22000"), (r"\bISO\s*13485\b", "ISO 13485"),
    (r"\bISO\s*55001\b", "ISO 55001"), (r"\bISO\s*37001\b", "ISO 37001"),
    (r"\bISO\s*39001\b", "ISO 39001"), (r"\bEN\s*15224\b", "EN 15224"),
    (r"\bAS\s*9100\b", "AS 9100"),
]
SKIPPED = re.compile(r"forestry|notified body|welding|accessibility|personal data|road safety", re.I)


def classify(text: str) -> str | None:
    for pattern, standard in STANDARD_PATTERNS:
        if re.search(pattern, text, re.I):
            return standard
    return None


def iaf_codes(row: dict[str, str]) -> set[int]:
    text = " ".join(row.get(f"column{i}", "") for i in range(1, 10))
    return {int(n) for n in re.findall(r"\bIAF\s*(?:code\s*)?(\d{1,2})\b", text)
            if 1 <= int(n) <= 39}


def scope_codes(std: str, row: dict[str, str]) -> tuple[set[int], str]:
    text = " ".join(row.get(f"column{i}", "") for i in range(1, 10))
    if std in IAF_STANDARDS:
        codes = iaf_codes(row)
        return codes or ALL, "IAF sectors listed in the Swedac scope" if codes else \
            "No sector list in the register row; recorded for all EA sectors"
    if std == "EN 15224":
        return {38}, "EN 15224 classified to EA 38 (health and social work)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({m.group(1).upper() for m in re.finditer(r"\b(?:category|cat\.?)\s*([A-K])", text, re.I)})
        if cats:
            codes = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
            return codes, f"ISO 22003-1 categories {', '.join(cats)} (classified to EA by sector)"
    if std == "ISO 50001":
        areas = [letter for letter, prefixes, _ in esyd.ENERGY_AREAS
                 if any(re.search(re.escape(prefix), text, re.I) for prefix in prefixes)]
        if areas:
            return set().union(*(expand(next(s for l, _, s in esyd.ENERGY_AREAS if l == a)) for a in areas)), \
                f"ISO 50003 technical areas {', '.join(sorted(set(areas)))} (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [name for name, prefixes, _ in esyd.MEDICAL_AREAS
                 if any(re.search(re.escape(prefix), text, re.I) for prefix in prefixes)]
        if areas:
            return set().union(*(expand(next(s for n, _, s in esyd.MEDICAL_AREAS if n == a)) for a in areas)), \
                f"ISO 13485 main technical areas: {'; '.join(sorted(set(areas)))} (classified to EA by sector)"
    return ALL, "No sector list in the register; recorded for all EA sectors"


def write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.DictWriter(fh, fieldnames=columns)
        out.writeheader()
        out.writerows(rows)


def phone(raw: str, review: list[str], rid: str, name: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("+46"):
        digits = re.sub(r"\D", "", value[3:])
        return f"+46 {digits}" if digits else ""
    if value.startswith("0"):
        digits = re.sub(r"\D", "", value[1:])
        return f"+46 {digits}" if digits else ""
    review.append(f"{rid} {name}: phone '{value}' is not a Swedish or international number; left empty")
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[])
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)
    bodies = list(csv.DictReader((args.scrape / "bodies.csv").open(encoding="utf-8-sig", newline="")))
    scopes = list(csv.DictReader((args.scrape / "scopes.csv").open(encoding="utf-8-sig", newline="")))
    by_id = defaultdict(list)
    for row in scopes:
        if row["in_17021_scope"] == "yes":
            by_id[row["ident"]].append(row)
    review, skipped = [], defaultdict(list)
    body_rows, accreditations, scope_rows = {}, [], []
    for body in bodies:
        rid, name = body["ident"], body["company"].strip()
        found: dict[str, tuple[set[int], list[str]]] = {}
        for row in by_id[rid]:
            raw = " ".join(row.get(f"column{i}", "") for i in range(1, 10))
            std = classify(row["column2"] or row["scheme_title"] + " " + raw)
            if not std:
                skipped[row["scheme_title"] or row["column2"]].append(rid)
                continue
            codes, note = scope_codes(std, row)
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note not in prev[1]:
                prev[1].append(note)
        if not found:
            review.append(f"{rid} {name}: no importable management-system standard; not imported")
            continue
        if name in body_rows:
            review.append(f"{rid} {name}: duplicate registration merged into {body_rows[name]['registration_no']}")
            continue
        normalized_phone = phone(body["phone"], review, rid, name)
        body_rows[name] = {"name": name, "country": "Sweden", "registration_no": rid, "phone": normalized_phone,
                           "email": body["email"], "website": body["website"], "address": body["address"],
                           "source_url": body["url"], "verified_at": ""}
        rows_needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": body["latest_decision_date"] or today,
                                   "expiry_date": "", "proof_url": body["url"]})
        for std, (codes, notes) in found.items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE",
                               "scope_note": "; ".join(notes)})
    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with path.open(encoding="utf-8-sig", newline="") as fh:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(fh)})
    for name in list(body_rows):
        row = body_rows[name]
        if (row["country"], name) in others:
            other, dataset = others[(row["country"], name)]
            body_rows[name] = {c: other[c] for c in BODY_COLUMNS}
            review.append(f"{row['registration_no']} {name}: already in {dataset}; existing body row used")
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write(args.out / "scopes.csv", SCOPE_COLUMNS, scope_rows)
    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today or date.today())
    with (HERE / "swedac_review.md").open("w", encoding="utf-8") as fh:
        fh.write(f"# Swedac conversion review\n\nGenerated {today}: {len(body_rows)} bodies, "
                 f"{len(accreditations)} accreditations, {len(scope_rows)} scope rows before pruning.\n\n")
        fh.write("## Notes\n\n" + "".join(f"- {x}\n" for x in review))
        fh.write("\n## Sections not imported\n\n")
        for heading, ids in sorted(skipped.items()):
            fh.write(f"- {heading}: {', '.join(sorted(set(ids)))}\n")
        fh.write("\n## Removed by prune_inactive\n\n" + "".join(f"- {x}\n" for x in removed))
    print(f"before prune: {len(body_rows)} bodies, {len(accreditations)} accreditations, "
          f"{len(scope_rows)} scopes; removed {len(removed)}")


if __name__ == "__main__":
    main()
