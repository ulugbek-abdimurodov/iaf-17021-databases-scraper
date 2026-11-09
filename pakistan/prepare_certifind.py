#!/usr/bin/env python3
"""Turn the PNAC (Pakistan National Accreditation Council) CB scope documents into a CertiFind dataset
(bodies.csv, accreditations.csv, scopes.csv).

The scrape folder holds one text PDF per accredited management system certification body (CB-001.pdf
...). Page 1 names the body, its address, the first-grant date and the expiry ("valid until"); each
further page is one section "A: Quality Management System ISO 9001:2015 ..." with one table:

- ISO 9001 / 14001 / 45001: IAF codes (= EA codes), one per row, after an optional technical cluster.
- ISO 22000 ("Food Safety Management System"): ISO 22003-1 sub-categories (C0, CI, C-II, C-IV ...);
  the category letter is classified to EA with the ESYD table.
- ISO 13485: IAF MD 8/9 main technical areas, classified to EA with the ESYD table.

No PDF has struck-through text (checked with pdfplumber line objects). The documents carry no phone,
e-mail or website.

Run:  python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
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

import pdfplumber

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "PNAC"
SOURCE_URL = "https://www.pnac.gov.pk"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

STANDARD_PATTERNS = [
    ("ISO 9001", r"9001"), ("ISO 14001", r"14001"), ("ISO 45001", r"45001|Occupational Health"),
    ("ISO 22000", r"22000|Food Safety"), ("ISO 13485", r"13485|Medical devices"),
]
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
SCHEMES = {"ISO 22000": ("ISO 22003-1", " (22000)")}
DEFAULT_SCHEME = ("ISO/IEC 17021-1", "")

# Bodies whose first "Awarded to" line is not the plain legal name.
NAMES = {
    "CB 002": "Bureau Veritas Pakistan (Pvt) Limited",
    "CB 005": "Certification Services Pakistan (Pvt) Ltd.",
}
NOISE = re.compile(r"^(F-06/04|ACCREDITATION Issue|Rev\. No|DOCUMENT|CB \d+$|Page \d+ of|Date Director"
                   r"|.*_{3,}|\d{2}-\d{2}-\d{4}\s+s\s?d$)", re.I)
SECTION = re.compile(r"^([A-H])\s?:\s*(.+)")
IAF_CODE = re.compile(r"(?:^|\s)(\d{1,2})(?=\s+[A-Za-z“\"]|\s*$)")
FOOD_SUB = re.compile(r"(?<![A-Za-z])([A-K])-?(0|IV|V|I{1,3})(?![A-Za-z])")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" ,")


def dmy(value: str) -> str:
    d, m, y = value.split("-")
    return f"{y}-{m}-{d}"


def parse(pdf: Path, debug: bool) -> tuple[dict, dict, list[str]]:
    with pdfplumber.open(pdf) as doc:
        pages = [p.extract_text() or "" for p in doc.pages]
    first = pages[0]
    cert = re.search(r"Accreditation No:\s*(CB\s*\d+)", first).group(1)
    awarded = first.split("Awarded to", 1)[1].split("The scope of accreditation", 1)[0]
    lines = [clean(l) for l in awarded.splitlines() if clean(l)]
    name = NAMES.get(cert, lines[0])
    address = ", ".join(l for l in lines[1:] if not (l.startswith("(") or l == "Business Assurance (BA)"))
    address = address.replace("–", "-").replace(",,", ",")
    info = {"cert": cert, "name": name, "address": address,
            "issue": dmy(re.search(r"granted on (\d{2}-\d{2}-\d{4})", first).group(1)),
            "expiry": dmy(re.search(r"valid until (\d{2}-\d{2}-\d{4})", first).group(1))}

    sections: dict[str, dict] = {}
    notes: list[str] = []
    for text in pages[1:]:
        rows = [clean(l) for l in text.splitlines() if clean(l) and not NOISE.match(clean(l))]
        cur = None
        if rows and not any(SECTION.match(r) for r in rows):
            notes.append(f"page without a scheme section skipped (national scheme): {' '.join(rows[:4])[:160]}")
        for i, line in enumerate(rows):
            m = SECTION.match(line)
            if m:
                head = " ".join(rows[i:i + 2])
                std = next((s for s, p in STANDARD_PATTERNS if re.search(p, head, re.I)), None)
                if std is None:
                    notes.append(f"unknown section skipped: {line}")
                    cur = None
                    continue
                cur = sections.setdefault(std, {"ea": set(), "food": set(), "medical": set(), "limits": []})
                continue
            if cur is None or re.search(r"IAF MD|ISO/IEC|ISO 22003|As per the req", line):
                continue
            if std in IAF_STANDARDS:
                for c in IAF_CODE.findall(line):
                    if 1 <= int(c) <= 39:
                        cur["ea"].add(int(c))
                        if "Limited to" in line:
                            cur["limits"].append(f"EA {c}: {line.split(c, 1)[1].strip()}")
                if debug:
                    print(cert, std, "|", line, "->", IAF_CODE.findall(line))
            elif std == "ISO 22000":
                for cat, sub in FOOD_SUB.findall(line):
                    cur["food"].add(f"{cat}{sub}")
            elif std == "ISO 13485":
                low = line.lower()
                if re.search(r"non[- ]active", low):
                    cur["medical"].add(esyd.MEDICAL_AREAS[0][0])
                    low = re.sub(r"non[- ]active", "", low)  # don't also match "active medical"
                for area, prefixes, _ in esyd.MEDICAL_AREAS:
                    if any(p in low for p in prefixes):
                        cur["medical"].add(area)
    return info, sections, notes


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    review: dict[str, list[str]] = defaultdict(list)
    bodies, accreditations, scopes = [], [], []
    pdfs = sorted(args.scrape.glob("CB-*.pdf"))
    for pdf in pdfs:
        info, sections, notes = parse(pdf, debug=pdf.stem in args.debug)
        cert, name = info["cert"], info["name"]
        review["Skipped schemes / parser notes"] += [f"{cert} {name}: {n}" for n in notes]
        rows = []
        for std, sec in sections.items():
            if std in IAF_STANDARDS:
                codes, note = sec["ea"], ""
                if sec["limits"]:
                    note = "Restricted sectors: " + "; ".join(sec["limits"])
                    review["Restricted sectors"].append(f"{cert} {std}: {note}")
            elif std == "ISO 22000":
                codes = set()
                for sub in sec["food"]:
                    codes |= esyd.expand(esyd.FOOD_CATEGORIES[sub[0]])
                note = (f"ISO 22003-1 sub-categories {', '.join(sorted(sec['food']))} "
                        "(classified to EA by sector)")
            else:
                codes = set()
                for area in sec["medical"]:
                    codes |= next(esyd.expand(c) for a, _, c in esyd.MEDICAL_AREAS if a == area)
                note = f"IAF MD 9 main technical areas: {'; '.join(sorted(sec['medical']))} (classified to EA by sector)"
            if not codes:
                review["Sector table not understood (standard left out)"].append(f"{cert} {std}")
                continue
            rows.append((std, esyd.ea_spec(codes), note))
        if not rows:
            review["Nothing importable (body left out)"].append(f"{cert} {name}")
            continue
        review["Parsed"].append(f"{cert} {name}: " + "; ".join(f"{s} [{c}]" for s, c, _ in rows))
        bodies.append({"name": name, "country": "Pakistan", "registration_no": "", "phone": "", "email": "",
                       "website": "", "address": info["address"], "source_url": SOURCE_URL, "verified_at": ""})
        for acc_std, suffix in sorted({SCHEMES.get(s, DEFAULT_SCHEME) for s, _, _ in rows} | {DEFAULT_SCHEME}):
            accreditations.append({"ab_code": AB_CODE, "certificate_number": cert + suffix, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": info["issue"], "expiry_date": info["expiry"],
                                   "proof_url": SOURCE_URL})
        for std, codes, note in rows:
            scopes.append({"certificate_number": cert + SCHEMES.get(std, DEFAULT_SCHEME)[1],
                           "certification_standard": std, "ea_codes": codes, "status": "ACTIVE",
                           "scope_note": note})

    args.dataset.mkdir(parents=True, exist_ok=True)
    write_csv(args.dataset / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda b: b["name"].lower()))
    write_csv(args.dataset / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.dataset / "scopes.csv", SCOPE_COLUMNS, scopes)
    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    review["Removed by prune_inactive"] += prune(args.dataset, date.fromisoformat(args.today))

    out = ["# PNAC dataset review", "",
           f"{len(bodies)} bodies, {len(accreditations)} accreditations, {len(scopes)} scopes "
           f"(of {len(pdfs)} scope documents)", "",
           "No phone/e-mail/website in the PNAC documents; contacts left empty.", ""]
    for section, items in review.items():
        out += [f"## {section} ({len(items)})", "", *[f"- {i}" for i in items], ""]
    args.review.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("scrape", type=Path, nargs="?", default=HERE)
    p.add_argument("dataset", type=Path, nargs="?",
                   default=HERE.parent.parent / "certifind" / "data" / "pnac-pakistan")
    p.add_argument("--today", default=date.today().isoformat())
    p.add_argument("--debug", nargs="*", default=[], help="file stems (CB-001) to print parsed rows for")
    p.add_argument("--review", type=Path, default=HERE / "pnac_review.md")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
