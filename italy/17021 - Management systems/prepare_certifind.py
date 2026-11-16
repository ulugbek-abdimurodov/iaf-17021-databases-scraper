#!/usr/bin/env python3
"""Convert the ACCREDIA (Italy) ISO/IEC 17021-1 scrape into a CertiFind dataset (data/accredia-italy).

Input: <scrape>/database/italy/accredia_raw.json written by scrape_it_accredia.py, one list per CB:
[id, name, website, address, phone, email, certificate_no, issue_date dd/mm/yyyy, expiry, schemes, other]
schemes = [[standard, flag, codes]] (flag I = IAF sectors, T = technical areas, C = ISO 22003-1 categories,
S = ISO 22301 sectors, N = NACE codes) or [[standard]] without codes. other = ";"-separated further
schemes listed without codes ("other MS schemes only" when the scraper could not name them).

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
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

HERE = Path(__file__).resolve().parent
DB = HERE.parent  # .../CertiFind/database


def _load(name: str, path: Path):
    sys.modules.setdefault("requests", types.ModuleType("requests"))  # greece module imports it; unused here
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", DB / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "ACCREDIA"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310"
DETAIL_URL = SOURCE_URL + "&PPSEARCH_ORG_SEARCH_MASK_ORG={}"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the ACCREDIA register; recorded for all EA sectors"

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
    "ISO 20121": ("ISO/IEC 17021-4", "20121"),
}
# "other" schemes in the standards table (no sector list -> all EA)
OTHER_OK = {"ISO 37001", "ISO 39001", "ISO 21001", "ISO 20121", "ISO 28000", "ISO 55001", "ISO 37301", "ISO 19443",
            "ISO/IEC 42001", "ISO 21401", "ISO 29001", "ISO 56001", "ISO 7101", "AS 9100"}
ALIAS = {"EN 9100": "AS 9100"}  # European edition of AS 9100
OTHER_WHY = {"UNI/PdR 74": "Italian national scheme (UNI reference practice)",
             "UNI 11337-8": "Italian national scheme (UNI BIM standard)",
             "PAS 24000": "not in the standards table",
             "other MS schemes only": "register lists further management system schemes the scraper could not name"}
# ISO 50003:2021 technical areas as numbered by ACCREDIA -> ESYD letters
ENERGY_NUM = {"1.1": "A", "1.2": "B", "2.1": "C", "2.2": "D", "3.0": "E", "4.0": "F", "5.0": "G", "6.0": "H"}
ENERGY = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
_MED = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
MD8 = {  # IAF MD 8 tables 1.1-1.7 (ACCREDIA may add sub-codes 1.2.A, 1.7.E ...)
    "1.1": _MED["Non-active medical devices"], "1.2": _MED["Active (non-implantable) medical devices"],
    "1.3": _MED["Active implantable medical devices"], "1.4": _MED["In vitro diagnostic medical devices"],
    "1.5": _MED["Sterilization methods"], "1.6": _MED["Devices incorporating specific substances / technologies"],
    "1.7": _MED["Parts or services"],
}
COUNTRIES = ["Bosnia and Herzegovina", "Liechtenstein", "Switzerland", "Kosovo", "Israel", "India", "Italy", "Ukraine"]
NAME_COUNTRY = {"PT Bureau Veritas Indonesia": "Indonesia"}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def key(s: str) -> str:
    s = " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())
    return " ".join(re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|pvt|private|the|sa|de|cv|a s|as|"
                           r"s r l|srl|s p a|spa|s c a r l|scarl|s a s|sas|s n c|snc|s c|sc|ag|unipersonale)\b",
                           " ", s).split())


def iso(d: str) -> str:
    try:
        return datetime.strptime(d.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def split_country(addr: str, name: str) -> tuple[str, str]:
    a = re.sub(r"\s+", " ", addr).strip()
    country = NAME_COUNTRY.get(name, "")
    for c in COUNTRIES:
        if a.endswith(" " + c) or a == c:
            country, a = c, a[: -len(c)].strip()
            break
    # "C. da Cucullo66026 - ORTONA (CH)ABRUZZO" -> "C. da Cucullo, 66026 ORTONA (CH), ABRUZZO"
    a = re.sub(r"(?<=\D)(\d{5}) - ", r", \1 ", a)
    a = re.sub(r"(?<=\D)(\d{4,7}) - ", r", \1 ", a)
    a = re.sub(r"\)(?=[A-Z])", "), ", a)
    a = re.sub(r"(?<=[a-z])(?=[A-Z]{2,})", ", ", a)
    return a.strip(" ,"), country or "Italy"


DIAL = {"Italy": "39", "Switzerland": "41", "Bosnia and Herzegovina": "387", "Kosovo": "383", "Ukraine": "380",
        "India": "91", "Israel": "972", "Liechtenstein": "423", "Indonesia": "62"}


def phone(raw: str, country: str, review: list, name: str) -> str:
    p = raw.strip()
    if not p:
        return ""
    first = p
    for sep in (r"/\s+", r"\s+-\s+"):  # "0108341/ 0108353111", "027015081 - 02747601": two numbers
        parts = re.split(sep, first)
        if len(parts) > 1 and all(len(re.sub(r"\D", "", x)) >= 7 for x in parts):
            first = parts[0]
    # "0267479254 0267479241", "0835-259593 331-8055238": second number after a space
    m = re.match(r"^(.*?\d{3,}.*?)\s+(?=\+?\d[\d\-./]{6,}$)", first)
    if m and len(re.sub(r"\D", "", m.group(1))) >= 9:
        first = m.group(1)
    digits = re.sub(r"\D", "", first)
    if first.lstrip().startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif country == "Italy":
        digits = "39" + digits
    else:
        review.append(f"{name}: phone '{raw}' has no country code; left empty")
        return ""
    cc = next((c for c in sorted(DIAL.values(), key=len, reverse=True) if digits.startswith(c)), "")
    nsn = digits[len(cc):]
    if not cc or not 6 <= len(nsn) <= 11:
        review.append(f"{name}: phone '{raw}' invalid; left empty")
        return ""
    if cc == "39":
        if not nsn.startswith(("0", "3", "8")):
            review.append(f"{name}: phone '{raw}' is not a valid Italian number; left empty")
            return ""
        return f"+39 {nsn}"  # Italian numbers keep their leading 0
    return f"+{cc} {nsn.lstrip('0')}"


def load_existing(data_root: Path, out: Path) -> dict:
    ex: dict = {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent.resolve() == out.resolve():
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                ex.setdefault((key(r["name"]), r["country"]), []).append((f.parent.name, r))
    return ex


def sectors(std: str, flag: str, codes: str, review: list, name: str) -> tuple[set[int], str]:
    items = [c.strip() for c in codes.split(",") if c.strip()]
    if not items:
        return ALL, ALL_NOTE
    if flag == "I":
        ea: set[int] = set()
        for c in items:  # "01-04", "01-07b", "17b"
            m = re.fullmatch(r"(\d+)[a-z]?(?:-(\d+)[a-z]?)?\*?", c)  # "*" = sector accredited with a restriction
            if not m:
                review.append(f"{name} {std}: IAF code '{c}' not understood; ignored")
                continue
            ea.update(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
        return ea & ALL, "IAF codes from the ACCREDIA register"
    if flag == "C" and std in ("ISO 22000", "FSSC 22000"):
        cats = sorted(set(items))
        return (set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)),
                f"ISO 22003-1 categories {', '.join(cats)} classified to EA")
    if flag == "T" and std == "ISO 50001":
        areas = sorted({ENERGY_NUM[c] for c in items if c in ENERGY_NUM})
        if len(areas) == len(set(items)):
            return (set().union(*(expand(ENERGY[a]) for a in areas)),
                    f"ISO 50003 technical areas {', '.join(items)} classified to EA")
    if flag == "T" and std == "ISO 13485":
        tabs = sorted({".".join(c.split(".")[:2]) for c in items})
        if all(t in MD8 for t in tabs):
            return (set().union(*(expand(MD8[t]) for t in tabs)),
                    f"IAF MD 8 technical areas {', '.join(items)} classified to EA")
    review.append(f"{name} {std}: {flag} codes '{codes[:60]}' not classified to EA; recorded for all EA sectors")
    return ALL, ALL_NOTE + f" (register lists {'NACE codes' if flag == 'N' else 'sectors ' + codes})"


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
    bodies, accs, scopes = {}, {}, {}
    raw = json.loads((args.scrape / "database" / "italy" / "accredia_raw.json").read_text(encoding="utf-8"))
    for rid, name, web, addr, ph, email, certno, issued, expiry, schemes, other in raw:
        name = re.sub(r"\s+", " ", name).strip()
        cert = certno.strip()
        if rid in debug:
            print(rid, name, schemes, other)
        stds: dict[str, tuple[set[int], str]] = {}
        for s in schemes:
            std, flag, codes = (s + ["", ""])[:3]
            ea, note = sectors(std, flag, codes, review, name)
            if std in stds:
                ea = ea | stds[std][0]
            stds[std] = (ea, note)
        for o in filter(None, (x.strip() for x in (other or "").split(";"))):
            o = ALIAS.get(o, o)
            if o in OTHER_OK:
                stds.setdefault(o, (ALL, ALL_NOTE))
            else:
                skipped.setdefault(f"{o} ({OTHER_WHY.get(o, 'not in the standards table')})", []).append(f"{name} ({cert})")
        if not stds:
            review.append(f"{name} ({cert}): no importable scheme; dropped")
            continue
        if not iso(issued):
            review.append(f"{name} ({cert}): register detail has no accreditation date or address (not scraped); "
                          f"dropped ({', '.join(stds)})")
            continue

        address, country = split_country(addr, name)
        match = existing.get((key(name), country))
        if match:
            exact = [m for m in match if m[1]["name"] == name]
            ds, row = (exact or match)[0]
            body = dict(row)
            review.append(f"{name} ({cert}): reuses body row '{row['name']}' from {ds}")
        else:
            w = web.strip()
            body = {"name": name, "country": country, "registration_no": cert,
                    "phone": phone(ph, country, review, name), "email": re.split(r"[;,\s]+", email.strip())[0],
                    "website": ("https://" + w if w and not w.startswith("http") else w), "address": address,
                    "source_url": DETAIL_URL.format(rid), "verified_at": ""}
        if body["name"] in bodies:
            raise SystemExit(f"duplicate body name {body['name']}")
        bodies[body["name"]] = body
        for std, (ea, note) in stds.items():
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            c = f"{cert} ({suffix})" if suffix else cert
            accs.setdefault(c, {"ab_code": AB_CODE, "certificate_number": c, "body_name": body["name"],
                                "accreditation_standard": acc_std, "status": "ACTIVE", "issue_date": iso(issued),
                                "expiry_date": iso(expiry), "proof_url": DETAIL_URL.format(rid)})
            scopes[(c, std)] = {"certificate_number": c, "certification_standard": std, "ea_codes": ea_spec(ea),
                                "status": "ACTIVE", "scope_note": note}

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs.values(), key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes.values(), key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(bodies), len(accs), len(scopes))

    sys.path.insert(0, str(DB))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "accredia_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# ACCREDIA conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                 f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        fh.writelines(f"- {line}\n" for line in review)
        fh.write("\n## Schemes not imported (scheme: bodies)\n\n")
        for s, ids in sorted(skipped.items()):
            fh.write(f"- {s}: {'; '.join(ids)}\n")
        fh.write("\n## Removed by prune_inactive\n\n")
        fh.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'accredia_review.md'}")


if __name__ == "__main__":
    main()
