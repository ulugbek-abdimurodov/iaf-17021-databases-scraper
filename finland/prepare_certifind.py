#!/usr/bin/env python3
"""Convert the FINAS scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by scrape_fi_finas.py. cases/<ident>.json holds the register record
and the scope PDF's text per page (text_by_page). No FINAS PDF has struck-through text, so the
extracted text is used directly.

Two annex layouts:
- Older "Liite 1 / Appendix 1" annexes: Finnish and English lines interleaved. The scope starts at
  "PÄTEVYYSALUE / SCOPE OF ACCREDITATION" (or the ISO 13485 table header). Each section is a
  heading naming the standard(s), then the sector rows: "17 C 33.1" (IAF code, NACE code), NACE
  rows without an IAF code ("C 33.1"), ISO 22003-1 categories ("C Food manufacturing",
  "C0, CI, CII"), ISO 50003 areas ("Industry heavy") or IAF MD 8 areas ("Non-active ...").
- New "Liite 1, Akkreditoitu pätevyysalue" annexes: one Finnish and one English half. The English
  half is read. A heading is "<category>/<standard>[/IAF NN <sector>]".

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug S001,S002]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "FINAS"
BASE = "ISO/IEC 17021-1"
REGISTER = "https://www.finas.fi/sites/en/operators/Pages/default.aspx"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the FINAS annex; recorded for all EA sectors"

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 27701": ("ISO/IEC 27006", " (27006)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
    "AS 9100": ("AS 9104-1", " (9104)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
ORDER = ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 13485", "EN 15224", "ISO 3834", "ISO 22000",
         "FSSC 22000", "ISO 50001", "ISO/IEC 27001", "ISO/IEC 27701", "ISO/IEC 20000-1", "ISO 22301"]

# Heading patterns -> standard. Checked in order; "suppress" drops 9001 named on the same line
# (ISO 3834 and AQAP 2110 are "in combination with ISO 9001").
STANDARD_RES = [
    (re.compile(r"\bFSSC\b"), "FSSC 22000"),
    (re.compile(r"(?<!FSSC )\b22000\b"), "ISO 22000"),
    (re.compile(r"\b50001\b"), "ISO 50001"),
    (re.compile(r"\b13485\b"), "ISO 13485"),
    (re.compile(r"\b14001\b"), "ISO 14001"),
    (re.compile(r"\b45001\b"), "ISO 45001"),
    (re.compile(r"\b27001\b"), "ISO/IEC 27001"),
    (re.compile(r"\b27701\b"), "ISO/IEC 27701"),
    (re.compile(r"\b20000-1\b|ISO/IEC 20000\b"), "ISO/IEC 20000-1"),
    (re.compile(r"\b22301\b"), "ISO 22301"),
    (re.compile(r"\b3834\b"), "ISO 3834"),
    (re.compile(r"\b15224\b"), "EN 15224"),
    (re.compile(r"\b9001\b"), "ISO 9001"),
]
# Sections that are not imported, with the reason written to the review and SOURCES.md.
SKIPPED_RES = [
    (re.compile(r"PEFC", re.I), "PEFC FI forest certification (Finnish national scheme)"),
    (re.compile(r"AQAP", re.I), "AQAP 2110 (NATO quality scheme, not in CertiFind)"),
    (re.compile(r"Notified Bod|Ilmoitetut laitokset", re.I), "EU directive notified-body module"),
    (re.compile(r"Technical services?/|Tutkimuslaitokset", re.I),
     "Vehicle type-approval technical service, category C (EU regulations, not a management-system standard)"),
]
COMBINED_9001 = re.compile(r"(combination with|yhdistettynä)\s+(SFS-EN\s+)?ISO\s+9001|9001\s+laatujärjestelmään", re.I)
EN15593 = re.compile(r"\b15593\b")

IAF_ROW = re.compile(r"^\s*(\d{1,2})\s+[A-U](?:\s|$)")
IAF_TAG = re.compile(r"\bIAF\s+(\d{1,2})\b")
NACE_ROW = re.compile(r"^\s*([A-U])\s*(\d{2}(?:\.\d{1,2})?)\b")
NACE_LIST = re.compile(r"\b[A-U]\s?(\d{2}(?:\.\d{1,2})?)")
FOOD_ROW = re.compile(r"^\s*([A-K])(?:0|I{1,3}|IV|V)?(?:\s*,\s*[A-K](?:0|I{1,3}|IV|V)?)*\s*$"
                      r"|^\s*([A-K])(?:0|I{1,3}|IV|V)?\s+[A-ZÄÖ(]")
SEE_9001 = re.compile(r"see ISO 9001|ks\. ISO 9001", re.I)
NO_CLASS = re.compile(r"Ei erillistä luokitusta|Ei luokitusta|Ei rajoituksia|No (separate )?classification|No restrictions", re.I)
# Old layout: the table header says whether the rows are IAF/EA codes or bare NACE codes.
OLD_HEADER = re.compile(r"^(Sertifiointikohde\s+Toimiala|Certification category\s+Technical area)\s*(.*)")
BARE_CODE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s+[^\d\s]|\s*$)")
OLD_START = re.compile(r"^(PÄTEVYYSALUE|Tekninen pääalue)")
OLD_NOISE = re.compile(r"^(S\d{3}/[AM]\d+/\d{4} Liite|Vaatimus/Requirement|\d{1,2}\.\d{1,2}\.\d{4} Päätöksen|"
                       r"www\.finas\.fi|FINAS |PÄTEVYYSALUE|SCOPE OF ACCREDITATION|Sertifiointikohde|"
                       r"Certification category|Tekninen pääalue|Main Technical area)")
NEW_NOISE = re.compile(r"^(S\d{3}, |Annex 1, |Decision |Accreditation (requirement|area|scope)|\d+/\d+FINAS|"
                       r"Sites\s*$|Technical area \(|Main technical area|Product/product range)", re.I)

# Register address -> cleaned address (the register repeats the company name in some).
ADDRESSES = {
    "S047": "PL 39, 02151 Espoo",
    "S051": "Hansatie 3, 13430 Hämeenlinna",
}


def medical_area(line: str):
    low = line.strip().lower()
    for name, keys, spec in esyd.MEDICAL_AREAS:
        if any(low.startswith(k) for k in keys):
            return name, spec
    return None


def energy_area(line: str):
    low = line.strip().lower().replace("–", "-")
    for letter, names, spec in esyd.ENERGY_AREAS:
        if any(low.startswith(n.replace("–", "-")) for n in names) or (letter in "CD" and low.startswith("buildings")):
            return letter, spec
    return None


def nace_ea(code: str) -> set[int]:
    parts = code.split(".")
    candidates = [code, f"{parts[0]}.{parts[1][:1]}" if len(parts) > 1 else code, parts[0]]
    for table in (esyd.NACE_SPANS, esyd.NACE_TO_EA):
        for c in candidates:
            if c in table:
                v = table[c]
                return expand(v) if isinstance(v, str) else {v}
    return set()


def iso_date(raw: str) -> str:
    d, m, y = re.match(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", raw).groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


def city_case(addr: str) -> str:
    """'Keilaranta 15 B, 02150 ESPOO' -> '... 02150 Espoo'."""
    m = re.match(r"(.*\b\d{5}\s+)(.+)$", addr)
    if not m or not m.group(2).isupper():
        return addr
    return m.group(1) + "-".join(p.capitalize() for p in m.group(2).split("-"))


def scope_lines(case: dict) -> tuple[list[str], str]:
    pages = case["text_by_page"]
    english = [p for p in pages if "Annex 1, Accreditation scope" in p[:300]]
    if english:
        out = []
        for p in english:
            for line in p.split("\n"):
                line = line.strip()
                if line.startswith("Site name Street address"):
                    break  # site table to the end of the page
                if line and not NEW_NOISE.match(line):
                    out.append((line, "iaf"))
        return out, "new"
    out, started, mode = [], False, "iaf"
    for p in pages:
        for line in p.split("\n"):
            line = line.strip()
            h = OLD_HEADER.match(line)
            if h:
                mode = "iaf" if re.search(r"IAF|EA", h.group(2)) else "nace"
            if not started:
                started = bool(OLD_START.match(line))
                continue
            if line and not OLD_NOISE.match(line):
                out.append((line, mode))
    return out, "old"


def is_content(line: str) -> bool:
    return bool(IAF_ROW.match(line) or BARE_CODE.match(line) or IAF_TAG.search(line) or NACE_ROW.match(line) or FOOD_ROW.match(line)
                or SEE_9001.search(line) or NO_CLASS.search(line) or medical_area(line) or energy_area(line))


def blocks(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    content_seen = True
    for line, mode in lines:
        stds, skips = set(), set()
        if not line.startswith("PRP") and not SEE_9001.search(line):
            for rx, reason in SKIPPED_RES:
                if rx.search(line):
                    skips.add(reason)
            for rx, std in STANDARD_RES:
                if rx.search(line):
                    stds.add(std)
            if "FSSC 22000" in stds:
                stds.discard("ISO 22000")
            if COMBINED_9001.search(line) or "ISO 3834" in stds or any("AQAP" in s for s in skips):
                stds.discard("ISO 9001")
        if stds or skips:
            if content_seen or not out:
                out.append({"standards": set(), "skipped": set(), "lines": [], "modes": [], "headings": []})
            out[-1]["standards"] |= stds
            out[-1]["skipped"] |= skips
            out[-1]["headings"].append(line)
            content_seen = False
        if out:
            out[-1]["lines"].append(line)
            out[-1]["modes"].append(mode)
            if EN15593.search(line):
                out[-1]["skipped"].add("EN 15593 food packaging hygiene (not in CertiFind; only in combination with ISO 9001 / ISO 22000)")
        if is_content(line):
            content_seen = True
    return out


def block_codes(std: str, block: dict) -> tuple[set[int] | None, list[str], bool]:
    """(EA codes or None for nothing listed, notes, refers to ISO 9001 sectors)."""
    lines = block["lines"]
    if std == "EN 15224":
        return {38}, ["Health care (EA 38)"], False
    if std in ("ISO 22000", "FSSC 22000"):
        cats = []
        for line in lines:
            m = FOOD_ROW.match(line)
            if m:
                cats.append((m.group(1) or m.group(2)))
        cats = list(dict.fromkeys(cats))
        if not cats:
            return None, [], False
        codes = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
        return codes, [f"ISO 22003-1 categories {', '.join(sorted(cats))} (classified to EA by sector)"], False
    if std == "ISO 50001":
        areas = {}
        for line in lines:
            a = energy_area(line)
            if a:
                areas[a[0]] = a[1]
        if not areas:
            return None, [], False
        codes = set().union(*(expand(s) for s in areas.values()))
        return codes, [f"ISO 50003 technical areas {', '.join(sorted(areas))} (classified to EA by sector)"], False
    if std == "ISO 13485":
        areas = {}
        for line in lines:
            a = medical_area(line)
            if a:
                areas[a[0]] = a[1]
        if not areas:
            return None, [], False
        codes = set().union(*(expand(s) for s in areas.values()))
        return codes, [f"ISO 13485 main technical areas: {'; '.join(sorted(areas))} (classified to EA by sector)"], False
    # Bare codes ("25 Metal products") are IAF codes unless the table is a NACE table: the header
    # says NACE only, or the rows sit under NACE section headings ("C TEOLLISUUS"). A table with
    # "17 C 25" rows gives the IAF codes in its first column.
    has_iaf_rows = any(IAF_ROW.match(line) for line in lines)
    nace_table = not has_iaf_rows and (all(m == "nace" for m in block["modes"]) or any(
        re.match(r"^[A-U](?:\s+[A-U])?\s+[A-ZÄÖ]{3,}(?:\s|,|$)", line) for line in lines))
    modes = ["nace" if nace_table else "iaf"] * len(lines)
    if has_iaf_rows:
        modes = ["rows"] * len(lines)
    iaf = set()
    for line, mode in zip(lines, modes):
        m = IAF_ROW.match(line) or (BARE_CODE.match(line) if mode == "iaf" else None)
        if m and "." not in m.group(1):
            iaf.add(int(m.group(1)))
        iaf |= {int(x) for x in IAF_TAG.findall(line)}
    iaf = {c for c in iaf if 1 <= c <= 39}
    if iaf:
        return iaf, [], False
    refers = any(SEE_9001.search(line) for line in lines)
    if std in IAF_STANDARDS:
        nace, codes = [], set()
        for line, mode in zip(lines, modes):
            m = NACE_ROW.match(line)
            b = BARE_CODE.match(line) if mode == "nace" else None
            found = [m.group(2)] if m else [b.group(1)] if b else (NACE_LIST.findall(line) if re.fullmatch(r"([A-U]\s?\d{2}(\.\d+)?[,\s]*)+", line) else [])
            for n in found:
                nace.append(n)
                codes |= nace_ea(n)
        if codes:
            return codes, [f"Classified to EA from the NACE codes listed (NACE {', '.join(dict.fromkeys(nace))})"], refers
    return None, [], refers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", default="")
    args = ap.parse_args()
    debug = set(filter(None, args.debug.split(",")))

    review: list[str] = []
    skipped_log: dict[str, set[str]] = defaultdict(set)
    bodies, accs, scopes = [], [], []
    names = set()
    for path in sorted((args.scrape / "cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        rid, name = case["ident"], case["company"].strip()
        lines, layout = scope_lines(case)
        found: dict[str, dict] = {}
        for b in blocks(lines):
            for reason in b["skipped"]:
                skipped_log[reason].add(f"{rid} {name}")
            for std in b["standards"]:
                codes, notes, refers = block_codes(std, b)
                entry = found.setdefault(std, {"codes": set(), "notes": [], "all": False, "refers": False})
                if codes is None and refers:
                    entry["refers"] = True
                elif codes is None:
                    entry["all"] = True
                else:
                    entry["codes"] |= codes
                    entry["notes"] += [n for n in notes if n not in entry["notes"]]
            if rid in debug:
                print(f"--- {rid} block {sorted(b['standards'])} skipped={sorted(b['skipped'])}")
                for line in b["lines"][:40]:
                    print("   ", line)
        if "ISO 9001" in found:
            for std, e in found.items():
                if e["refers"]:
                    e["codes"] |= found["ISO 9001"]["codes"]
                    e["all"] = e["all"] or found["ISO 9001"]["all"]
                    e["notes"].append("Sectors as listed for ISO 9001 (\"see ISO 9001 technical sectors\")")
        if not found:
            review.append(f"{rid} {name}: nothing importable (layout {layout}); left out")
            continue
        if name in names:
            review.append(f"{rid} {name}: duplicate name")
        names.add(name)

        address = ADDRESSES.get(rid, city_case(case["address"].strip().replace("‐", "-")))
        website = case.get("website", "").strip()
        if not website:
            m = re.search(r"(?:https?://)?www\.[\w.-]+\.\w+(?:/[\w/.-]*)?", case["text_by_page"][0].replace("www.finas.fi", ""))
            website = m.group(0) if m else ""
        if website and not website.startswith("http"):
            website = "https://" + website
        bodies.append({"name": name, "country": "Finland", "registration_no": rid, "phone": "", "email": "",
                       "website": website, "address": address, "source_url": REGISTER, "verified_at": ""})
        issue = iso_date(case["renewed"]) if case.get("renewed") else ""
        expiry = iso_date(case["expires"]) if case.get("expires") else ""
        rows = {}

        def acc_row(std):
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            cert = rid + suffix
            if cert not in rows:
                rows[cert] = {"ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
                              "accreditation_standard": acc_std, "status": "ACTIVE", "issue_date": issue,
                              "expiry_date": expiry, "proof_url": case["url"].replace(" ", "%20")}
            return cert

        acc_row("ISO 9001")  # base ISO/IEC 17021-1 row, always present
        for std in sorted(found, key=ORDER.index):
            e = found[std]
            if e["all"] or not e["codes"]:
                codes, note = ALL, ALL_NOTE
                if std in IAF_STANDARDS | {"ISO 22000", "FSSC 22000", "ISO 50001", "ISO 13485"}:
                    review.append(f"{rid} {name}: {std} has no sector list in the annex; recorded for all EA sectors")
            else:
                codes, note = e["codes"], "; ".join(e["notes"])
            scopes.append({"certificate_number": acc_row(std), "certification_standard": std,
                           "ea_codes": ea_spec(codes), "status": "ACTIVE", "scope_note": note})
        accs.extend(rows.values())

    args.out.mkdir(parents=True, exist_ok=True)
    for fname, cols, rows in (("bodies", BODY_COLUMNS, bodies), ("accreditations", ACCREDITATION_COLUMNS, accs),
                              ("scopes", SCOPE_COLUMNS, scopes)):
        with open(args.out / f"{fname}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    counts = f"{len(bodies)} bodies, {len(accs)} accreditations, {len(scopes)} scope rows"

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "finas_review.md", "w", encoding="utf-8") as f:
        f.write(f"# FINAS conversion review\n\n{counts} before prune.\n\n## Skipped schemes\n\n")
        for reason, who in sorted(skipped_log.items()):
            f.write(f"- {reason}: {', '.join(sorted(who))}\n")
        f.write("\n## Notes\n\n" + "".join(f"- {r}\n" for r in review))
        f.write("\n## Removed by prune_inactive\n\n" + "".join(f"- {r}\n" for r in removed))
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'finas_review.md'}")


if __name__ == "__main__":
    main()
