#!/usr/bin/env python3
"""Convert the INAB scrape (management systems certification bodies, ISO/IEC 17021-1) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by inab_scraper.py (bodies.json and, per body, the "Schedule of
Accreditation" PDF (<no>_scope.pdf) and the certificate of accreditation (<no>_certificate.pdf)).

Schedule layout: page 1 lists the "Scope Classification"s (one per scheme); then, per site,
"Scope of Accreditation" pages where each scheme section starts with a line holding only the
classification name ("ISO 14001", "FSSC", "Notified bodies - Mgt Sys"). IAF codes are lines
"17 Basic metals and ...", ISO 50003 technical areas "01 Industry - Light to Medium", food
categories "Cat C ...". The certificate gives the award / renewal / expiry dates.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]
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
from datetime import date
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

AB_CODE = "INAB"
BASE = "ISO/IEC 17021-1"
COUNTRY = "Ireland"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the schedule; recorded for all EA sectors"
ALL = set(range(1, 40))

# INAB scope classification -> CertiFind standard. Anything else (EU directive notified-body
# modules: "Notified bodies - Mgt Sys") is not imported and listed in the review.
STANDARDS = {
    "ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001": "ISO 45001",
    "ISO 50001": "ISO 50001", "ISO/IEC 27001": "ISO/IEC 27001", "ISO 13485": "ISO 13485",
    "ISO 22000": "ISO 22000", "FSSC": "FSSC 22000", "ISO 19443": "ISO 19443",
}
# Certification standard -> (accreditation standard, certificate-number suffix), as in the
# DAkkS and RvA datasets.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}

# ISO 50003 technical areas; INAB numbers them 01-08 in the order A-H.
ENERGY_LETTERS = dict(zip(range(1, 9), "ABCDEFGH"))
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
FOOD_EA = esyd.FOOD_CATEGORIES
MEDICAL = [  # IAF MD 8 main technical areas
    (r"non[- ]?active medical", "Non-active medical devices"),
    (r"active implantable", "Active implantable medical devices"),
    (r"active \(?non[- ]implantable|active medical devices", "Active (non-implantable) medical devices"),
    (r"in[- ]vitro", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation", "Sterilization methods"),
    (r"incorporating|specific substances|utili[sz]ing specific", "Devices incorporating specific substances / technologies"),
    (r"parts (?:or|and) services", "Parts or services"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}

CODE_LINE = re.compile(r"^(\d{2})\.?\s+\S")
FOOD_LINE = re.compile(r"^(?:Cat\s+([A-K])\b|Catering\b)")
PAGE_FOOTER = re.compile(r"^INAB Registration No\.")


def iso_date(raw: str) -> str:
    d, m, y = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw).groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def struck(w: dict, strokes: list[dict]) -> bool:
    h = w["bottom"] - w["top"]
    return len(w["text"]) > 1 and any(
        r["top"] > w["top"] + 0.3 * h and r["bottom"] < w["bottom"] - 0.15 * h
        and r["x0"] < w["x1"] - 1 and r["x1"] > w["x0"] + 1 for r in strokes)


def pdf_lines(path: Path) -> tuple[list[str], int]:
    """Text lines of every page (struck-through words dropped) and the number of struck words."""
    out, struck_count = [], 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            strokes = [r for r in page.rects + page.lines if abs(r["bottom"] - r["top"]) <= 1.5]
            rows: dict[int, list[dict]] = defaultdict(list)
            for w in page.extract_words(keep_blank_chars=False, use_text_flow=False):
                if struck(w, strokes):
                    struck_count += 1
                    continue
                key = next((k for k in rows if abs(k - w["top"]) <= 2), round(w["top"]))
                rows[key].append(w)
            for top in sorted(rows):
                out.append(" ".join(w["text"] for w in sorted(rows[top], key=lambda w: w["x0"])))
    return out, struck_count


def schedule(path: Path) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """(classifications, {classification: lines}, page-1 contact fields)."""
    lines, _ = pdf_lines(path)
    classes = [m.group(1).strip() for l in lines if (m := re.match(r"^Scope Classification\s+(.+)$", l))]
    contact = {}
    for key in ("Contact Phone No", "Website", "Email"):
        m = next((re.match(re.escape(key) + r"\s+(.+)$", l) for l in lines if l.startswith(key + " ")), None)
        contact[key] = m.group(1).strip() if m else ""
    # A long website wraps onto the next lines (up to "Accreditation Standard").
    if contact["Website"].endswith(("-", "/")):
        i = next(i for i, l in enumerate(lines) if l.startswith("Website "))
        while not lines[i + 1].startswith("Accreditation Standard"):
            i += 1
            contact["Website"] += lines[i].strip()
    sections: dict[str, list[str]] = defaultdict(list)
    current = None
    started = False
    for l in lines:
        if l.startswith("Scope of"):
            started = True
        if not started or PAGE_FOOTER.match(l):
            continue
        if l.strip() in classes:
            current = l.strip()
            continue
        if current:
            sections[current].append(l)
    return classes, sections, contact


def scope_codes(std: str, lines: list[str]) -> tuple[set[int], str]:
    text = "\n".join(lines)
    if std in IAF_STANDARDS:
        return {int(m.group(1)) for l in lines if (m := CODE_LINE.match(l)) and 1 <= int(m.group(1)) <= 39}, ""
    if std == "ISO 50001":
        areas = sorted({ENERGY_LETTERS[int(m.group(1))] for l in lines
                        if (m := CODE_LINE.match(l)) and 1 <= int(m.group(1)) <= 8})
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({(m.group(1) or "E").upper() for l in lines if (m := FOOD_LINE.match(l))})
        if not cats:
            return set(), ""
        return set().union(*(expand(FOOD_EA[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [name for rx, name in MEDICAL if re.search(rx, text, re.I)]
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    return set(ALL), ALL_NOTE


def certificate(path: Path) -> dict[str, str]:
    text = "\n".join(pdf_lines(path)[0])
    out = {}
    for key, label in (("award", "Date of award of accreditation"),
                       ("renewal", "Date of last renewal of accreditation"),
                       ("expiry", "Expiry date of this certificate of accreditation")):
        m = re.search(re.escape(label) + r"\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", text)
        out[key] = iso_date(m.group(1)) if m else ""
    return out


def phone(raw: str) -> str:
    """Irish national numbers to international form: '(051) 445 542' -> '+353 51 445 542'.
    Freephone 1800 numbers have no international form and are left empty."""
    p = re.sub(r"\(\+353\)", "+353", raw.strip())
    p = re.sub(r"\s*\(0\)\s*", " ", p)
    if p.startswith("1800") or not p:
        return ""
    if not p.startswith("+"):
        digits = re.sub(r"\D", "", p)
        if not digits.startswith("0"):
            return ""
        digits = digits[1:]
        # Dublin (1), mobiles (8x) and two-digit area codes.
        if digits.startswith("1"):
            area, rest = "1", digits[1:]
        else:
            area, rest = digits[:2], digits[2:]
        p = f"+353 {area} {rest[:3]} {rest[3:]}".strip()
    return re.sub(r"\s+", " ", p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[], help="print the sections of these registrations")
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    bodies = json.loads((args.scrape / "bodies.json").read_text(encoding="utf-8"))["bodies"]
    review, skipped = [], defaultdict(list)
    body_rows, accreditations, scope_rows = [], [], []
    for b in bodies:
        rid, name = b["accreditation_number"], b["name"].strip()
        docs = {d["document_type"]: d for d in b["documents"]}
        if "scope" not in docs or "certificate" not in docs:
            review.append(f"{rid} {name}: schedule or certificate missing; not imported")
            continue
        sched_path = args.scrape / docs["scope"]["local_path"]
        _, struck_n = pdf_lines(sched_path)
        if struck_n:
            review.append(f"{rid} {name}: {struck_n} struck-through words dropped from the schedule")
        classes, sections, contact = schedule(sched_path)
        found: dict[str, tuple[set[int], str]] = {}
        for cls in classes:
            std = STANDARDS.get(cls)
            lines = sections.get(cls, [])
            if rid in args.debug:
                print(f"## {rid} [{std}] {cls}\n   " + "\n   ".join(lines))
            if std is None:
                skipped[cls].append(rid)
                continue
            codes, note = scope_codes(std, lines)
            if not codes:
                review.append(f"{rid} {name}: {std} section found but no sectors read — check the schedule")
                continue
            found[std] = (codes, note)
        if not found:
            review.append(f"{rid} {name}: only EU-directive notified-body activities "
                          f"({', '.join(classes)}); not imported")
            continue

        cert = certificate(args.scrape / docs["certificate"]["local_path"])
        issue = cert["renewal"] or cert["award"]
        if not issue or not cert["expiry"]:
            review.append(f"{rid} {name}: dates not read from the certificate ({cert})")

        c = b["contact"]
        address = ", ".join(l.rstrip(" ,") for l in c["address"] if l.rstrip(" ,") != name)
        address = re.sub(r"Co\.(?=\S)", "Co. ", address)
        website = c["website"] or contact["Website"]
        if website and not re.match(r"https?://", website, re.I):
            website = "https://" + website
        raw_phone = c["phone"] or contact["Contact Phone No"]
        if raw_phone and not phone(raw_phone):
            review.append(f"{rid} {name}: phone '{raw_phone}' has no international form; left empty")
        body_rows.append({"name": name, "country": COUNTRY, "registration_no": rid,
                          "phone": phone(raw_phone), "email": c["email"] or contact["Email"],
                          "website": website, "address": address,
                          "source_url": b["detail_url"], "verified_at": ""})
        if c["email_link"] and c["email_link"].lower() != c["email"].lower():
            review.append(f"{rid} {name}: directory shows {c['email']} but links to {c['email_link']}; "
                          f"the shown address (also on the schedule) is used")

        rows_needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": issue, "expiry_date": cert["expiry"],
                                   "proof_url": docs["scope"]["url"]})
        for std, (codes, note) in found.items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": note})

    # A company already in another dataset (same country and name) is one body in the database.
    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with open(path, encoding="utf-8-sig", newline="") as f:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(f)})
    for i, row in enumerate(body_rows):
        if (row["country"], row["name"]) in others:
            other, dataset = others[(row["country"], row["name"])]
            body_rows[i] = {k: other[k] for k in BODY_COLUMNS}
            review.append(f"{row['registration_no']} {row['name']}: already in {dataset}; that dataset's body row is used")

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows, key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "inab_review.md", "w", encoding="utf-8") as f:
        f.write(f"# INAB conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Scope classifications not imported (classification: registrations)\n\n")
        for cls, ids in sorted(skipped.items()):
            f.write(f"- {cls}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'inab_review.md'}")


if __name__ == "__main__":
    main()
