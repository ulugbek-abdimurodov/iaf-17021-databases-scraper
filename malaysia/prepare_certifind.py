#!/usr/bin/env python3
"""Convert the JSM (Department of Standards Malaysia) ACB scrape into CertiFind CSVs.

    python prepare_certifind.py <scrape> <dataset> [--today YYYY-MM-DD] [--debug ACB001 ...]

<scrape> is the folder holding register_records.json and pdfs/ (jsm_certifind/data/jsm-malaysia).
The register gives one row per body and programme; each body's schedule PDF gives the sector
codes per programme. Schedules carry a rotated "Scan this QR code..." watermark (dropped by
char rotation) and may strike through withdrawn codes (dropped like the RvA converter does).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)
HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "JSM"
COUNTRY = "Malaysia"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the JSM schedule; recorded for all EA sectors"

# Programme acronym (as in the schedule heading and the register) -> CertiFind standard.
PROGRAMMES = {
    "QMS": "ISO 9001", "EMS": "ISO 14001", "OSH": "ISO 45001", "ISMS": "ISO/IEC 27001",
    "MDQMS": "ISO 13485", "EnMS": "ISO 50001", "FSMS": "ISO 22000", "ABMS": "ISO 37001",
    "BCMS": "ISO 22301", "RTSMS": "ISO 39001",
}
# Programmes deliberately not imported, with the reason logged in the review.
SKIPPED = {
    "MSPO": "national scheme (Malaysian Sustainable Palm Oil)",
    "PC": "product certification (ISO/IEC 17065)",
    "HACCP": "national HACCP scheme (MS 1480), not in the standards table",
    "GMP": "national GMP scheme (MS 1514), not in the standards table",
    "FMC": "national forest management scheme (MC&I / MTCS)",
    "PEFC": "PEFC chain of custody, not a 17021-1 management system in the standards table",
    "ATSMS": "ISO 21101 (adventure tourism) is not in the standards table",
    "FAMI-QS": "FAMI-QS is not in the standards table",
    "PERSONS": "certification of persons (ISO/IEC 17024)",
}
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

ACRONYM = re.compile(r"\((QMS|EMS|OSH|ISMS|MDQMS|EnMS|FSMS|FSSC[^)]*|ABMS|BCMS|RTSMS|ATSMS|HACCP|GMP|"
                     r"MSPO[^)]*|FMC|PC|FAMI-QS|PEFC[^)]*|CoC)\)")
IAF_CODE = re.compile(r"(?:^|\s)([1-9]|[1-3]\d)(?=\s+(?:[A-Z“\"(]|Limited)|\s*$)")
FOOD_ROW = re.compile(r"(?:^|\s)([A-K])\s+(?:(?:0|I{1,3}|IV)\s+)?[A-Z][a-z]")
ENERGY = [("A", r"^Indu\w*[- ]+light"), ("B", r"^Indu\w*[- ]+heavy"), ("D", r"^Bui\w*\s+complex"),
          ("C", r"^Buildings\b"), ("E", r"^Transport\b"), ("F", r"^Mining\b"),
          ("G", r"^Agricultur"), ("H", r"^Energy\s+supply")]
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL = [
    (r"non-?\s?active", "Non-active medical devices"),
    (r"(?<!non-)(?<!non )active implantable", "Active implantable medical devices"),
    (r"(?<!non-)(?<!non )active (?:medical|\(non|non-implantable)", "Active (non-implantable) medical devices"),
    (r"in vitro", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation", "Sterilization methods"),
    (r"incorporating|utili[sz]ing specific", "Devices incorporating specific substances / technologies"),
    (r"parts or services|^components|distribution services|maintenance services", "Parts or services"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
STATES = ("Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang", "Perak", "Perlis",
          "Pulau Pinang", "Sabah", "Sarawak", "Selangor", "Terengganu", "Kuala Lumpur", "Putrajaya",
          "Labuan")
ALIASES = {"SIRIM QAS INTERNATIONAL SDN. BHD.": "SIRIM QAS International Sdn Bhd"}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def struck(c: dict, strokes: list[dict]) -> bool:
    h = c["bottom"] - c["top"]
    return any(r["top"] > c["top"] + 0.3 * h and r["bottom"] < c["bottom"] - 0.15 * h
               and r["x0"] < c["x1"] - 0.5 and r["x1"] > c["x0"] + 0.5 for r in strokes)


def pages(pdf_path: Path) -> list[str]:
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            strokes = [r for r in page.rects + page.lines if r["bottom"] - r["top"] < 1.5
                       and r["x1"] - r["x0"] > 3]
            keep = page.filter(lambda o: o.get("object_type") != "char" or (
                abs(o["matrix"][1]) < 0.01 and not struck(o, strokes)))
            out.append(keep.extract_text() or "")
    return out


def iso_date(raw: str) -> str:
    if not raw:
        return ""
    d, mon, y = raw.split()
    mon = {"DIS": "DEC", "OGO": "AUG", "MEI": "MAY", "OKT": "OCT", "JUN": "JUN"}.get(mon[:3].upper(), mon[:3])
    return datetime.strptime(f"{d} {mon.title()} {y}", "%d %b %Y").date().isoformat()


NAMES = [("QUALITY MANAGEMENT", "QMS"), ("ENVIRONMENTAL MANAGEMENT", "EMS"),
         ("OCCUPATIONAL SAFETY", "OSH"), ("INFORMATION SECURITY", "ISMS"), ("MEDICAL DEVICE", "MDQMS"),
         ("ENERGY MANAGEMENT", "EnMS"), ("FOOD SAFETY SYSTEM CERTIFICATION", "FSSC"),
         ("FOOD SAFETY MANAGEMENT", "FSMS"), ("ANTI-BRIBERY", "ABMS"), ("ANTI BRIBERY", "ABMS"),
         ("BUSINESS CONTINUITY", "BCMS"), ("ROAD TRAFFIC", "RTSMS"), ("ROAD TRANSPORT", "RTSMS"),
         ("ADVENTURE TOURISM", "ATSMS"), ("HACCP", "HACCP"), ("GOOD MANUFACTURING", "GMP"),
         ("PALM OIL", "MSPO"), ("FOREST MANAGEMENT", "FMC"), ("FAMI-QS", "FAMI-QS")]


CRITERIA = [(r"ISO 9001\b", "QMS"), (r"ISO 14001\b", "EMS"), (r"ISO 45001\b", "OSH"),
            (r"27001\b", "ISMS"), (r"13485\b", "MDQMS"), (r"50001\b", "EnMS"), (r"FSSC", "FSSC"),
            (r"ISO 22000\b", "FSMS"), (r"37001\b", "ABMS"), (r"22301\b", "BCMS"), (r"39001\b", "RTSMS")]


def programme_of(text: str) -> str | None:
    """Acronym of the programme a schedule page describes (None for pages without a scope table)."""
    if not (m := re.search(r"SCOPE OF\s+ACCREDITATION|SCOPE NO", text)):
        return None
    head = text[:m.start()]
    if re.search(r"PRODUCT CERTIFICATION|17065", head):
        return "PC"
    if re.search(r"PERSONS|PERSONNEL|17024", head):
        return "PERSONS"
    # The certification criteria decide (one schedule labels its EMS page "(QMS)").
    crit = re.search(r"CERTIFICATION (?:CRITERIA|STANDARD)\S*\s*(.*)", head)
    if crit:
        for rx, acr in CRITERIA:
            if re.search(rx, crit.group(1)):
                return acr
    found = ACRONYM.findall(head)
    if found:
        a = found[-1]
    else:
        flat = re.sub(r"\s+", " ", head).upper()
        a = next((acr for n, acr in NAMES if n in flat), "?")
    for k in ("FSSC", "MSPO", "PEFC"):
        if a.startswith(k):
            return k
    return "PEFC" if a == "CoC" else a


def scope_lines(text: str) -> list[str]:
    m = re.search(r"SCOPE OF\s+ACCREDITATION:?", text)
    body = text[m.end():] if m else ""
    # Codes listed "SUBJECT TO WITNESS" are not yet accredited.
    end = re.search(r"^(?:Note:|LIST OF AUDITORS|The Scheme for the Accreditation)|SUBJECT TO WITNESS", body, re.M)
    return (body[:end.start()] if end else body).splitlines()


def scope_codes(std: str, text: str) -> tuple[set[int], str]:
    lines = scope_lines(text)
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({m.group(1) for l in lines for m in FOOD_ROW.finditer(l)})
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 50001":
        areas = sorted({a for l in lines for a, rx in ENERGY if re.search(rx, l.strip(), re.I)})
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [n for rx, n in MEDICAL if any(re.search(rx, l.strip(), re.I) for l in lines)]
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    codes = {int(m.group(1)) for l in lines if not re.search(r"\d{4}|ISO|IEC|IAF|ID 1", l)
             for m in IAF_CODE.finditer(l)} if any("IAF" in l for l in lines) else set()
    if std in IAF_STANDARDS:
        return codes, ""
    return (codes, "IAF codes listed in the JSM schedule") if codes else (set(ALL), ALL_NOTE)


def phone(rid: str, name: str, raw: str, review: list[str]) -> str:
    """'603-5544 6430', '03-27337700', '019-856 8009' -> '+60 3 5544 6430' etc."""
    d = re.sub(r"\D", "", raw)
    if not d:
        return ""
    d = d[2:] if d.startswith("60") else d[1:] if d.startswith("0") else d
    if d.startswith("1"):
        area, rest = d[:2], d[2:]
    elif d.startswith(("3", "4", "5", "6", "7", "9")):
        area, rest = d[:1], d[1:]
    elif d.startswith("8"):
        area, rest = d[:2], d[2:]
    else:
        area, rest = "", ""
    if not area or not 6 <= len(rest) <= 8:
        review.append(f"{rid} {name}: phone '{raw}' could not be made international; left empty")
        return ""
    groups = [rest[:4], rest[4:]] if len(rest) == 8 else [rest[:3], rest[3:]]
    return f"+60 {area} " + " ".join(groups)


def address(raw: str) -> str:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    last = max((i for i, p in enumerate(parts) if any(s in p for s in STATES)), default=len(parts) - 1)
    return ", ".join(parts[:last + 1])


def website(raw: str) -> str:
    w = raw.strip()
    if not w or w.upper() in ("NA", "NIL", "HTTP://"):
        return ""
    w = re.sub(r"\.com\.m$", ".com.my", w.rstrip("/"))
    return w if re.match(r"https?://", w, re.I) else "http://" + w


def merge_notes(notes: list[str]) -> list[str]:
    """One note per kind when a standard spans several pages."""
    kinds = [("ISO 22003-1 categories ", ", "), ("ISO 50003 technical areas ", ", "),
             ("ISO 13485 main technical areas: ", "; ")]
    tail = " (classified to EA by sector)"
    out = []
    for prefix, sep in kinds:
        items = [i for n in notes if n.startswith(prefix)
                 for i in n[len(prefix):].removesuffix(tail).split(sep)]
        if items:
            out.append(prefix + sep.join(sorted(dict.fromkeys(items))) + tail)
    return out + [n for n in notes if not any(n.startswith(p) for p, _ in kinds)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[])
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    records = json.loads((args.scrape / "register_records.json").read_text(encoding="utf-8"))
    register: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        register[r["registration_no"]].append(r)

    review, skipped = [], defaultdict(set)
    merged: dict[str, dict] = {}
    body_rows: dict[str, dict] = {}
    for rid, rows in sorted(register.items()):
        b, name = rows[0], rows[0]["name"].strip()
        pdf = args.scrape / "pdfs" / f"{rid}.pdf"
        if not pdf.exists():
            review.append(f"{rid} {name}: no schedule PDF; not imported")
            continue
        texts = pages(pdf)
        first = texts[0]
        issue = re.search(r"Issue date:\s*(\d{1,2} \w+ \d{4})", first)
        valid = re.search(r"Valid until:\s*(\d{1,2} \w+ \d{4})", first)
        doc = {"issue": iso_date(issue.group(1)) if issue else "",
               "expiry": iso_date(valid.group(1)) if valid else "", "url": b["proof_url"]}
        found: dict[str, tuple[set[int], list[str]]] = {}
        last = None
        for i, text in enumerate(texts):
            prog = programme_of(text)
            if prog is None:
                continue
            if prog == "?":  # continuation page of the previous programme's table
                prog = last or "?"
            last = prog
            if rid in args.debug:
                print(f"## {rid} p{i + 1} [{prog}]\n   " + "\n   ".join(scope_lines(text)[:14]))
            std = PROGRAMMES.get(prog)
            if prog == "FSSC":
                std = "FSSC 22000"
            if prog == "OSH" and "45001" not in text:
                skipped["OSH page without ISO 45001 (OHSAS 18001)"].add(rid)
                continue
            if std is None:
                skipped[f"{prog}: {SKIPPED.get(prog, 'unrecognised programme heading')}"].add(rid)
                continue
            if False:
                review.append(f"{rid} {name}: {prog} page {i + 1} does not cite ISO/IEC 17021; skipped")
                continue
            codes, note = scope_codes(std, text)
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)
        for std in [s for s, (c, _) in found.items() if not c]:
            review.append(f"{rid} {name}: {std} pages found but no sectors read; not imported — check the PDF")
            del found[std]
        reg_progs = {m.group(1) for r in rows if (m := ACRONYM.search(r["programme"]))}
        for prog, std in PROGRAMMES.items():
            if prog in reg_progs and std not in found:
                review.append(f"{rid} {name}: register lists {prog} but the schedule gave no {std} scope")
        if not found:
            review.append(f"{rid} {name}: no importable management-system programme; not imported")
            continue
        if name in merged:
            first_m = merged[name]
            for std, (codes, notes) in found.items():
                prev = first_m["found"].setdefault(std, (set(), []))
                prev[0].update(codes)
                prev[1].extend(n for n in notes if n not in prev[1])
            review.append(f"{rid} {name}: second registration of {first_m['rid']}; merged into its rows")
            continue
        merged[name] = {"rid": rid, "doc": doc, "found": found}
        body_rows[name] = {"name": name, "country": COUNTRY, "registration_no": rid,
                           "phone": phone(rid, name, b["phone"], review), "email": re.sub(r"\s+", "", b["email"]),
                           "website": website(b["website"]), "address": address(b["address_raw"]),
                           "source_url": b["register_url"], "verified_at": ""}

    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with open(path, encoding="utf-8-sig", newline="") as f:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(f)})
    for name in list(body_rows):
        key = (COUNTRY, ALIASES.get(name, name))
        if key in others:
            other, dataset = others[key]
            body_rows[key[1]] = {c: other[c] for c in BODY_COLUMNS}
            if key[1] != name:
                del body_rows[name]
                merged[key[1]] = merged.pop(name)
            review.append(f"{merged[key[1]]['rid']} {name}: already in {dataset}; that dataset's body row is used")

    accreditations, scope_rows = [], []
    for name, m in merged.items():
        rid, doc, found = m["rid"], m["doc"], m["found"]
        needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": doc["issue"], "expiry_date": doc["expiry"],
                                   "proof_url": doc["url"]})
        for std, (codes, notes) in found.items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": "; ".join(merge_notes(notes))})

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "jsm_review.md", "w", encoding="utf-8") as f:
        f.write(f"# JSM conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Programmes not imported (reason: registrations)\n\n")
        for k, ids in sorted(skipped.items()):
            f.write(f"- {k}: {', '.join(sorted(ids))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'jsm_review.md'}")


if __name__ == "__main__":
    main()
