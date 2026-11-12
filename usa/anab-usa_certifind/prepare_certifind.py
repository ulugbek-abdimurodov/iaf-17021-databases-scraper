#!/usr/bin/env python3
"""Convert the ANAB management-systems directory scrape into a CertiFind dataset (data/anab-usa).

Input: <scrape>/database/usa/anab_raw.psv written by scrape_us_anab.py, one line per CB:
id|title|since|expires|pdf_address|dir_country|website|phone|email|pkey|orgid|in_scope_schemes|other_schemes
in_scope_schemes = "STD=codes;..." with IAF codes (9001/14001/45001), ISO 22003-1 categories
(22000/FSSC), IAF MD 8 area numbers 1.1-1.7 (13485); empty codes = no sector list in the PDF.
other_schemes = comma list of schemes the scraper did not parse codes for. Short lines
"id|title|other_schemes" are CBs holding only such schemes.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
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

AB_CODE = "ANAB"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://anabdirectory.remoteauditor.com/"
PDF_URL = "https://anab.jadian.com/Certificate.mvc?PKey={}&useId=true&OrgId={}"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the ANAB scope; recorded for all EA sectors"

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
}
# other_schemes entries that are in the standards table (no sector list -> all EA)
OTHER = {"AS9100": "AS 9100", "ISO/IEC 42001": "ISO/IEC 42001", "ISO 37001": "ISO 37001",
         "ISO 37301": "ISO 37301", "ISO 55001": "ISO 55001", "ISO 28000": "ISO 28000",
         "ISO 15378": "ISO 15378"}
SKIP_WHY = {
    "AS9110": "not in the standards table", "AS9120": "not in the standards table",
    "AS6081": "not in the standards table", "TL 9000": "not in the standards table",
    "RC14001": "US national scheme (Responsible Care)", "R2": "electronics recycling sector scheme, not in the standards table",
    "RIOS": "recycling sector scheme, not in the standards table", "SFI": "North American forestry scheme",
    "ATFS": "US national forestry scheme", "BA 9000": "US national scheme (body armor)",
    "SN 9001": "not in the standards table", "FAMI-QS": "not in the standards table",
    "Leading Harvest": "US national agriculture scheme",
}
ENERGY = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
_MED = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
# IAF MD 8 main technical areas numbered as in the ANAB scope PDFs
MD8 = {
    "1.1": _MED["Non-active medical devices"],
    "1.2": _MED["Active (non-implantable) medical devices"],
    "1.3": _MED["Active implantable medical devices"],
    "1.4": _MED["In vitro diagnostic medical devices"],
    "1.5": _MED["Sterilization methods"],
    "1.6": _MED["Devices incorporating specific substances / technologies"],
    "1.7": _MED["Parts or services"],
}
COUNTRY = {"KOREA, REPUBLIC OF": "South Korea", "CZECH REPUBLIC": "Czechia"}
# Countries for short records (no directory address)
SHORT_COUNTRY = {"6950": "India", "1036": "China", "5479": "Singapore", "4287": "United States",
                 "1033": "United States", "1032": "United States", "3467": "United States", "1431": "United States"}
DIAL = {"United States": "1", "Canada": "1", "Jamaica": "1", "China": "86", "India": "91", "United Kingdom": "44",
        "Mexico": "52", "Japan": "81", "Israel": "972", "Australia": "61", "United Arab Emirates": "971",
        "Italy": "39", "France": "33", "Spain": "34", "South Korea": "82", "Denmark": "45", "Czechia": "420",
        "Peru": "51"}


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
    return datetime.strptime(d.strip(), "%d %B %Y").date().isoformat() if d.strip() else ""


def phone(raw: str, country: str, review: list, name: str) -> str:
    p = re.split(r"\s*(?:x|ext\.?|X)\s*\d+\s*$", raw.strip())[0]
    p = p.split("/")[0].strip()
    if not p:
        return ""
    cc = DIAL.get(country, "")
    p = p.replace("(0)", "").replace("(", "").replace(")", "")
    digits = re.sub(r"\D", "", p)
    if p.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("011"):  # US international prefix
        digits = digits[3:]
    elif cc == "1" and len(digits) == 11 and digits.startswith("1"):
        pass
    elif cc == "1" and len(digits) == 10:
        digits = "1" + digits
    elif cc and digits.startswith(cc) and len(digits) > len(cc) + 7:
        pass
    else:
        review.append(f"{name}: phone '{raw}' could not be made international; left empty")
        return ""
    # US numbers written "+669..." (missing 1)
    if p.startswith("+") and country == "United States" and len(digits) == 10 and digits[0] != "1":
        digits = "1" + digits
    if len(digits) < 9 or len(digits) > 15:
        review.append(f"{name}: phone '{raw}' invalid; left empty")
        return ""
    for c in sorted(set(DIAL.values()) | {"48", "55", "90"}, key=len, reverse=True):
        if digits.startswith(c):
            if c == "1":
                rest = digits[1:]
                return f"+1 {rest[:3]} {rest[3:6]} {rest[6:]}"
            # keep the published digit groups after the country code; drop trunk 0
            tokens = re.findall(r"\d+", p)
            skip = len(re.sub(r"\D", "", p)) - len(digits) + len(c)
            out = []
            for t in tokens:
                if skip >= len(t):
                    skip -= len(t)
                    continue
                out.append(t[skip:]); skip = 0
            if out and out[0].startswith("0") and c != "39":
                out[0] = out[0].lstrip("0")
            return "+" + c + " " + " ".join(t for t in out if t)
    review.append(f"{name}: phone '{raw}' has an unknown country code; left empty")
    return ""


def address(raw: str, name: str) -> str:
    parts = [p.strip() for p in raw.split(" ~ ") if p.strip()]
    if parts and key(parts[0]) == key(name):
        parts = parts[1:]
    s = ", ".join(parts)
    s = re.sub(r"D istrict of C olumbia", "District of Columbia", s)
    return re.sub(r"\s+", " ", s).strip()


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
    debug = set(filter(None, args.debug.split(",")))
    existing = load_existing(args.out.parent, args.out)

    review: list[str] = []
    skipped: dict[str, list[str]] = {}
    bodies, accs, scopes = {}, {}, []
    seen_ids: dict[str, str] = {}
    raw = (args.scrape / "database" / "usa" / "anab_raw.psv").read_text(encoding="utf-8")
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("|")
        if len(f) == 3:
            rid, name, other = f
            since = exp = addr = ctry = web = ph = email = pk = org = ""
            in_scope = ""
            country = SHORT_COUNTRY.get(rid, "United States")
            review.append(f"{name} (MS-{rid}): directory gives no address or dates; country set to {country}")
        else:
            rid, name, since, exp, addr, ctry, web, ph, email, pk, org, in_scope, other = f
            country = COUNTRY.get(ctry, ctry.title())
        name = re.sub(r"\s+", " ", name).strip()
        cert = f"MS-{rid}"
        if rid in seen_ids:
            review.append(f"{name} ({cert}): ANAB id already used by {seen_ids[rid]}; record skipped")
            continue
        seen_ids[rid] = name
        proof = PDF_URL.format(pk, org) if pk else SOURCE_URL

        stds: list[tuple[str, set[int], str]] = []
        for part in filter(None, in_scope.split(";")):
            std, codes = part.split("=")
            codes = codes.strip()
            if not codes:
                stds.append((std, ALL, ALL_NOTE))
            elif std in ("ISO 9001", "ISO 14001", "ISO 45001"):
                stds.append((std, expand(codes.replace(",", ";")) & ALL, "IAF codes from the ANAB scope"))
            elif std in ("ISO 22000", "FSSC 22000"):
                ea = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in codes.split(",")))
                stds.append((std, ea, f"ISO 22003-1 categories {codes} classified to EA"))
            elif std == "ISO 13485":
                ea = set().union(*(expand(MD8[c]) for c in codes.split(",")))
                stds.append((std, ea, f"IAF MD 8 areas {codes} classified to EA"))
            elif std == "ISO 50001":
                ea = set().union(*(expand(ENERGY[c]) for c in codes.split(",")))
                stds.append((std, ea, f"ISO 50003 technical areas {codes} classified to EA"))
            else:
                stds.append((std, ALL, ALL_NOTE))
        for o in filter(None, (x.strip() for x in other.split(","))):
            if o in OTHER:
                stds.append((OTHER[o], ALL, ALL_NOTE))
            else:
                skipped.setdefault(f"{o} ({SKIP_WHY.get(o, 'not in the standards table')})", []).append(f"{name} ({cert})")
        if rid in debug:
            print(rid, name, stds)
        if not stds:
            review.append(f"{name} ({cert}): no importable scheme; dropped")
            continue
        if not since:
            review.append(f"{name} ({cert}): no accreditation date in the directory (importer requires one); "
                          f"dropped ({', '.join(s[0] for s in stds)})")
            continue

        match = existing.get((key(name), country))
        if match:
            exact = [m for m in match if m[1]["name"] == name]
            ds, row = (exact or match)[0]
            body = dict(row)
            review.append(f"{name} ({cert}): reuses body row '{row['name']}' from {ds}")
        else:
            body = {"name": name, "country": country, "registration_no": cert,
                    "phone": phone(ph, country, review, name), "email": email.strip(),
                    "website": checked_website(web, context=name), "address": address(addr, name), "source_url": SOURCE_URL,
                    "verified_at": ""}
        if body["name"] in bodies:
            review.append(f"{name} ({cert}): body name already used in this dataset; registrations merged")
            cert = bodies[body["name"]]["_cert"]
        else:
            bodies[body["name"]] = {**body, "_cert": cert}
        for std, ea, note in stds:
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            c = f"{cert} ({suffix})" if suffix else cert
            accs.setdefault(c, {"ab_code": AB_CODE, "certificate_number": c, "body_name": body["name"],
                                "accreditation_standard": acc_std, "status": "ACTIVE", "issue_date": iso(since),
                                "expiry_date": iso(exp), "proof_url": proof})
            if any(s["certificate_number"] == c and s["certification_standard"] == std for s in scopes):
                continue
            if not ea:
                review.append(f"{name} ({cert}) {std}: codes gave no EA sector; recorded for all")
                ea, note = ALL, ALL_NOTE
            scopes.append({"certificate_number": c, "certification_standard": std, "ea_codes": ea_spec(ea),
                           "status": "ACTIVE", "scope_note": note})

    body_rows = [{k: v for k, v in b.items() if k != "_cert"} for b in bodies.values()]
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs.values(), key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accs), len(scopes))

    sys.path.insert(0, str(DB))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "anab_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# ANAB conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                 f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        fh.writelines(f"- {line}\n" for line in review)
        fh.write("\n## Schemes not imported (scheme: bodies)\n\n")
        for s, ids in sorted(skipped.items()):
            fh.write(f"- {s}: {'; '.join(ids)}\n")
        fh.write("\n## Removed by prune_inactive\n\n")
        fh.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'anab_review.md'}")


if __name__ == "__main__":
    main()
