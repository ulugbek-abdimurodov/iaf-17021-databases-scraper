#!/usr/bin/env python3
"""Convert the Akkreditierung Austria scrape (program 928, "Certification Body for
Managementsystems") into a CertiFind dataset folder (bodies.csv, accreditations.csv,
scopes.csv).

Input: the folder written by scrape_akkreditierung_austria.py (bodies.csv, scopes.csv,
technical_fields.csv, scope_attributes.csv, addresses.csv). Each body holds one
accreditation (identification number, e.g. 0901) under EN ISO/IEC 17021-1 with one initial
accreditation date and no end date (Austrian accreditations are open-ended and kept under
surveillance). Its scope rows of type N are the accredited certification standards; the other
types are applicable documents (IAF MDs, ISO 50003, ISO 22003-1, ...) and are only used to
cross-check.

Sectors come from each scope's technical fields (the register's ICS-like numbers):
  90.0xx.NN.X / 90.1xx.NN.X / 90.4xx.NN.X   IAF code NN (ISO 9001 / 14001 / 45001)
  90.xxx.00.C.05A.14A                       cluster entry naming IAF codes 5 and 14
  90.420.<cat> / 90.221.<cat>               ISO 22003-1 food chain category (ISO 22000 / FSSC)
  90.600.0N                                 ISO 50003 technical area N (1 = light industry ... 8)
  90.500.0N                                 IAF MD 8/9 main technical area N (ISO 13485)
IAF codes are compared with the scope's "field/ range" text; differences go to the review.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points go to akkreditierung_review.md next to this script; prune_inactive.prune() then
drops everything that is not currently valid.
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

AB_CODE = "AA"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://akkreditierung-austria.gv.at/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the register; recorded for all EA sectors"

# Register standard (docNr, national prefixes removed) -> (CertiFind standard, sector kind).
# Kind None: known and deliberately not imported, with the reason for the review.
STANDARDS = [
    (r"ISO 9001\b", "ISO 9001", "iaf"),
    (r"ISO 14001\b", "ISO 14001", "iaf"),
    (r"ISO 45001\b", "ISO 45001", "iaf"),
    (r"ISO 13485\b", "ISO 13485", "medical"),
    (r"ISO 50001\b", "ISO 50001", "energy"),
    (r"ISO 22000\b", "ISO 22000", "food"),
    (r"FSSC 22000\b", "FSSC 22000", "food"),
    (r"ISO/IEC 27001\b", "ISO/IEC 27001", "all"),
    (r"ISO/IEC 27701\b", "ISO/IEC 27701", "all"),
    (r"ISO/IEC 27017\b", "ISO/IEC 27017", "all"),
    (r"ISO/IEC 27018\b", "ISO/IEC 27018", "all"),
    (r"ISO/IEC 20000-1\b", "ISO/IEC 20000-1", "all"),
    (r"ISO/IEC 42001\b", "ISO/IEC 42001", "all"),
    (r"ISO 22301\b", "ISO 22301", "all"),
    (r"ISO 37001\b", "ISO 37001", "all"),
    (r"ISO 37301\b", "ISO 37301", "all"),
    (r"ISO 55001\b", "ISO 55001", "all"),
    (r"ISO 21001\b", "ISO 21001", "all"),
    (r"ISO 29993\b", "ISO 29993", "all"),
    (r"ISO 7101\b", "ISO 7101", "all"),
    (r"ISO 3834-[234]\b", "ISO 3834", "all"),
    (r"9100:", "AS 9100", "all"),
    (r"9110:", None, "EN 9110 (aviation maintenance organisations; not in CertiFind's standards)"),
    (r"ISO/IEC 27002\b", None, "ISO/IEC 27002 (guidance on controls, certified with ISO/IEC 27001)"),
    (r"ISO/IEC 27011\b", None, "ISO/IEC 27011 (telecom controls; not in CertiFind's standards)"),
    (r"ISO/IEC 27019\b", None, "ISO/IEC 27019 (energy-utility controls; not in CertiFind's standards)"),
    (r"ISO/IEC TR 20000-9\b", None, "ISO/IEC TR 20000-9 (cloud guidance for ISO/IEC 20000-1)"),
    (r"IEC 62443-2-1\b", None, "IEC 62443-2-1 (industrial automation security; not in CertiFind's standards)"),
    (r"ISO 29990\b", None, "ISO 29990 (withdrawn, replaced by ISO 29993)"),
    (r"\b15085-2\b", None, "EN 15085-2 (railway vehicle welding; not in CertiFind's standards)"),
    (r"TL 9000\b", None, "TL 9000 (telecom quality; not in CertiFind's standards)"),
    (r"SCC[- ]VAZ\b", None, "SCC-VAZ (Austrian contractor safety scheme)"),
    (r"AUVA-SGM\b", None, "AUVA-SGM (Austrian accident-insurance safety management scheme)"),
    (r"IT-Sicherheitskatalog", None, "IT-Sicherheitskatalog § 11 EnWG (German energy-sector law)"),
    (r"EUV 2018/762\b", None, "Regulation (EU) 2018/762 (railway safety management; not a certification standard)"),
    (r"EUV 2018/858\b", None, "Regulation (EU) 2018/858 (vehicle type approval, conformity of production)"),
    (r"2014/68/EU\b", None, "Directive 2014/68/EU module H (pressure equipment, notified body)"),
]
STANDARD_RES = [(re.compile(p), std, kind) for p, std, kind in STANDARDS]
PREFIX = re.compile(r"^(?:OEVE/OENORM|OENORM|ÖNORM|EN)\s+")

# Certification standard -> (accreditation standard, certificate-number suffix). Everything
# else is certified under the ISO/IEC 17021-1 row with the plain identification number.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27017": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27018": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "AS 9100": ("AS 9104-1", " (9104)"),
}

IAF_FIELD = re.compile(r"^90\.[014]\d\d\.(\d\d)\.[AMU]$")
CLUSTER_FIELD = re.compile(r"^90\.[014]\d\d\.00\.C((?:\.\d\d[AMU])+)$")
FOOD_FIELD = re.compile(r"^90\.(?:420|221)\.(A|AI|AII|B|BI|BII|BIII|C|C0|CI|CII|CIII|CIV|D|E|F|FI|FII|G|H|I|J|K)$")
ENERGY_FIELD = re.compile(r"^90\.600\.0([1-8])\.[AMU]$")
MEDICAL_FIELD = re.compile(r"^90\.500\.0([1-7])\.[AMU]$")
ENERGY_LETTER = dict(zip("12345678", "ABCDEFGH"))
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL_NAMES = {"1": "Non-active medical devices", "2": "Active (non-implantable) medical devices",
                 "3": "Active implantable medical devices", "4": "In vitro diagnostic medical devices",
                 "5": "Sterilization methods",
                 "6": "Devices incorporating specific substances / technologies",
                 "7": "Parts or services"}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
FOOD_ORDER = ["A", "AI", "AII", "B", "BI", "BII", "BIII", "C", "C0", "CI", "CII", "CIII", "CIV",
              "D", "E", "F", "FI", "FII", "G", "H", "I", "J", "K"]

# Restrictions printed with a code in the register's field/ range text, by scope id.
RESTRICTIONS = {
    "14475506": "EA 17 limited to fabricated metal products (Mechanische Industrie - Gefertigte Metallwaren)",
}
# Display names where the register's body name is a department of the legal entity.
DISPLAY = {
    "0920": "Technische Universität Graz – Europaprüfstelle für Medizinprodukte",
}
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def iso_date(raw: str) -> str:
    m = DATE.search(raw or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def classify(doc_nr: str):
    name = PREFIX.sub("", PREFIX.sub("", doc_nr.strip()))
    for rx, std, kind in STANDARD_RES:
        if rx.search(name):
            return std, kind
    return None, None


def range_codes(text: str) -> set[int] | None:
    m = re.search(r"IAF-Codes?\s+(.*)", text or "", re.S)
    if not m:
        return None
    body = re.sub(r"\([^)]*\)", "", m.group(1))
    return {int(n) for n in re.findall(r"\b(\d{1,2})\b", body)}


ENERGY_WORDS = {"A": r"leicht", "B": r"schwer", "D": r"Gebäudekomplex",
                "C": r"Gebäude(?!komplex)", "E": r"Transport", "F": r"Bergbau",
                "G": r"Landwirtschaft", "H": r"Energieversorgung"}


def energy_words(text: str) -> set[str]:
    """ISO 50003 technical areas named in a German field/ range text."""
    return {a for a, w in ENERGY_WORDS.items() if re.search(w, text or "")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    bodies = {b["body_id"]: b for b in read(args.scrape / "bodies.csv")}
    scopes = read(args.scrape / "scopes.csv")
    fields = defaultdict(list)
    for r in read(args.scrape / "technical_fields.csv"):
        fields[r["scope_id"]].append(r["field_number"].strip())
    attrs = defaultdict(dict)
    for r in read(args.scrape / "scope_attributes.csv"):
        attrs[r["scope_id"]][r["attribute_en"]] = r["value"]
    business = {}
    for r in read(args.scrape / "addresses.csv"):
        if r["type"] == "BUSINESS":
            business[r["body_id"]] = r

    review: list[str] = []
    body_rows, accreditations, scope_rows = [], [], []

    for body_id, b in sorted(bodies.items()):
        name = DISPLAY.get(body_id) or b["legal_entity"].strip() or b["name"].strip()
        issue = iso_date(b["initial_accreditation"])
        # standard -> {"codes": set, "notes": [..], "url": proof url, "detail": [...]}
        found: dict[str, dict] = {}
        for s in (s for s in scopes if s["body_id"] == body_id):
            if s["type"] != "N":
                continue
            if s["status"] != "VALID" or s["accreditation_standard"] != "EN ISO/IEC 17021-1:2015":
                review.append(f"{body_id} {s['standard']}: status {s['status']}, "
                              f"{s['accreditation_standard']}; not imported")
                continue
            std, kind = classify(s["standard"])
            if std is None:
                review.append(f"{body_id} {name}: {s['standard']} not imported — "
                              f"{kind or 'unknown standard, add a rule'}")
                continue
            entry = found.setdefault(std, {"codes": set(), "notes": [], "url": s["url"],
                                           "food": set(), "energy": set(), "medical": set()})
            nums = fields[s["scope_id"]]
            if kind == "iaf":
                codes = set()
                for n in nums:
                    if m := IAF_FIELD.match(n):
                        codes.add(int(m.group(1)))
                    elif m := CLUSTER_FIELD.match(n):
                        codes |= {int(c[:2]) for c in m.group(1).strip(".").split(".")}
                text = attrs[s["scope_id"]].get("field/ range", "")
                listed = range_codes(text)
                if listed is not None and listed != codes:
                    review.append(f"{body_id} {name} {s['standard']}: technical fields give "
                                  f"{ea_spec(codes) or 'none'}, field/ range lists "
                                  f"{ea_spec(listed)}; union used")
                    codes |= listed
                if not codes:
                    review.append(f"{body_id} {name} {s['standard']}: no IAF code; "
                                  f"recorded for all EA sectors")
                    codes = set(range(1, 40))
                    entry["notes"].append(ALL_NOTE)
                entry["codes"] |= codes
                if s["scope_id"] in RESTRICTIONS:
                    entry["notes"].append(RESTRICTIONS[s["scope_id"]])
            elif kind == "food":
                entry["food"] |= {m.group(1) for n in nums if (m := FOOD_FIELD.match(n))}
            elif kind == "energy":
                entry["energy"] |= {ENERGY_LETTER[m.group(1)] for n in nums
                                    if (m := ENERGY_FIELD.match(n))}
                entry["energy"] |= energy_words(attrs[s["scope_id"]].get("field/ range", ""))
            elif kind == "medical":
                entry["medical"] |= {m.group(1) for n in nums if (m := MEDICAL_FIELD.match(n))}
            else:
                entry["codes"] = set(range(1, 40))
                if ALL_NOTE not in entry["notes"]:
                    entry["notes"].append(ALL_NOTE)

        # Turn food / energy / medical areas into EA codes.
        for std, e in found.items():
            if e["food"]:
                cats = [c for c in FOOD_ORDER if c in e["food"]]
                e["codes"] = set().union(*(expand(esyd.FOOD_CATEGORIES[c[0]]) for c in cats))
                e["notes"] = ["ISO 22003-1 food chain categories: " + ", ".join(cats)
                              + " (classified to EA by category)"]
            elif std in ("ISO 22000", "FSSC 22000"):
                review.append(f"{body_id} {name} {std}: no food chain category; all EA sectors")
                e["codes"], e["notes"] = set(range(1, 40)), [ALL_NOTE]
            if e["energy"]:
                areas = sorted(e["energy"])
                e["codes"] = set().union(*(expand(ENERGY_EA[a]) for a in areas))
                e["notes"] = ["ISO 50003 technical areas: " + "; ".join(ENERGY_NAMES[a] for a in areas)
                              + " (classified to EA by area)"]
            elif std == "ISO 50001":
                review.append(f"{body_id} {name} ISO 50001: no technical area; all EA sectors")
                e["codes"], e["notes"] = set(range(1, 40)), [ALL_NOTE]
            if e["medical"]:
                areas = sorted(e["medical"])
                e["codes"] = set().union(*(expand(MEDICAL_EA[MEDICAL_NAMES[a]]) for a in areas))
                e["notes"] = ["IAF MD 8 main technical areas: " + "; ".join(MEDICAL_NAMES[a] for a in areas)
                              + " (classified to EA by area)"]
            elif std == "ISO 13485":
                review.append(f"{body_id} {name} ISO 13485: no technical area; all EA sectors")
                e["codes"], e["notes"] = set(range(1, 40)), [ALL_NOTE]

        # Cross-check ISO 50001 areas with the ISO 50003 applicable document.
        for s in scopes:
            if s["body_id"] == body_id and s["standard"].startswith("ISO 50003") and "ISO 50001" in found:
                listed = energy_words(attrs[s["scope_id"]].get("field/ range", ""))
                if listed and listed != found["ISO 50001"]["energy"]:
                    review.append(f"{body_id} {name}: ISO 50001 scope lists areas "
                                  f"{''.join(sorted(found['ISO 50001']['energy']))}, ISO 50003 document "
                                  f"lists {''.join(sorted(listed))} ({s['standard']}); ISO 50001 scope used")

        if not found:
            review.append(f"body {body_id} {name}: no importable standard; not imported")
            continue

        base_url = (found.get("ISO 9001") or next(iter(found.values())))["url"]
        rows_needed = {BASE: (body_id, base_url)}
        for std, e in found.items():
            if std in SCHEME_ROWS:
                acc_std, suffix = SCHEME_ROWS[std]
                rows_needed.setdefault(acc_std, (body_id + suffix, e["url"]))
        for acc_std, (cert, url) in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": issue, "expiry_date": "", "proof_url": url})
        for std, e in found.items():
            cert = body_id + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else body_id
            scope_rows.append({"certificate_number": cert, "certification_standard": std,
                               "ea_codes": ea_spec(e["codes"]), "status": "ACTIVE",
                               "scope_note": "; ".join(dict.fromkeys(e["notes"]))})
        if not any(std not in SCHEME_ROWS for std in found):
            review.append(f"{body_id} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")

        a = business.get(body_id) or {"street": b["street"], "postal_code": b["postal_code"],
                                      "city": b["city"]}
        address = ", ".join(p for p in (a["street"].strip(),
                                        f"{a['postal_code']} {a['city']}".strip()) if p)
        body_rows.append({
            "name": name, "country": "Austria", "registration_no": body_id,
            "phone": b["phones"].split(";")[0].strip(), "email": b["emails"].split(";")[0].strip(),
            "website": b["website"].strip().rstrip("/"), "address": address,
            "source_url": SOURCE_URL, "verified_at": "",
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

    with open(HERE / "akkreditierung_review.md", "w", encoding="utf-8") as f:
        f.write("# Akkreditierung Austria conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; "
          f"review: {HERE / 'akkreditierung_review.md'}")


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
