#!/usr/bin/env python3
"""Convert the COFRAC scrape (section Certifications, ISO/IEC 17021-1 management system
certification bodies) into a CertiFind dataset folder (bodies.csv, accreditations.csv,
scopes.csv).

Input: the folder written by cofrac_ms_scraper.py (bodies.csv with one row per accreditation
number "4-xxxx", and documents/<ident>/<ident>.pdf, the accreditation certificate plus its
technical annex).

Annex layouts (all bilingual French / English):
  * old form "CERT CEPE FORM 56": scope starts at "TECHNICAL APPENDIX"; a section starts with a
    line "Système de management de ... /" followed by the French title, the English domain and
    the English title ("ISO 9001", "Certification against ISO 9001", "ISO 19443" ...);
  * new form: scope starts at "Liste des activités accréditées" or after the overview page
    "Annexe technique / Technical annex"; a section starts with one line
    "Système de management de ... / Certification selon la norme ISO 9001".
Section bodies are IAF tables ("17 Métallurgie ..."), ISO 22003-1 categories ("C Food ..."),
ISO 50003 areas ("A : Industrie légère ...") or IAF MD 8 codes ("1.2.A ...").

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug IDs]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
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

AB_CODE = "COFRAC"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the COFRAC annex; recorded for all EA sectors"
ALL = set(range(1, 40))
SOURCE_URL = "https://tools.cofrac.fr/en/easysearch/index.php"

# French schemes (HDS, CACES, NF V 01-005/007 agricultural production, HAS medicine promotion,
# AFAQ ISO 9001-based training referentials, French/German legal metrology and decrees) and
# schemes not in the standards table (AQAP, GMP+, PAFC/PEFC ...). EN 9110/9120 share the
# aerospace section with EN 9100; only EN 9100 (= AS 9100) is imported from it.
NATIONAL = re.compile(r"HDS|Hébergeurs|CACES|production agricole|agricultural production|médicaments|"
                      r"medicinal|se basant sur|Standard based on|métrologie|Arrêté|signalisation|"
                      r"\bAQAP\b|GMP\+|PAFC|PEFC|MASE", re.I)
PFX = r"\b(?:NF\s+)?(?:EN\s+)?(?:ISO|IEC)(?:/IEC)?[ /-]*"
STANDARDS = [
    (r"FSSC\s*22000", "FSSC 22000"),
    (PFX + r"9001\b", "ISO 9001"),
    (PFX + r"14001\b", "ISO 14001"),
    (PFX + r"45001\b", "ISO 45001"),
    (PFX + r"50001\b", "ISO 50001"),
    (PFX + r"27001\b", "ISO/IEC 27001"),
    (PFX + r"27701\b", "ISO/IEC 27701"),
    (PFX + r"20000(?:-1)?\b", "ISO/IEC 20000-1"),
    (PFX + r"42001\b", "ISO/IEC 42001"),
    (PFX + r"22301\b", "ISO 22301"),
    (PFX + r"22000\b", "ISO 22000"),
    (PFX + r"13485\b", "ISO 13485"),
    (PFX + r"19443\b", "ISO 19443"),
    (PFX + r"55001\b", "ISO 55001"),
    (PFX + r"37001\b", "ISO 37001"),
    (PFX + r"37301\b", "ISO 37301"),
    (PFX + r"21001\b", "ISO 21001"),
    (PFX + r"39001\b", "ISO 39001"),
    (PFX + r"28000\b", "ISO 28000"),
    (PFX + r"3834\b", "ISO 3834"),
    (r"\bEN 15224\b", "EN 15224"),
    (r"\b(?:AS|EN)\s?9100\b", "AS 9100"),
]
STANDARD_RES = [(re.compile(p, re.I), s) for p, s in STANDARDS]
# Generic headings whose standard is named only in the section body.
GENERIC = re.compile(r"domaine nucléaire|Dispositifs médicaux|medical devices|aéronautique|aerospace|"
                     r"sécurité des denrées|food safety|anti-corruption|anti-bribery", re.I)

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

SECTION = re.compile(r"^#?\s*Syst[eè]me de management")
HEAD_STOP = re.compile(r"^(?:Programme de|Norme ou document|Code\b|Catégorie|Category|Liste des|"
                       r"Sites intervenant)")
SCOPE_END = re.compile(r"^(?:Sites intervenant|Date de prise d|# Accréditation rendue|"
                       r"Cette annexe technique annule)")
NOISE = re.compile(r"^(?:=====PAGE|Attestation N°|CERT CEPE FORM|Page \d+ (?:sur|/)|Comité Français|"
                   r"Tél\. :|Annexe technique / Technical annex)")
IAF_LINE = re.compile(r"^(?:IAF\s?)?(\d{1,2})(?![\d.,/])\s*(?:[A-Za-zÀ-ÿ(]|$)")
ENERGY_LINE = re.compile(r"(?:^|\s)([A-H])\s?:\s?[A-ZÀ-Ý]")
FOOD_LINE = re.compile(r"^([A-K])(?:I{1,3}|IV|0)?\s+[A-ZÀ-Ý]")
MD_LINE = re.compile(r"(?:^|\s)1\.([1-7])\.[A-Z]?\b")
MD_AREAS = {"1": "Non-active medical devices", "2": "Active (non-implantable) medical devices",
            "3": "Active implantable medical devices", "4": "In vitro diagnostic medical devices",
            "5": "Sterilization methods",
            "6": "Devices incorporating specific substances / technologies", "7": "Parts or services"}
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}

COUNTRY_CODES = {"France": "33", "Morocco": "212", "Italy": "39", "United States": "1"}
# COFRAC name -> the name another dataset already uses for the same company.
ALIASES = {"Schellman Compliance LLC": "Schellman Compliance, LLC"}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def iso_date(raw: str) -> str:
    d, m, y = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw).groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


def annex_text(pdf_path: Path) -> list[str]:
    with pdfplumber.open(pdf_path) as pdf:
        # Some annexes print every character twice (overlaid); dedupe before reading.
        return [line for page in pdf.pages
                for line in (page.dedupe_chars().extract_text() or "").splitlines()]


def dates(lines: list[str]) -> tuple[str, str]:
    text = "\n".join(lines)
    start = re.search(r"(?:granting date|Valid from)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    end = re.search(r"(?:expiry date|Valid until)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    return (iso_date(start.group(1)) if start else "", iso_date(end.group(1)) if end else "")


def sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """[(heading, body lines)] of the technical annex."""
    starts = [i for i, l in enumerate(lines) if re.match(r"^Liste des activités accréditées", l)]
    if not starts:
        starts = [i for i, l in enumerate(lines)
                  if re.match(r"^(?:TECHNICAL APPENDIX|Annexe technique / Technical annex)", l)]
    lines = [l.strip() for l in lines[starts[0]:]] if starts else []
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if SECTION.match(line):
            head = [line]
            i += 1
            # Old form: the French title, English domain and English title follow on own lines.
            # A heading can be split by a page break (footer / page header lines in between).
            while (i < len(lines) and len(head) < 4 and not HEAD_STOP.match(lines[i])
                   and not SECTION.match(lines[i]) and not IAF_LINE.match(lines[i])):
                if not NOISE.match(lines[i]):
                    head.append(lines[i])
                i += 1
            out.append((" ".join(head), []))
            continue
        if SCOPE_END.match(line):
            out.append(("", []))  # end marker: following lines belong to no section
        elif out and out[-1][0] and not NOISE.match(line):
            out[-1][1].append(line)
        i += 1
    return [(h, b) for h, b in out if h]


def classify(heading: str, body: list[str]) -> str | None:
    if NATIONAL.search(heading):
        return None
    title = re.sub(r"^#?\s*Syst[eè]me de management[^/]*/", "", heading)
    std = next((s for rx, s in STANDARD_RES if rx.search(title)), None)
    if std == "ISO 22000" and re.search(r"FSSC", " ".join(body[:6])):
        std = "FSSC 22000"
    if std is None and GENERIC.search(heading):
        text = " ".join(body[:15])
        if NATIONAL.search(text):
            return None
        std = next((s for rx, s in STANDARD_RES if rx.search(text)), None)
    return std


def scope_codes(std: str, body: list[str]) -> tuple[set[int], str]:
    if std in IAF_STANDARDS or std == "EN 15224":
        codes = {int(m.group(1)) for line in body if (m := IAF_LINE.match(line))
                 and 1 <= int(m.group(1)) <= 39}
        if std == "EN 15224" and not codes:
            return {38}, "Health care sectors (EA 38)"
        return codes, ""
    if std == "ISO 50001":
        areas = sorted({m.group(1) for line in body for m in ENERGY_LINE.finditer(line)})
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({m.group(1) for line in body if (m := FOOD_LINE.match(line))})
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [MD_AREAS[k] for k in sorted({m.group(1) for line in body for m in MD_LINE.finditer(line)})]
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    return set(ALL), ALL_NOTE


def phone(rid: str, name: str, country: str, raw: str, review: list[str]) -> str:
    """'05 56 34 75 07' -> '+33 5 56 34 75 07'; '00 212 522 543 540' -> '+212 522 543 540'."""
    raw = raw.strip()
    p = re.sub(r"\(0\)", " ", raw)
    p = re.sub(r"[.\s]+", " ", p).strip()
    cc = COUNTRY_CODES.get(country, "")
    if p.startswith("00"):
        p = "+" + p[2:].lstrip()
    elif re.match(r"^\d", p) and cc and p.replace(" ", "").startswith(cc) and country != "France":
        p = "+" + p
    if p.startswith("+"):
        m = re.fullmatch(r"\+(\d{1,3}) ?(\d[\d ]+)", p)
        if m and m.group(1) == cc and len(re.sub(r"\D", "", m.group(2))) >= 8:
            return f"+{cc} {m.group(2).strip()}"
    elif country == "France":
        digits = re.sub(r"\D", "", p)
        if re.fullmatch(r"0[1-9]\d{8}", digits):
            return "+33 " + digits[1] + " " + " ".join(digits[i:i + 2] for i in range(2, 10, 2))
    if raw:
        review.append(f"{rid} {name}: phone '{raw}' is not a valid number for {country}; left empty")
    return ""


def merge_notes(notes: list[str]) -> list[str]:
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
    ap.add_argument("--debug", nargs="*", default=[], help="print the sections of these registrations")
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    with open(args.scrape / "bodies.csv", encoding="utf-8-sig", newline="") as f:
        bodies = list(csv.DictReader(f))

    review, skipped = [], defaultdict(list)
    body_rows: dict[str, dict] = {}
    merged: dict[str, dict] = {}
    for b in bodies:
        rid, name = b["ident"].strip(), b["company"].strip()
        if b["state"] != "Active":
            review.append(f"{rid} {name}: register status '{b['state']}'; not imported")
            continue
        pdf = args.scrape / "documents" / rid / f"{rid}.pdf"
        if not pdf.exists():
            review.append(f"{rid} {name}: annex PDF not downloaded ({b['url']}); not imported")
            continue
        lines = annex_text(pdf)
        issued, expires = dates(lines)
        found: dict[str, tuple[set[int], list[str]]] = {}
        for heading, body in sections(lines):
            std = classify(heading, body)
            if rid in args.debug:
                print(f"## {rid} [{std}] {heading}\n   " + "\n   ".join(body[:12]))
            if not body:
                continue  # overview page listing the domains
            if std is None:
                title = re.sub(r"^#?\s*Syst[eè]me de management[^/]*/\s*", "", heading)
                skipped[re.sub(r"\s+", " ", title)[:90]].append(rid)
                continue
            codes, note = scope_codes(std, body)
            if not codes:
                review.append(f"{rid} {name}: {std} section found but no sectors read — check the annex")
                continue
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)
        if not found:
            review.append(f"{rid} {name}: no importable standard in the annex (only French / "
                          f"non-CertiFind schemes); not imported")
            continue
        if not (issued and expires):
            review.append(f"{rid} {name}: validity dates not found in the certificate")

        if name in merged:
            # Several COFRAC accreditations of one company (e.g. per site or per scheme family):
            # CertiFind allows one accreditation per body, AB and standard, so merge.
            first = merged[name]
            for std, (codes, notes) in found.items():
                prev = first["found"].setdefault(std, (set(), []))
                prev[0].update(codes)
                prev[1].extend(n for n in notes if n not in prev[1])
            review.append(f"{rid} {name}: second accreditation of {first['rid']} (valid {issued} – "
                          f"{expires}); its schemes are merged into {first['rid']}'s rows and dates")
            continue
        country = b["country"].strip()
        parts = [p.strip() for p in b["address"].split("|") if p.strip()]
        if parts and re.fullmatch(r"FRANCE|MAROC|ITALIE|USA", parts[-1], re.I):
            parts = parts[:-1]
        merged[name] = {"rid": rid, "url": b["url"], "found": found, "issued": issued, "expires": expires}
        body_rows[name] = {"name": name, "country": country, "registration_no": rid,
                           "phone": phone(rid, name, country, b["phone"], review),
                           "email": b["email"].strip(), "website": b["website"].strip(),
                           "address": ", ".join(parts), "source_url": SOURCE_URL, "verified_at": ""}

    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with open(path, encoding="utf-8-sig", newline="") as f:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(f)})
    for name in list(body_rows):
        row = body_rows[name]
        key = (row["country"], ALIASES.get(name, name))
        if key in others:
            other, dataset = others[key]
            del body_rows[name]
            body_rows[key[1]] = {c: other[c] for c in BODY_COLUMNS}
            merged[key[1]] = merged.pop(name)
            review.append(f"{row['registration_no']} {name}: already in {dataset} as '{key[1]}'; "
                          f"that dataset's body row is used")

    accreditations, scope_rows = [], []
    for name, m in merged.items():
        rid, found = m["rid"], m["found"]
        rows_needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": m["issued"], "expiry_date": m["expires"],
                                   "proof_url": m["url"]})
        for std, (codes, notes) in found.items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE",
                               "scope_note": "; ".join(merge_notes(notes))})
        if all(std in SCHEME_ROWS for std in found):
            review.append(f"{rid} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "cofrac_review.md", "w", encoding="utf-8") as f:
        f.write(f"# COFRAC conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Sections not imported (heading: accreditations)\n\n")
        for heading, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {heading}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'cofrac_review.md'}")


if __name__ == "__main__":
    main()
