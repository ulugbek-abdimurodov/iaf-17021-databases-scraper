#!/usr/bin/env python3
"""Convert the IAS (International Accreditation Service, USA) MSCB scrape into a CertiFind dataset (data/ias-usa).

Input: <scrape>/raw/ias_raw.txt written by database/usa/scrape_us_ias.py, one line per certificate:
num|expiry|name|cc|status|pdf|address|website|effective|since|STD~ea~md8tables~foodcats;...
STD: "I9001" = ISO 9001, "I/27001" = ISO/IEC 27001, "FSSC 22000 v. 6.0". ea = IAF/EA ranges (9001/14001/45001),
md8tables = IAF MD 8 table numbers A1.1-A1.7 (13485), foodcats = ISO 22003-1 letters (22000/FSSC).

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug NUMS]
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

AB_CODE = "IAS"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://www.iasonline.org/search-accredited-organizations-2/"
PDF_BASE = "https://www.iasonline.org/wp-content/uploads/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the IAS scope; recorded for all EA sectors"

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
    "ISO 20121": ("ISO/IEC 17021-4", "20121"),
}
STD = {"I9001": "ISO 9001", "I14001": "ISO 14001", "I45001": "ISO 45001", "I13485": "ISO 13485",
       "I22000": "ISO 22000", "I50001": "ISO 50001", "I/27001": "ISO/IEC 27001", "I/27701": "ISO/IEC 27701",
       "SO/IEC 27701": "ISO/IEC 27701", "I/20000-1": "ISO/IEC 20000-1", "I22301": "ISO 22301",
       "I37001": "ISO 37001", "I/42001": "ISO/IEC 42001", "I37301": "ISO 37301", "I39001": "ISO 39001",
       "I41001": "ISO 41001", "I21001": "ISO 21001", "I55001": "ISO 55001", "I20121": "ISO 20121",
       "I29993": "ISO 29993"}
SKIP_WHY = {"I/TS 17021-10": "ISO/IEC TS 17021-10 is a competence requirement, not a certification standard; not in the standards table"}
_MED = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
MD8 = {  # IAF MD 8 tables A1.1-A1.7
    1: _MED["Non-active medical devices"], 2: _MED["Active (non-implantable) medical devices"],
    3: _MED["Active implantable medical devices"], 4: _MED["In vitro diagnostic medical devices"],
    5: _MED["Sterilization methods"], 6: _MED["Devices incorporating specific substances / technologies"],
    7: _MED["Parts or services"],
}
COUNTRIES = {
    "AE": "United Arab Emirates", "AL": "Albania", "AU": "Australia", "BG": "Bulgaria", "BR": "Brazil",
    "CA": "Canada", "CL": "Chile", "CN": "China", "CY": "Cyprus", "GB": "United Kingdom", "GR": "Greece",
    "HK": "Hong Kong", "HR": "Croatia", "IN": "India", "JP": "Japan", "KR": "South Korea", "MN": "Mongolia",
    "MX": "Mexico", "NG": "Nigeria", "OM": "Oman", "QA": "Qatar", "RO": "Romania", "SA": "Saudi Arabia",
    "SG": "Singapore", "SM": "San Marino", "TR": "Turkey", "TW": "Taiwan", "US": "United States",
}
# register country column contradicts the certificate address
COUNTRY_FIX = {"218": "United States", "283": "China"}
UPPER_KEEP = {"USA", "U.S.A.", "UK", "PO", "P.O.", "NW", "NE", "SW", "SE", "R&D", "LLC"}


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
    d = d.replace(" ", "")
    for f in ("%B%d,%Y", "%b%d,%Y"):
        try:
            return datetime.strptime(d, f).date().isoformat()
        except ValueError:
            pass
    return ""


def clean_addr(a: str) -> str:
    a = a.replace("§", "&")
    a = re.sub(r"\s+-\s+", "-", a)
    a = re.sub(r"\s+,", ",", a)
    a = re.sub(r"\s{2,}", " ", a).strip(" ,;")
    a = ", ".join(p.strip(" ,") for p in a.split(";") if p.strip(" ,"))
    if sum(c.isupper() for c in a) > sum(c.islower() for c in a):
        a = " ".join(w if w in UPPER_KEEP or re.search(r"\d", w) else w.title() for w in a.split(" "))
    return a


def clean_web(w: str) -> str:
    w = w.strip().lower().rstrip("/")
    if not w or w == "w.website.com":
        return ""
    w = re.sub(r"^w\.", "www.", w)
    return w if w.startswith("http") else "https://" + w


def ranges(s: str) -> set[int]:
    out: set[int] = set()
    for r in filter(None, s.split(",")):
        a, _, b = r.strip().partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


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
    bodies, accs, scopes = {}, {}, {}
    for line in (args.scrape / "raw" / "ias_raw.txt").read_text(encoding="utf-8").splitlines():
        f = line.split("|")
        if len(f) < 11 or not f[0].isdigit():
            continue
        num, exp, name, cc, status, pdf, addr, web, eff, since, sch = f[:11]
        cert = f"MSCB-{num}"
        name = re.sub(r"\s+", " ", name.replace("§", "&")).strip()
        country = COUNTRY_FIX.get(num, COUNTRIES.get(cc, cc))
        if num in COUNTRY_FIX:
            review.append(f"{name} ({cert}): register country {cc}, address says {country}; used {country}")
        proof = PDF_BASE + (pdf.replace("~", "-Cert.pdf") if pdf.endswith("~") else pdf)
        st = "SUSPENDED" if status.lower().startswith("suspended") else "ACTIVE"
        issue = iso(since) or iso(eff)

        stds: dict[str, tuple[set[int], str]] = {}
        for part in filter(None, sch.split(";")):
            p = (part.split("~") + ["", "", ""])[:4]
            k = p[0].strip()
            std = "FSSC 22000" if k.startswith("FSSC") else STD.get(k)
            if not std:
                skipped.setdefault(SKIP_WHY.get(k, f"{k} (not in the standards table)"), []).append(f"{name} ({cert})")
                continue
            if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
                ea, note = ranges(p[1]) & ALL, "IAF codes from the IAS scope"
            elif std == "ISO 13485":
                tabs = sorted({int(t) for t in p[2].split(",") if t.strip()})
                ea = set().union(*(expand(MD8[t]) for t in tabs)) if tabs else set()
                note = f"IAF MD 8 tables A1.{', A1.'.join(map(str, tabs))} classified to EA"
            elif std in ("ISO 22000", "FSSC 22000"):
                cats = sorted({c.strip() for c in p[3].split(",") if c.strip()})
                ea = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)) if cats else set()
                note = f"ISO 22003-1 categories {', '.join(cats)} classified to EA"
            else:
                ea, note = ALL, ALL_NOTE
            if not ea:
                review.append(f"{name} ({cert}) {std}: no sectors parsed; recorded for all EA sectors")
                ea, note = ALL, ALL_NOTE
            if std in stds:
                stds[std] = (stds[std][0] | ea, stds[std][1])
            else:
                stds[std] = (ea, note)
        if num in debug:
            print(num, name, sch, stds)
        if not stds:
            review.append(f"{name} ({cert}): no importable scheme; dropped")
            continue
        if not issue:
            review.append(f"{name} ({cert}): no accreditation date; dropped")
            continue
        if re.search(r"\b[A-Z] [A-Z]{2,}\b|\b[A-Z]{2,} [A-Z]\b", addr) and not re.search(r"\b(SUITE|ROAD|UNIT)\b [A-Z]\b", addr):
            review.append(f"{name} ({cert}): address has broken words from the PDF text ('{addr[:60]}...'); kept as published")

        match = existing.get((key(name), country))
        if match:
            exact = [m for m in match if m[1]["name"] == name]
            ds, row = (exact or match)[0]
            body = dict(row)
            review.append(f"{name} ({cert}): reuses body row '{row['name']}' from {ds}")
        else:
            body = {"name": name, "country": country, "registration_no": cert, "phone": "", "email": "",
                    "website": clean_web(web), "address": clean_addr(addr), "source_url": SOURCE_URL,
                    "verified_at": ""}
        if body["name"] in bodies:
            review.append(f"{name} ({cert}): body name already used in this dataset; merged into "
                          f"{bodies[body['name']]['_cert']}")
            cert = bodies[body["name"]]["_cert"]
        else:
            bodies[body["name"]] = {**body, "_cert": cert}
        for std, (ea, note) in stds.items():
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            c = f"{cert} ({suffix})" if suffix else cert
            accs.setdefault(c, {"ab_code": AB_CODE, "certificate_number": c, "body_name": body["name"],
                                "accreditation_standard": acc_std, "status": st, "issue_date": issue,
                                "expiry_date": iso(exp), "proof_url": proof})
            s = scopes.setdefault((c, std), {"certificate_number": c, "certification_standard": std,
                                             "ea": set(), "status": st, "scope_note": note})
            s["ea"] |= ea

    body_rows = [{k: v for k, v in b.items() if k != "_cert"} for b in bodies.values()]
    scope_rows = [{**{k: v for k, v in s.items() if k != "ea"}, "ea_codes": ea_spec(s["ea"])} for s in scopes.values()]
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs.values(), key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accs), len(scope_rows))

    sys.path.insert(0, str(DB))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "ias_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# IAS conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                 f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        fh.writelines(f"- {line}\n" for line in review)
        fh.write("\n## Schemes not imported (scheme: bodies)\n\n")
        for s, ids in sorted(skipped.items()):
            fh.write(f"- {s}: {'; '.join(ids)}\n")
        fh.write("\n## Removed by prune_inactive\n\n")
        fh.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'ias_review.md'}")


if __name__ == "__main__":
    main()
