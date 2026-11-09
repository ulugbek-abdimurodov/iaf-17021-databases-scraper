#!/usr/bin/env python3
"""Turn the Lithuanian (NAB / LASA) register output into a CertiFind dataset.

Reads nab_ms_bodies/bodies.json (written by nab_scraper.py) for contacts and dates, and the
sector tables below, transcribed from each body's "Akreditavimo sritis" (scope) PDF:
IAF code | description | EVRK 2 (NACE rev. 2). The IAF code is the EA code. Each row's NACE
list is compared with IAF ID 1 (table and comparison reused from
database/bulgaria/prepare_certifind.py); a narrower list is noted as a limited scope.

    python prepare_certifind.py --out ../../certifind/data/lasa-lithuania
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
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

AB_CODE = "LASA"
COUNTRY = "Lithuania"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Certificate -> (name on the certificate, juridinio asmens kodas, address of the scope PDF).
BODIES = {
    "LA.04.001": ("Viešoji įstaiga „LST Sert“", "300076307", "Laisvės pr. 81-11, 06124 Vilnius"),
    "LA.04.002": ("UAB „Sertika“", "133827738", "Mituvos g. 2-255, 50131 Kaunas"),
    "LA.04.003": ("UAB „Euromatas“", "300092852", "Raudondvario pl. 168, 47172 Kaunas"),
    "LA.04.004": ("UAB „Bureau Veritas Lit“", "111512921", "Ukmergės g. 369A, 12142 Vilnius"),
    "LA.04.005": ("UAB „Sistemų registras“", "302834882", "Taikos pr. 131B, 51127 Kaunas"),
}

# Sector tables as printed (EA -> EVRK 2 / NACE cell). "išskyrus" is written as "except".
LST_9001 = {
    3: "10, 11, 12", 4: "13, 14", 8: "58.1, 59.2", 9: "18",
    17: "24 except 24.46, 25 except 25.4, 33.11", 18: "28, 33.12, 33.2",
    19: "26, 27, 33.13, 33.14, 95.1", 23: "31, 32, 33.19", 28: "41, 42, 43",
    29: "45, 46, 47, 95.2", 31: "49, 50, 52, 53, 61", 33: "58.2, 62, 63.1",
    34: "71, 72, 74 except 74.2, 74.3", 35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82",
    36: "84 except 84.21, 84.22", 37: "85", 38: "75, 86, 87, 88", 39: "96",
}
LST_14001 = {
    3: "10, 11, 12", 4: "13, 14", 17: "24 except 24.46, 25 except 25.4, 33.11",
    19: "26, 27, 33.13, 33.14, 95.1", 23: "31, 32, 33.19", 28: "41, 42, 43",
    29: "45, 46, 47, 95.2", 31: "49, 50, 52, 53, 61", 33: "58.2, 62, 63.1",
    34: "71, 72, 74 except 74.2, 74.3", 35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82",
    36: "84", 37: "85", 39: "96",
}
LST_45001 = {19: "26, 27, 33.13, 33.14, 95.1", 28: "41, 42, 43",
             35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 39: "96"}

SERTIKA_9001 = {
    2: "08.1", 4: "13, 14", 14: "22", 16: "23.6", 19: "26, 27, 33.13, 33.14, 95.1",
    23: "31, 32.50", 24: "38.3", 28: "41, 42, 43", 29: "45, 46, 47", 31: "49.41, 52",
    32: "68", 33: "58.2, 62, 63.1", 34: "71, 72, 74.1, 74.9",
    35: "69.2, 70.2, 73, 74.3, 81.2, 81.3, 82.92", 36: "84 except 84.21, 84.22", 37: "85",
    38: "86, 87", 39: "38.1, 38.2",
}
SERTIKA_14001 = {k: v for k, v in SERTIKA_9001.items() if k != 16}
SERTIKA_45001 = {k: SERTIKA_9001[k] for k in (2, 19, 23, 24, 28, 29, 31, 34, 39)}

EUROMATAS_9001 = {
    17: "24 except 24.46, 25 except 25.4, 33.11", 18: "28, 30.4, 33.12, 33.2",
    28: "41, 42, 43", 29: "45, 46, 47, 95.2", 31: "49, 52, 53, 61",
    32: "64, 65, 66, 68, 77", 34: "71, 72, 74 except 74.2, 74.3",
    35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 36: "84", 37: "85", 38: "88",
    39: "37, 38.1, 38.2, 39, 59.1, 60, 63.9, 79, 90, 91, 92, 93, 94, 96",
}
EUROMATAS_14001 = {k: EUROMATAS_9001[k] for k in (17, 28, 29, 31, 32, 34, 35, 36, 37)}

BV_45001 = {
    2: "08", 3: "10, 11, 12", 4: "13", 6: "16", 7: "17", 12: "20", 14: "22",
    15: "23 except 23.5, 23.6", 16: "23.6", 17: "24 except 24.46, 25 except 25.4",
    18: "25.4, 28, 30.4, 33.12, 33.2", 19: "26, 27, 33.13, 33.14, 95.1", 23: "31, 32, 33.19",
    24: "38.3", 25: "35.1", 26: "35.2", 27: "35.3, 36", 28: "41, 42, 43",
    29: "45, 46, 47, 95.2", 30: "56", 31: "52, 53, 61", 32: "64, 65, 66, 68, 77",
    33: "58.2, 62, 63.1", 34: "71, 72", 35: "80, 81", 37: "85", 39: "38.1, 38.2",
}

SR_ALL = {
    6: "16", 14: "22", 17: "24 except 24.46, 25 except 25.4, 33.11", 18: "28, 33.12, 33.2",
    23: "31, 32, 33.19", 28: "41, 42, 43", 29: "45, 46, 47", 31: "49, 52, 53",
    32: "64, 65, 66, 68, 77", 33: "58.2, 62, 63.1", 34: "71, 72, 74 except 74.2, 74.3",
    35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 36: "84", 37: "85", 38: "75, 86, 87, 88",
    39: "37, 38.1, 38.2, 39",
}

# Certificate number (with the scheme suffix used in the other datasets) ->
# (accreditation standard, [(certification standard, table or EA spec, extra note)]).
ACCREDITATIONS = {
    "LA.04.001": ("ISO/IEC 17021-1", [("ISO 9001", LST_9001, ""), ("ISO 14001", LST_14001, ""),
                                      ("ISO 45001", LST_45001, "")]),
    "LA.04.001 (22000)": ("ISO 22003-1", [("ISO 22000", "3", "ISO 22003-1 category C (CI and CIV only) "
                                           "(classified to EA by sector)")]),
    "LA.04.001 (27006)": ("ISO/IEC 27006", [("ISO/IEC 27001", "ALL", "No sector list in annex; "
                                             "recorded for all EA sectors")]),
    "LA.04.002": ("ISO/IEC 17021-1", [("ISO 9001", SERTIKA_9001, ""), ("ISO 14001", SERTIKA_14001, ""),
                                      ("ISO 45001", SERTIKA_45001, "")]),
    "LA.04.002 (27006)": ("ISO/IEC 27006", [("ISO/IEC 27001", "ALL", "No sector list in annex; "
                                             "recorded for all EA sectors")]),
    "LA.04.003": ("ISO/IEC 17021-1", [("ISO 9001", EUROMATAS_9001, ""),
                                      ("ISO 14001", EUROMATAS_14001, ""),
                                      ("ISO 45001", EUROMATAS_14001, "")]),
    "LA.04.004": ("ISO/IEC 17021-1", [("ISO 45001", BV_45001, "")]),
    "LA.04.005": ("ISO/IEC 17021-1", [("ISO 9001", SR_ALL, ""), ("ISO 14001", SR_ALL, ""),
                                      ("ISO 45001", SR_ALL, "")]),
}


def scope(cert: str, standard: str, table, extra: str, problems: list[str]) -> dict:
    notes = []
    if isinstance(table, str):
        spec = table
    else:
        limited = {}
        for ea, cell in table.items():
            listed = bas.parse_nace(cell)
            outside = [str(n) for n in listed if bas.ea_of_nace([n]) - {ea}]
            if outside:
                problems.append(f"{cert} {standard}: EA {ea} lists NACE outside the sector: {outside}")
            if bas.is_limited(ea, listed):
                limited[ea] = listed
        spec = bas.ea_spec(set(table))
        if limited:
            notes.append("Limited scope (part of the sector): " + "; ".join(
                f"EA {ea} (NACE {', '.join(map(str, items))})" for ea, items in sorted(limited.items())))
    if extra:
        notes.append(extra)
    return {"certificate_number": cert, "certification_standard": standard, "ea_codes": spec,
            "status": "ACTIVE", "scope_note": "; ".join(notes)}


def phone(raw: str) -> str:
    return raw.split(",")[0].strip()


def website(raw: str) -> str:
    raw = (raw or "").strip()
    return raw if not raw or raw.startswith("http") else "http://" + raw


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=HERE / "nab_ms_bodies" / "bodies.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    records = {}
    for item in json.loads(args.src.read_text(encoding="utf-8")):
        rec = item.get("record", item)
        records[rec["certificate"]] = (item, rec)

    bodies, accreditations, scopes, problems = [], [], [], []
    for cert, (name, reg_no, address) in BODIES.items():
        item, rec = records[cert]
        url = item.get("detail_url", "")
        bodies.append({"name": name, "country": COUNTRY, "registration_no": reg_no,
                       "phone": phone(rec.get("phoneNumber") or ""),
                       "email": (rec.get("email") or "").split(";")[0].strip(),
                       "website": website(rec.get("website")),
                       "address": f"{address}, {COUNTRY}", "source_url": url, "verified_at": ""})
    for number, (acc_std, sections) in ACCREDITATIONS.items():
        base = number.split(" ")[0]
        item, rec = records[base]
        valid_from = "-".join(f"{x:02d}" for x in rec["validFrom"])
        valid_to = "-".join(f"{x:02d}" for x in rec["validTo"])
        accreditations.append({"ab_code": AB_CODE, "certificate_number": number,
                               "body_name": BODIES[base][0], "accreditation_standard": acc_std,
                               "status": "ACTIVE", "issue_date": valid_from, "expiry_date": valid_to,
                               "proof_url": item.get("detail_url", "")})
        for standard, table, extra in sections:
            scopes.append(scope(number, standard, table, extra, problems))

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, bodies)
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    for p in problems:
        print("CHECK:", p)
    print(f"{len(bodies)} bodies, {len(accreditations)} accreditations, {len(scopes)} scope rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
