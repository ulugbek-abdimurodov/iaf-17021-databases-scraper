#!/usr/bin/env python3
"""Convert the UAF (United Accreditation Foundation, USA) MS-CAB scrape into a CertiFind dataset (data/uaf-united-states).

Input: <scrape>/raw/uaf.json written by database/united-states/scrape_us_uaf.py:
[{n,sc,w,e,p,co,ci,st,z,a,id,docs:[{u,s:[[std,acc_no,from,to,iaf,cats,mdIdx]]}],x:[scheme names not parsed]}]
iaf = IAF codes (9001/14001/45001), cats = ISO 22003-1 letters (22000), mdIdx = digits 0-6 into IAF MD 8
main technical areas (13485). x = further schemes on the certificate, printed without number or dates.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug NAMES]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import types
from datetime import date, datetime
from pathlib import Path

# Shared website check (../database/contact_check.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contact_check import website as checked_website  # noqa: E402


HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent  # .../CertiFind/database


def _load(name: str, path: Path):
    sys.modules.setdefault("requests", types.ModuleType("requests"))  # greece module imports it; unused here
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", DB / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "UAF"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://www.uafaccreditation.org/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the UAF schedule; recorded for all EA sectors"

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
    "ISO 20121": ("ISO/IEC 17021-4", "20121"),
}
_MED = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
MD = ["Non-active medical devices", "Active implantable medical devices", "Active (non-implantable) medical devices",
      "In vitro diagnostic medical devices", "Sterilization methods",
      "Devices incorporating specific substances / technologies", "Parts or services"]  # UAF/IAF MD 8 order
# "x" scheme names (normalised: lower, letters only) -> standard
EXTRA = [("antibribery", "ISO 37001"), ("artificialintelligence", "ISO/IEC 42001"),
         ("educationalorganizations", "ISO 21001"), ("assetmanagement", "ISO 55001"),
         ("compliancemanagement", "ISO 37301"), ("facilitymanagement", "ISO 41001"),
         ("eventsustainability", "ISO 20121")]
COUNTRY = {"Republic of Korea": "South Korea"}
DIAL = {"India": "91", "United States": "1", "United Arab Emirates": "971", "South Korea": "82",
        "United Kingdom": "44", "China": "86", "Morocco": "212", "Netherlands": "31", "Turkey": "90",
        "Jordan": "962", "Philippines": "63"}
NSN_LEN = {"91": {10}, "1": {10}, "44": {10}, "86": {10, 11}, "82": {8, 9, 10}, "971": {8, 9},
           "212": {9}, "31": {9}, "90": {10}, "962": {8, 9}, "63": {9, 10}}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def key(s: str) -> str:
    s = " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())
    return " ".join(re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|pvt|private|the|sa|de|cv|a s|as)\b",
                           " ", s).split())


def iso(d: str) -> str:
    try:
        return datetime.strptime(d.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def phone(raw: str, country: str, review: list, name: str) -> str:
    raw = (raw or "").strip()
    if raw in ("", "undefined", "null"):
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    elif not raw.startswith("+"):
        digits = DIAL.get(country, "") + digits.lstrip("0")
    cc = next((c for c in sorted(set(DIAL.values()), key=len, reverse=True) if digits.startswith(c)), "")
    if raw.startswith("+0"):  # "+022 ..." national number with trunk 0 -> body's own country
        cc, digits = DIAL.get(country, ""), DIAL.get(country, "") + digits.lstrip("0")
    nsn = digits[len(cc):].lstrip("0") if cc else ""
    if not cc or len(nsn) not in NSN_LEN.get(cc, set(range(7, 13))):
        review.append(f"{name}: phone '{raw}' could not be made a valid international number; left empty")
        return ""
    if cc == "1":
        return f"+1 {nsn[:3]} {nsn[3:6]} {nsn[6:]}"
    return f"+{cc} {nsn}"


def load_existing(data_root: Path, out: Path) -> dict:
    ex: dict = {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent.resolve() == out.resolve():
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                ex.setdefault((key(r["name"]), r["country"]), []).append((f.parent.name, r))
    return ex


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", default="")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    debug = {d.strip().casefold() for d in args.debug.split(",") if d.strip()}
    existing = load_existing(args.out.parent, args.out)

    review: list[str] = []
    skipped: dict[str, list[str]] = {}
    bodies, accs, scopes = {}, {}, {}
    for b in json.loads((args.scrape / "raw" / "uaf.json").read_text(encoding="utf-8")):
        name = re.sub(r"\s+", " ", b["n"]).strip()
        country = COUNTRY.get(b["co"], b["co"])
        if name.casefold() in debug:
            print(json.dumps(b, ensure_ascii=False, indent=1))
        # (std, acc_no, from, to, ea, note, proof)
        rows = []
        for doc in b["docs"]:
            for std, no, f, t, iaf, cats, md in doc["s"]:
                if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
                    ea = {int(x) for x in iaf.split(",") if x.strip()} & ALL
                    note = "IAF codes from the UAF schedule"
                elif std == "ISO 22000" and cats:
                    ea = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
                    note = f"ISO 22003-1 categories {', '.join(sorted(set(cats)))} classified to EA"
                elif std == "ISO 13485" and md:
                    areas = [MD[int(i)] for i in sorted(set(md))]
                    ea = set().union(*(expand(_MED[a]) for a in areas))
                    note = "IAF MD 8 areas classified to EA: " + "; ".join(areas)
                else:
                    ea, note = ALL, ALL_NOTE
                if not ea:
                    review.append(f"{name} {std}: no sectors parsed; recorded for all EA sectors")
                    ea, note = ALL, ALL_NOTE
                rows.append((std, no.strip(), iso(f), iso(t), ea, note, doc["u"]))
        if not rows:
            review.append(f"{name}: no accreditation table parsed; dropped")
            continue

        match = existing.get((key(name), country))
        if match:
            exact = [m for m in match if m[1]["name"] == name]
            ds, row = (exact or match)[0]
            body = dict(row)
            review.append(f"{name}: reuses body row '{row['name']}' from {ds}")
        else:
            body = {"name": name, "country": country, "registration_no": b["sc"].strip(),
                    "phone": phone(b["p"], country, review, name), "email": (b["e"] or "").strip(),
                    "website": checked_website(b["w"]),
                    "address": ", ".join(p.strip() for p in (b["a"], b["ci"], b["st"], b["z"]) if p and p.strip()),
                    "source_url": SOURCE_URL, "verified_at": ""}
            if body["website"] and not body["website"].startswith("http"):
                body["website"] = "https://" + body["website"]
        if body["name"] in bodies:
            raise SystemExit(f"duplicate body name {body['name']}")
        bodies[body["name"]] = body

        certs: dict[str, str] = {}  # accreditation standard -> certificate number
        for std, no, f, t, ea, note, proof in rows:
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            if acc_std not in certs:
                certs[acc_std] = f"{no} ({suffix})" if suffix else no
            elif no != certs[acc_std].split(" (")[0]:
                review.append(f"{name}: {std} accreditation {no} merged into {certs[acc_std]}")
            c = certs[acc_std]
            a = accs.setdefault(c, {"ab_code": AB_CODE, "certificate_number": c, "body_name": body["name"],
                                    "accreditation_standard": acc_std, "status": "ACTIVE", "issue_date": f,
                                    "expiry_date": t, "proof_url": proof})
            if f and f < a["issue_date"]:
                a["issue_date"] = f
            if t and t > a["expiry_date"]:
                a["expiry_date"] = t
            s = scopes.setdefault((c, std), {"certificate_number": c, "certification_standard": std,
                                             "ea": set(), "status": "ACTIVE", "scope_note": note})
            s["ea"] |= ea

        # schemes printed without accreditation number / dates
        for xname in b["x"]:
            k = re.sub(r"[^a-z]", "", xname.lower())
            std = next((s for p, s in EXTRA if p in k), None)
            if std and SCHEME_ROWS.get(std, (BASE,))[0] == BASE and BASE in certs:
                c = certs[BASE]
                scopes.setdefault((c, std), {"certificate_number": c, "certification_standard": std, "ea": set(ALL),
                                             "status": "ACTIVE",
                                             "scope_note": ALL_NOTE + " (listed on the UAF certificate without a "
                                                           "separate accreditation number)"})
            else:
                why = ("no accreditation number or dates in the scrape for its own "
                       f"{SCHEME_ROWS[std][0]} row" if std else "not a management system standard in the standards table")
                skipped.setdefault(f"{std or xname.strip()} ({why})", []).append(name)

    body_rows = list(bodies.values())
    scope_rows = [{**{k: v for k, v in s.items() if k != "ea"}, "ea_codes": ea_spec(s["ea"])} for s in scopes.values()]
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs.values(), key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accs), len(scope_rows))

    sys.path.insert(0, str(DB))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "uaf_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# UAF conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                 f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        fh.writelines(f"- {line}\n" for line in review)
        fh.write("\n## Schemes not imported (scheme: bodies)\n\n")
        for s, ids in sorted(skipped.items()):
            fh.write(f"- {s}: {'; '.join(ids)}\n")
        fh.write("\n## Removed by prune_inactive\n\n")
        fh.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'uaf_review.md'}")


if __name__ == "__main__":
    main()
