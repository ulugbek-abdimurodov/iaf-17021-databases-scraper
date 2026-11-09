#!/usr/bin/env python3
"""Convert the RvA scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by rva_scraper.py (bodies.json, documents.json and, per body, the
"Annex to declaration of accreditation" PDF in English (-sce.pdf) and/or Dutch (-scn.pdf)).
The English annex is used when published, otherwise the Dutch one.

Annex layout: location pages (which list schemes per site; skipped), then a two-column table
"Standard / Certification scheme" (left, x < 150 pt) | "Normative document" (right, the scope).
A scheme section starts where the left column has text again; its heading decides the
standard. IAF codes are right-column lines "17 basic metals ..." (or a table row
"17 Sectie C 24 ...").

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

AB_CODE = "RvA"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the annex; recorded for all EA sectors"
ALL = set(range(1, 40))
LEFT = 150  # x0 below this is the "Standard / Certification scheme" column

# Section heading (left column, start) -> CertiFind standard. Anything else is not imported
# and listed in the review (national schemes such as VCA, HKZ, NEN 7510, CO2-Prestatieladder,
# PEFC/PCSN; sector schemes not in CertiFind such as AQAP 2110, FAMI-QS, BRCGS; EU directive
# modules).
PFX = r"^(?:NEN-)?(?:EN[- ])?(?:ISO|IEC)(?:/IEC)?[ /-]*"
STANDARDS = [
    # "ISO 22000, ISO 22002-1, Additional FSSC requirements" is FSSC 22000; checked first.
    (r"^(?:FSSC\s*22000|(?:NEN-)?(?:EN[- ])?ISO 22000\b.{0,60}\bFSSC)", "FSSC 22000"),
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
    (PFX + r"3834\b", "ISO 3834"),
    (r"^(?:NEN-)?EN 15224\b", "EN 15224"),
    (r"^(?:AS|EN) ?9100\b", "AS 9100"),
]
STANDARD_RES = [(re.compile(p, re.I), s) for p, s in STANDARDS]
# Dutch schemes whose heading cell also names an ISO standard ("Groenkeur ..., including ISO 9001").
NATIONAL = re.compile(r"Groenkeur|HKZ|NEN ?7510|Deelregeling|SCIOS|CO2", re.I)

# Certification standard -> (accreditation standard, certificate-number suffix), as in the
# DAkkS dataset.
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

# ISO 50003 technical areas; RvA numbers them 1-8 in the order A-H.
ENERGY = [("A", r"light to\s*medium|licht|light"), ("B", r"heavy|zwaar"),
          ("D", r"building\s*complex|gebouwencomplex"), ("C", r"buildings|gebouwen"),
          ("E", r"transport"), ("F", r"mining|mijnbouw"), ("G", r"agricultur|landbouw"),
          ("H", r"energy\s*supply|energievoorziening")]
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
ENERGY_ROW = re.compile(r"^(?:\d\.\s+(?:\D+?\s+)?)?(\d{1,2})\s+\d{2}(?:\.\d+)?(?:,|\s|$)")
FOOD_LINE = re.compile(r"(?:^|\s|-)(?:category|categorie|cat\.)\s+([A-K])(?:I{1,3}|IV|0)?\b", re.I)
MEDICAL = [  # IAF MD 8 main technical areas
    (r"non[- ]?active medical|niet[- ]actieve medische", "Non-active medical devices"),
    (r"active implantable|actieve implanteerbare", "Active implantable medical devices"),
    (r"active \(?non[- ]implantable|actieve \(?niet[- ]implanteerbare|active medical devices \(non",
     "Active (non-implantable) medical devices"),
    (r"in[- ]vitro", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation|sterilisatie", "Sterilization methods"),
    (r"incorporating|specific substances|specifieke stoffen", "Devices incorporating specific substances / technologies"),
    (r"parts or services|onderdelen of diensten", "Parts or services"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}

HEADER_END = re.compile(r"^(?:This annex is valid|Deze bijlage is geldig)")
COLUMN_HEADER = re.compile(r"^(?:R\d\w*)?(?:Standard ?/|Norm ?/|Certification scheme|Certificatieschema|"
                           r"Normative document|Normatief document)")
FOOTER = re.compile(r"^(?:Dutch Accreditation Council|Raad voor Accreditatie)\b|^Voluntary withdrawal|"
                    r"^Vrijwillige intrekking|^Voluntary$|^1 If (?:no date|there is)|"
                    r"^1 (?:Indien|Als) ")
LOCATION_PAGE = re.compile(r"Location\(s\) where|Locatie\(s\) waar|^c?Location\s+(?:Certification|Scheme)|"
                           r"^c?Locatie\s+(?:Certificatie|Schema)|^c?Location\s*$", re.M)
PRODUCT_PAGE = re.compile(r"^Product\s*/", re.M)
CONTINUATION = re.compile(r"^(?:Valid until|Geldig tot|Valid from|Geldig vanaf|\+A\d|:\d{4}|\(?\d{4}\)?$)", re.I)
WRAPPED = re.compile(r"(?:\bmet|\bwith|compatib\w*|\bEN|\bISO|systemen –)\s*$", re.I)
IAF_LINE =re.compile(r"^(\d{1,2})\s+(?:deel\s+|part\s+)?(?:[A-Za-zÀ-ÿ(]|Sectie|Section)")
COUNTRIES = {"Nederland": "Netherlands", "India": "India", "Israël": "Israel", "China": "China",
             "Zuid-Afrika": "South Africa", "Japan": "Japan", "Rwanda": "Rwanda"}


def iso_date(raw: str) -> str:
    d, m, y = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", raw).groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


# RvA name -> the name another dataset already uses for the same company.
ALIASES = {"ISSPL Limited": "ISSPL Limited (formerly IRCLASS Systems and Solutions; Indian Register Quality Systems)"}
SMALL_WORDS ={"en", "aan", "den", "de", "op", "bij", "ido", "zh"}


def city_case(s: str) -> str:
    """'2181 HH HILLEGOM' -> '2181 HH Hillegom'; "'S-HERTOGENBOSCH" -> "'s-Hertogenbosch"."""
    m = re.match(r"(\d{4} ?[A-Z]{2}\s+)(.*)", s)
    head, city = (m.group(1), m.group(2)) if m else ("", s)
    words = []
    for i, w in enumerate(city.split()):
        parts = []
        for j, p in enumerate(w.split("-")):
            low = p.lower()
            if any(c.isdigit() for c in p) or p == "+250":
                parts.append(p)
            elif low in ("'s", "'t"):
                parts.append(low)
            elif low == "zh":
                parts.append("ZH")
            elif (i or j) and low in SMALL_WORDS:
                parts.append(low)
            else:
                parts.append(low.capitalize())
        words.append("-".join(parts))
    return head + " ".join(words)


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


def page_lines(page) -> list[tuple[str, str]]:
    """(left, right) text per printed line of a scope page, page header and footer removed."""
    rows: dict[int, list[dict]] = defaultdict(list)
    strokes = [r for r in page.rects + page.lines if abs(r["bottom"] - r["top"]) <= 1.5]
    for w in page.extract_words(keep_blank_chars=False, use_text_flow=False):
        if struck(w, strokes):  # crossed out = withdrawn activity
            continue
        key = next((k for k in rows if abs(k - w["top"]) <= 2), round(w["top"]))
        rows[key].append(w)
    lines = []
    started = False
    for top in sorted(rows):
        ws = sorted(rows[top], key=lambda w: w["x0"])
        full = " ".join(w["text"] for w in ws)
        if not started:
            if HEADER_END.match(full):
                started = True
            continue
        if COLUMN_HEADER.match(full) or FOOTER.match(full):
            continue
        left = " ".join(w["text"] for w in ws if w["x0"] < LEFT)
        right = " ".join(w["text"] for w in ws if w["x0"] >= LEFT)
        if re.fullmatch(r"\d{1,2}", left):  # an IAF code printed left of the boundary
            left, right = "", (left + " " + right).strip()
        lines.append((left, right))
    return lines


def sections(pdf_path: Path) -> list[tuple[str, list[str]]]:
    """[(heading, right-column lines)] for every scheme section of the annex."""
    out: list[tuple[str, list[str]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            prev_left = ""
            for left, right in page_lines(page):
                if left and not CONTINUATION.match(left):
                    wrapped = out and WRAPPED.search(out[-1][0])
                    starts = not wrapped and (not prev_left or any(rx.search(left) for rx, _ in STANDARD_RES))
                    if starts or not out:
                        out.append((left, []))
                    else:
                        out[-1] = (out[-1][0] + " " + left, out[-1][1])
                if out and right:
                    out[-1][1].append(right)
                prev_left = left
    return out


def classify(heading: str) -> str | None:
    if NATIONAL.search(heading):
        return None
    return next((s for rx, s in STANDARD_RES if rx.search(heading)), None)


def scope_codes(std: str, lines: list[str]) -> tuple[set[int], str]:
    text = "\n".join(lines)
    if std in IAF_STANDARDS or std == "EN 15224":
        codes = {int(m.group(1)) for line in lines if (m := IAF_LINE.match(line))
                 and 1 <= int(m.group(1)) <= 39}
        if std == "EN 15224" and not codes:
            return {38}, "Health care sectors (EA 38)"
        return codes, ""
    if std == "ISO 50001":
        # RvA table rows: [cluster] IAF-code NACE-codes description; a lone number is an IAF
        # code whose NACE cell wrapped.
        codes = {int(m.group(1)) for line in lines
                 if (m := ENERGY_ROW.match(line) or re.fullmatch(r"(\d{1,2})", line.strip()))
                 and 1 <= int(m.group(1)) <= 39}
        if codes:
            return codes, "IAF codes listed in the annex's ISO 50003 technical-area table"
        areas = [l for l, rx in ENERGY if re.search(rx, text, re.I)]
        areas = sorted(set(areas))
        if not areas:
            return set(), ""
        return set().union(*(expand(ENERGY_EA[a]) for a in areas)), \
            "ISO 50003 technical areas " + ", ".join(areas) + " (classified to EA by sector)"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted({m.group(1).upper() for m in FOOD_LINE.finditer(text)})
        if not cats:
            return set(), ""
        return set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats)), \
            "ISO 22003-1 categories " + ", ".join(cats) + " (classified to EA by sector)"
    if std == "ISO 13485":
        areas = [name for rx, name in MEDICAL if re.search(rx, text, re.I)]
        if not areas:
            return set(), ""
        return set().union(*(expand(MEDICAL_EA[a]) for a in areas)), \
            "ISO 13485 main technical areas: " + "; ".join(areas) + " (classified to EA by sector)"
    return set(ALL), ALL_NOTE


def phone(rid: str, name: str, raw: str, review: list[str]) -> str:
    """'+31 (0)10 2018401' -> '+31 10 2018401'. The register cuts Rwanda's +250 to +25."""
    p = re.sub(r"\s*\(0\)\s*", " ", raw.strip())
    p = re.sub(r"^\+25 ", "+250 ", p)
    if p and not re.fullmatch(r"\+\d{1,3}(?: \d+)+", p):
        review.append(f"{rid} {name}: phone '{raw.strip()}' is not an international number; left empty")
        return ""
    return p


