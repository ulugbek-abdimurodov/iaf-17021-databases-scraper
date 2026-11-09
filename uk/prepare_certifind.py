#!/usr/bin/env python3
"""Convert the UKAS scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by ukas_ms_scraper.py (bodies.json and, per body, the "Schedule of
Accreditation" PDF in schedules/<number>_<name>.pdf).

Schedule layout: page 1 = summary + contact block, then a location table, then one scope table
per scheme. Every scope page repeats a header (UKAS address, body, issue no/date, "Accredited to
ISO/IEC 17021-1 ... to provide management systems certification"); a scheme section starts at
"In accordance with ISO/IEC 17021-1 ..." and the next line names the scheme ("ISO 9001: 2015
Certification", "ISO 9001 Sector Scheme Accreditation", ...). A section ends at "END" or at the
next "In accordance with". IAF codes are written "IAF 16 Concrete, ..." (ISO 55001:
"IAF 3, 5, 6, 8").

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug 0001 ...]
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

AB_CODE = "UKAS"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://www.ukas.com/find-an-organisation/browse-by-category/?cat=2567"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the schedule; recorded for all EA sectors"
ALL = set(range(1, 40))

# Scheme line (the line after "In accordance with ...") -> CertiFind standard. Anything else is
# not imported and listed in the review.
PFX = r"^(?:BS )?(?:EN )?(?:ISO|IEC)(?:/IEC)?(?:/TS)?[ /-]*"
STANDARDS = [
    (r"FSSC\W*22000", "FSSC 22000"),
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
    (PFX + r"55001\b", "ISO 55001"),
    (PFX + r"37001\b", "ISO 37001"),
    (PFX + r"37301\b", "ISO 37301"),
    (PFX + r"21001\b", "ISO 21001"),
    (PFX + r"39001\b", "ISO 39001"),
    (PFX + r"28000\b", "ISO 28000"),
    (PFX + r"19443\b", "ISO 19443"),
    (PFX + r"44001\b", "ISO 44001"),
    (PFX + r"18788\b", "ISO 18788"),
    (PFX + r"41001\b", "ISO 41001"),
    (PFX + r"29001\b", "ISO 29001"),
    (PFX + r"15378\b", "ISO 15378"),
    (PFX + r"22716\b", "ISO 22716"),
    (PFX + r"20121\b", "ISO 20121"),
    (PFX + r"30401\b", "ISO 30401"),
    (PFX + r"56001\b", "ISO 56001"),
    (PFX + r"7101\b", "ISO 7101"),
    (PFX + r"3834\b", "ISO 3834"),
    (r"^(?:BS )?EN 15224\b", "EN 15224"),
    (r"^(?:AS|EN) ?9100\b", "AS 9100"),
]
STANDARD_RES = [(re.compile(p, re.I), s) for p, s in STANDARDS]
SECTOR_SCHEME = re.compile(r"Sector Scheme", re.I)

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

# ISO 50003 technical areas, UKAS letters a)-h) = A-H.
ENERGY = [("A", r"light to\s*medium|light"), ("B", r"heavy"), ("D", r"complex"),
          ("C", r"buildings"), ("E", r"transport"), ("F", r"mining"), ("G", r"agricultur"),
          ("H", r"energy\s*supply")]
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
ENERGY_LINE = re.compile(r"^([a-h])\)\s+(.*)")
FOOD_LINE = re.compile(r"(?:^|\s)Category\s+([A-K])\b|^([A-K])(?:0|I{1,3}|IV)?\s*:", re.M)
MEDICAL = [  # IAF MD 8 main technical areas
    (r"non[- ]?active medical", "Non-active medical devices"),
    (r"active implantable", "Active implantable medical devices"),
    (r"active medical devices\s*\(non|active \(?non[- ]implantable", "Active (non-implantable) medical devices"),
    (r"in[- ]vitro", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation", "Sterilization methods"),
    (r"incorporating|specific substances|utili[sz]ing specific", "Devices incorporating specific substances / technologies"),
    (r"parts (?:or|and) services", "Parts or services"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
IAF_LIST = re.compile(r"\b(?:IAF|EA)\s+(\d{1,2}(?:\s*(?:,|and|&)\s*\d{1,2}\b)*)")

PAGE_FOOTER = re.compile(r"^Page \d+ of \d+$")
HEADER_END = re.compile(r"systems certification\s*$", re.I)
SECTION_START = re.compile(r"^In accordance with\b", re.I)


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


def page_lines(page, struck_log: list[str]) -> list[str]:
    rows: dict[int, list[dict]] = defaultdict(list)
    strokes = [r for r in page.rects + page.lines if abs(r["bottom"] - r["top"]) <= 1.5]
    for w in page.extract_words(keep_blank_chars=False, use_text_flow=False):
        if struck(w, strokes):  # crossed out = withdrawn activity
            struck_log.append(w["text"])
            continue
        key = next((k for k in rows if abs(k - w["top"]) <= 2), round(w["top"]))
        rows[key].append(w)
    return [" ".join(w["text"] for w in sorted(rows[t], key=lambda w: w["x0"])) for t in sorted(rows)]


def read_schedule(pdf_path: Path) -> tuple[str, list[tuple[str, list[str]]], list[str]]:
    """(page-1 text, [(scheme line, section lines)], struck words)."""
    sections: list[tuple[str, list[str]]] = []
    struck_log: list[str] = []
    first = ""
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            lines = page_lines(page, struck_log)
            if i == 0:
                first = "\n".join(lines)
            # Drop the repeated page header (ends "... to provide management systems certification").
            end = next((j for j, l in enumerate(lines[:20]) if HEADER_END.search(l)), -1)
            lines = lines[end + 1:]
            current = None
            j = 0
            while j < len(lines):
                line = lines[j]
                if PAGE_FOOTER.match(line):
                    j += 1
                    continue
                if SECTION_START.match(line) and j + 1 < len(lines):
                    current = (lines[j + 1], [])
                    sections.append(current)
                    j += 2
                    continue
                if line.strip() == "END":
                    current = None
                elif current is not None:
                    current[1].append(line)
                j += 1
    return first, sections, struck_log


def classify(scheme: str) -> str | None:
    scheme = scheme.strip()
    found = next((s for rx, s in STANDARD_RES if rx.search(scheme)), None)
    if found is None and (m := re.search(r"\b(?:ISO|IEC)[/IEC ]*\d{4,5}\b.*", scheme)):
        # "BS OHSAS 18001 (OHSAS 18001) Certification and ISO/IEC 45001"
        found = next((s for rx, s in STANDARD_RES if rx.search(m.group(0))), None)
    return found


def sector_schemes(lines: list[str]) -> tuple[list[str], list[str]]:
    """Standards found in a "Sector Scheme(s)" section, and the other lines (not imported)."""
    text = "\n".join(lines)
    found = []
    if re.search(r"\b9100\b", text):
        found.append("AS 9100")
    if re.search(r"27701", text):
        found.append("ISO/IEC 27701")
    if re.search(r"\b(?:ISO|BS EN ISO) 3834\b", text):
        found.append("ISO 3834")
    return found, lines


def iaf_codes(lines: list[str]) -> set[int]:
    codes = set()
    for line in lines:
        for m in IAF_LIST.finditer(line):
            codes.update(int(c) for c in re.findall(r"\d{1,2}", m.group(1)) if 1 <= int(c) <= 39)
    return codes


def scope_codes(std: str, lines: list[str]) -> tuple[set[int], str]:
    text = "\n".join(lines)
    if std == "EN 15224":
        return {38}, "Health care sectors (EA 38)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({m.group(1) or m.group(2) for m in FOOD_LINE.finditer(text)})
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 50001":
        areas = set()
        for line in lines:
            if m := ENERGY_LINE.match(line):
                areas.add(m.group(1).upper())
        if not areas:
            areas = {l for l, rx in ENERGY if re.search(rx, text, re.I)}
        if not areas:
            return set(), ""
        areas = sorted(areas)
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [name for rx, name in MEDICAL if re.search(rx, text, re.I)]
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    codes = iaf_codes(lines)
    if codes:
        return codes, ""
    return set(ALL), ALL_NOTE


CALLING = {"United Kingdom": "44", "China": "86", "United States": "1", "Japan": "81", "Malaysia": "60",
           "Qatar": "974", "Malta": "356", "Taiwan": "886", "Hong Kong": "852", "South Africa": "27"}


def phone(no: str, name: str, raw: str, review: list[str], country: str = "") -> str:
    """'+44 (0)1732 450 000' -> '+44 1732 450 000'; '00 81 3 ...' / '0086 10 ...' -> '+81 3 ...'.
    Only the first of several numbers is kept."""
    p = re.split(r"\s*/\s*|\s+Option\b|\s+ext\b", raw.strip(), flags=re.I)[0]
    p = re.sub(r"\s*\(0\)\s*", " ", p)
    p = re.sub(r"\(\s*\+?(\d{1,3})\s*\)", r"+\1 ", p)  # (+974) / (852)
    p = re.sub(r"[-.–]", " ", p)
    p = re.sub(r"\s+", " ", p).strip()
    p = re.sub(r"^\+\s+", "+", p)
    p = re.sub(r"^\+?00\s?", "+", p)
    code = CALLING.get(country, "")
    if code and not p.startswith("+") and p.startswith(code + " "):
        p = "+" + p  # '86 571 85067941'
    p = re.sub(r"^\++", "+", p)
    if country == "United States" and p.startswith("+") and not p.startswith("+1"):
        p = "+1 " + p[1:]  # '+(248) 358 3388' is a US area code
    if code and re.match(rf"\+{code}\d", p):
        p = f"+{code} " + p[len(code) + 1:]  # '+862150977013' -> '+86 2150977013', '+603 ...' -> '+60 3 ...'
    p = re.sub(r"\s+", " ", p).strip()
    if p and not re.fullmatch(r"\+\d{1,3}(?: \d+)+", p):
        review.append(f"{no} {name}: phone '{raw.strip()}' is not an international number; left empty")
        return ""
    return p


def cf_email(href: str) -> str:
    """Decode a Cloudflare-protected address ('/cdn-cgi/l/email-protection#<hex>')."""
    m = re.search(r"email-protection#([0-9a-f]+)", href or "")
    if not m:
        return ""
    data = bytes.fromhex(m.group(1))
    return bytes(b ^ data[0] for b in data[1:]).decode("utf-8", "replace")


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
    ap.add_argument("--debug", nargs="*", default=[], help="print the sections of these accreditation numbers")
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    bodies = json.loads((args.scrape / "bodies.json").read_text(encoding="utf-8"))
    review, skipped = [], defaultdict(list)
    body_rows: dict[str, dict] = {}
    merged: dict[str, dict] = {}
    for b in bodies:
        no, name = b["accreditation_number"], re.sub(r"\s+", " ", b["name"]).strip()
        pdfs = sorted((args.scrape / "schedules").glob(f"{no}_*.pdf"))
        if not pdfs:
            review.append(f"{no} {name}: no schedule PDF; not imported")
            continue
        first, secs, struck_words = read_schedule(pdfs[0])
        if struck_words:
            review.append(f"{no} {name}: struck-through words dropped: {' '.join(struck_words)[:200]}")
        m = re.search(r"Issue date:?\s*(\d{1,2} \w+ \d{4})", first)
        issue = datetime.strptime(m.group(1), "%d %B %Y").date().isoformat() if m else ""
        if not issue:
            review.append(f"{no} {name}: no issue date on the schedule")

        found: dict[str, tuple[set[int], list[str]]] = {}

        def add(std: str, codes: set[int], note: str) -> None:
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)

        for scheme, lines in secs:
            scheme = re.sub(r"\s+", " ", scheme).strip()
            if no in args.debug:
                print(f"## {no} [{classify(scheme)}] {scheme}\n   " + "\n   ".join(lines[:15]))
            if SECTOR_SCHEME.search(scheme):
                stds, rest = sector_schemes(lines)
                for std in stds:
                    add(std, set(ALL), "No sector list in the schedule (sector scheme); recorded for all EA sectors")
                label = re.sub(r"[: ]*20\d\d\b", "", scheme) + ": " + " | ".join(
                    l for l in lines if not re.search(r"9100|9110|9120|27701", l))[:150]
                skipped[label].append(no)
                continue
            std = classify(scheme)
            if std is None:
                skipped[re.sub(r"[: ]*20\d\d\b", "", scheme)[:80]].append(no)
                continue
            codes, note = scope_codes(std, lines)
            if not codes:
                review.append(f"{no} {name}: {std} section found but no sectors read — check the schedule")
                continue
            add(std, codes, note)
        if not found:
            review.append(f"{no} {name}: no importable standard in the schedule; not imported")
            continue

        if name in merged:
            first_m = merged[name]
            for std, (codes, notes) in found.items():
                prev = first_m["found"].setdefault(std, (set(), []))
                prev[0].update(codes)
                prev[1].extend(n for n in notes if n not in prev[1])
            review.append(f"{no} {name}: second accreditation of {first_m['no']}; merged into its rows")
            continue
        merged[name] = {"no": no, "found": found, "issue": issue, "url": b["schedule_url"]}

        parts = [p.strip() for p in b["address"].split(",")]
        country = parts[-1] if len(parts) > 1 else ""
        if not country:
            review.append(f"{no} {name}: no country in address '{b['address']}'")
        address = ", ".join(parts[:-1])
        wm = re.search(r"Website:\s*(\S+)", first)
        website = wm.group(1).rstrip(".,;") if wm else ""
        if website and not re.match(r"https?://", website, re.I):
            website = "https://" + website
        # The schedule's contact address first; the listing's (Cloudflare-encoded) one is often a
        # UKAS liaison mailbox.
        em = re.search(r"E-?Mail:\s*(\S+@\S+)", first, re.I)
        email = em.group(1).rstrip(".,;") if em else (cf_email(b["website"]) or cf_email(b["email"]))
        body_rows[name] = {"name": name, "country": country, "registration_no": no,
                           "phone": phone(no, name, b["telephone"], review, country), "email": email,
                           "website": website, "address": address,
                           "source_url": SOURCE_URL, "verified_at": ""}

    # A company already in another dataset (same country and name) is one body in the database.
    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with open(path, encoding="utf-8-sig", newline="") as f:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(f)})
    for name in list(body_rows):
        row = body_rows[name]
        key = (row["country"], name)
        if key in others:
            other, dataset = others[key]
            body_rows[name] = {c: other[c] for c in BODY_COLUMNS}
            review.append(f"{row['registration_no']} {name}: already in {dataset}; that dataset's body row is used")

    accreditations, scope_rows = [], []
    for name, m in merged.items():
        no, found = m["no"], m["found"]
        rows_needed = {BASE: no}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], no + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": m["issue"], "expiry_date": "", "proof_url": m["url"]})
        for std, (codes, notes) in found.items():
            number = no + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else no
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE",
                               "scope_note": "; ".join(merge_notes(notes))})
        if all(std in SCHEME_ROWS for std in found):
            review.append(f"{no} {name}: only schemes with their own accreditation standard; "
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
    with open(HERE / "ukas_review.md", "w", encoding="utf-8") as f:
        f.write(f"# UKAS conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Sections not imported (scheme line: accreditation numbers)\n\n")
        for heading, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {heading}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'ukas_review.md'}")


if __name__ == "__main__":
    main()
