"""Convert the KENAS scrape into the CertiFind dataset data/kenas-kenya/.

Usage: python prepare_certifind.py <scrape dir with register.json> <dataset dir> [--today YYYY-MM-DD]

The KENAS schedules are scanned images with no text layer and no OCR available, so the
scopes below were transcribed by hand from the schedule PDFs (pdf/<id>.pdf, downloaded
2026-11-10). Sector codes are the IAF codes printed in the schedules; ISO 22000 food
categories and ISO 13485 technical areas are classified with the ESYD tables.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_URL = "https://kenas.go.ke/status"

spec = importlib.util.spec_from_file_location("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
esyd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(esyd)
FOOD = esyd.FOOD_CATEGORIES
MED = {name: codes for name, _, codes in esyd.MEDICAL_AREAS}

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
}

# (standard, codes, note) per registration, transcribed from the schedules.
SCOPES = {
    "KENAS/CB/001": [
        ("ISO 9001", "1;3;30", ""),
        ("ISO 13485", MED["Non-active medical devices"] + ";" + MED["Sterilization methods"],
         "Non-active medical devices (catheters, gowns, surgical gloves, wound care); EO sterilization"),
        ("ISO/IEC 27001", "29;32;33;35;36;37", ""),
    ],
    "KENAS/CB/03": [
        ("ISO 9001", "4;5;6;7;8;9;10;12;14;17;19;23;29;32;33;35;36;37", "EA 7 limited to paper products and pulp/paper manufacturing"),
        ("ISO 14001", "7;10;12;13;14;15;16;17;19", "EA 7 limited to pulp and paper manufacturing; EA 17 limited to base metals production"),
        ("ISO 45001", "12;14;17;19", "EA 17 limited to base metals production"),
    ],
    "KENAS/CB/02": [
        ("ISO 9001", "1;3;7;8;9;10;12;14;17;18;19;20;22;23;28;29;30;31;32;33;34;35;36;37", "EA 7 limited to paper products"),
        ("ISO 14001", "14;19;22", ""),
        ("ISO 22000", FOOD["C"], "Food chain category C (food manufacturing)"),
    ],
    "KENAS/CB/028": [
        ("ISO 9001", "23;31;33;35;38", "EA 31 limited to NACE 37, 38.1, 38.2, 39 (waste)"),
        ("ISO 14001", "23;31", "EA 31 limited to NACE 37, 38.1, 38.2, 39 (waste)"),
        ("ISO 45001", "31", "Limited to NACE 37, 38.1, 38.2, 39 (waste)"),
        ("ISO/IEC 27001", "32;33;35;36", "Schedule prints code 37 next to 'Financial intermediation'; recorded as EA 32"),
        ("ISO/IEC 27701", "35", ""),
        ("ISO 22301", "32", ""),
    ],
    "KENAS/CB/038": [
        ("ISO 9001", "1;3;30", ""),
        ("ISO 22000", FOOD["C"], "Food chain category C (food manufacturing)"),
    ],
    "KENAS/MsCB/37": [
        ("ISO 13485", MED["Non-active medical devices"], "Non-active medical devices with measuring function (OBM drapes)"),
    ],
}
SKIPPED = {
    "KENAS/CB/001": "SANS 10330:2020 HACCP (South African national scheme, not in standards table)",
    "KENAS/Ms.CB/021": "SafeCare standards health facility certification (not in standards table); body dropped",
}
WEBSITES = {
    "KENAS/CB/001": "https://www.kebs.org",
    "KENAS/CB/038": "https://www.globalsusa.com",
    "KENAS/MsCB/37": "https://www.jengazetuafrica.com",
}
# Effective date of the latest (re-)assessment in each schedule's accreditation history.
# BV's schedule (dated 2023) stops at the 2020 re-assessment; 2024-02-17 is inferred from the
# register expiry 2028-02-17 (4-year cycle, same day as the 2014/2017/2020 cycle starts).
ISSUED = {"KENAS/CB/001": "2024-03-17", "KENAS/CB/03": "2024-02-17", "KENAS/CB/02": "2022-12-03",
          "KENAS/CB/028": "2023-12-21", "KENAS/CB/038": "2025-07-11", "KENAS/MsCB/37": "2025-09-05"}
PHONES = {"KENAS/CB/038": "+254 721 351089"}  # register lists a US and a Kenyan number


def write(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", default=dt.date.today().isoformat())
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    reg = json.load(open(a.scrape / "register.json", encoding="utf-8"))

    bodies, accs, scopes, review = [], [], [], []
    for r in reg:
        cid = r["id"]
        if cid in SKIPPED:
            review.append(f"- {cid} {r['name']}: skipped {SKIPPED[cid]}")
        if cid not in SCOPES:
            continue
        if r["expiry"] < a.today:
            review.append(f"- {cid} {r['name']}: expired {r['expiry']}, dropped")
            continue
        bodies.append(dict(name=r["name"], country="Kenya", registration_no=cid,
                           phone=PHONES.get(cid, r["phone"]), email=r["email"],
                           website=WEBSITES.get(cid, ""), address=r["address"],
                           source_url=SOURCE_URL, verified_at=""))
        rows = {}
        for std, codes, note in SCOPES[cid]:
            acc_std, suffix = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", None))
            cert = f"{cid} ({suffix})" if suffix else cid
            rows.setdefault(cert, acc_std)
            scopes.append(dict(certificate_number=cert, certification_standard=std,
                               ea_codes=codes, status="ACTIVE", scope_note=note))
        if cid not in rows:  # every body needs its ISO/IEC 17021-1 row
            rows = {cid: "ISO/IEC 17021-1", **rows}
        for cert, acc_std in rows.items():
            accs.append(dict(ab_code="KENAS", certificate_number=cert, body_name=r["name"],
                             accreditation_standard=acc_std, status="ACTIVE", issue_date=ISSUED[cid],
                             expiry_date=r["expiry"], proof_url=r["schedule"]))

    write(a.out / "bodies.csv", ["name", "country", "registration_no", "phone", "email", "website",
                                 "address", "source_url", "verified_at"], bodies)
    write(a.out / "accreditations.csv", ["ab_code", "certificate_number", "body_name",
                                         "accreditation_standard", "status", "issue_date",
                                         "expiry_date", "proof_url"], accs)
    write(a.out / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes",
                                 "status", "scope_note"], scopes)
    (HERE / "kenas_review.md").write_text(
        f"# KENAS review ({a.today})\n\nRegister lists 18 CBs: 7 management-system, 8 product (ISO/IEC 17065) "
        "and 3 personnel (ISO/IEC 17024); only management-system CBs are considered.\n\n"
        "Scopes transcribed by hand from scanned schedules (no text layer).\n\n"
        "Skipped / notes:\n" + "\n".join(review) + "\n", encoding="utf-8")
    print(len(bodies), "bodies,", len(accs), "accreditations,", len(scopes), "scopes")


if __name__ == "__main__":
    main()