def merge_notes(notes: list[str]) -> list[str]:
    """One note per kind when a standard has several sections (e.g. ISO 22000 per cluster)."""
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

    bodies =json.loads((args.scrape / "bodies.json").read_text(encoding="utf-8"))
    docs = json.loads((args.scrape / "documents.json").read_text(encoding="utf-8"))
    by_id: dict[str, dict[str, dict]] = defaultdict(dict)
    for d in docs:
        if d["download_status"] == "downloaded":
            by_id[d["id"]][d["language"]] = d

    review, skipped = [], defaultdict(list)
    body_rows: dict[str, dict] = {}
    merged: dict[str, dict] = {}
    accreditations, scope_rows = [], []
    for b in bodies:
        rid, name = b["id"], b["title"].strip()
        doc = by_id[rid].get("EN") or by_id[rid].get("NL")
        if not doc:
            review.append(f"{rid} {name}: no annex; not imported")
            continue
        found: dict[str, tuple[set[int], list[str]]] = {}
        for heading, lines in sections(args.scrape / doc["file"]):
            std = classify(heading)
            if rid in args.debug:
                print(f"## {rid} [{std}] {heading}\n   " + "\n   ".join(lines[:12]))
            if std is None:
                skipped[re.sub(r"\s+", " ", heading)[:70]].append(rid)
                continue
            codes, note = scope_codes(std, lines)
            if not codes:
                review.append(f"{rid} {name}: {std} section found but no sectors read — check the annex")
                continue
            prev = found.setdefault(std, (set(), []))
            prev[0].update(codes)
            if note and note not in prev[1]:
                prev[1].append(note)
        if not found:
            review.append(f"{rid} {name}: no importable standard in the annex (only national / "
                          f"product schemes); not imported")
            continue

        if name in merged:
            # The same company holds several RvA registrations. CertiFind allows one accreditation
            # per body, accreditation body and standard, so they are merged into the first one.
            first = merged[name]
            for std, (codes, notes) in found.items():
                prev = first["found"].setdefault(std, (set(), []))
                prev[0].update(codes)
                prev[1].extend(n for n in notes if n not in prev[1])
            review.append(f"{rid} {name}: second registration of {first['rid']} (annex valid "
                          f"{doc['valid_from']} – {doc['valid_until']}); its schemes are merged into "
                          f"{first['rid']}'s rows and dates")
            continue
        merged[name] = {"rid": rid, "doc": doc, "found": found}
        street = re.sub(r"\s0(?=\s|$)", "", b["street"]).strip()  # register shows house number 0 when empty
        address = ", ".join(x for x in (street, city_case(b["address"].strip())) if x)
        website = b["website"].strip()
        if website and not re.match(r"https?://", website, re.I):
            website = "http://" + website
        body_rows[name] = {"name": name, "country": COUNTRIES[b["country"]], "registration_no": rid,
                           "phone": phone(rid, name, b["phone"], review), "email": b["email"].strip(),
                           "website": re.sub(r"^HTTP", "http", website), "address": address,
                           "source_url": b["url"], "verified_at": ""}

    # A company already in another dataset (same country and name) is one body in the database:
    # take that dataset's row as it is, so the two imports do not overwrite each other.
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
            body_rows[key[1]] = {c: other[c] for c in BODY_COLUMNS}
            if key[1] != name:
                del body_rows[name]
                merged[key[1]] = merged.pop(name)
            review.append(f"{row['registration_no']} {name}: already in {dataset}; that dataset's body row is used")

    for name, m in merged.items():
        rid, doc, found = m["rid"], m["doc"], m["found"]
        rows_needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": iso_date(doc["valid_from"]),
                                   "expiry_date": iso_date(doc["valid_until"]), "proof_url": doc["url"]})
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
    with open(HERE / "rva_review.md", "w", encoding="utf-8") as f:
        f.write(f"# RvA conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Sections not imported (heading: registrations)\n\n")
        for heading, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {heading}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'rva_review.md'}")


if __name__ == "__main__":
    main()
