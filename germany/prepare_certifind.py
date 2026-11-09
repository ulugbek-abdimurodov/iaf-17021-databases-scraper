#!/usr/bin/env python3
"""Convert the DAkkS scrape (type ZM, "Zertifizierungsstelle für Managementsysteme") into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by dakks_scraper.py (accreditations.csv, documents.csv, pdf/, text/).
DAkkS numbers look like D-ZM-<body>-<certificate>-<annex>: D-ZM-16029-01-00 is an accreditation
certificate (Akkreditierungsurkunde) of body D-ZM-16029, D-ZM-16029-01-01 ... its annexes
(Teil-Akkreditierungen), each with one or more certification programmes. A body with a single
annex has the scope in the -00 document itself ("Anlage zur Akkreditierungsurkunde ...-00").
All ZM accreditations are granted under DIN EN ISO/IEC 17021-1 and have no end date.

One CertiFind accreditation row per certificate (D-ZM-xxxxx-NN-00) and accreditation standard;
schemes with their own accreditation standard (ISO/IEC 27006, ISO 50003, ISO 22003-1, ...) get
a suffixed row, as in the other datasets (`D-ZM-16029-01-00 (27006)`).

Sectors:
  ISO 9001 / 14001 / 45001   IAF code table with ticked boxes. Vector PDFs: ticks are drawn
                             as two diagonal lines (or ☒ / X glyphs) inside the cell; scanned
                             annexes are listed in SCANNED_GRIDS (read from the page images).
  ISO 50001                  ISO 50003 technical areas listed by letter (A ... H)
  ISO 22000 / FSSC 22000     ISO 22003-1 food chain categories listed by letter (A ... K)
  ISO 13485                  IAF MD 8 main technical areas named in the annex
  everything else            no sector list: all EA sectors

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points go to dakks_review.md next to this script; prune_inactive.prune() then drops
everything that is not currently valid.
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

AB_CODE = "DAkkS"
BASE = "ISO/IEC 17021-1"
REGISTER = "https://www.dakks.de/de/akkreditierte-stelle.html?id="
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the annex; recorded for all EA sectors"
ALL = set(range(1, 40))

# Annex text (whitespace collapsed, national prefixes kept) -> CertiFind standard. A pattern
# with standard None is known and deliberately not imported (reason for the review).
STANDARDS = [
    (r"ISO 9001\s*:", "ISO 9001"),
    (r"ISO 14001\s*:", "ISO 14001"),
    (r"ISO 45001\s*:", "ISO 45001"),
    (r"ISO 13485\s*:", "ISO 13485"),
    (r"ISO(?:/IEC)? 50001\s*:", "ISO 50001"),
    (r"FSSC 2200\s?0", "FSSC 22000"),
    (r"ISO 22000\s*:\s*\d{4}\s+(?:Managementsysteme für die Lebensmittelsicherheit|Food safety)",
     "ISO 22000"),
    (r"ISO/IEC 27001\s*:", "ISO/IEC 27001"),
    (r"ISO/IEC 27701\s*:", "ISO/IEC 27701"),
    (r"ISO/IEC 20000-1\s*:", "ISO/IEC 20000-1"),
    (r"ISO/IEC 42001\s*:", "ISO/IEC 42001"),
    (r"ISO 22301\s*:", "ISO 22301"),
    (r"ISO 37001\s*:", "ISO 37001"),
    (r"ISO 37301\s*:", "ISO 37301"),
    (r"ISO 55001\s*:", "ISO 55001"),
    (r"ISO 21001\s*:", "ISO 21001"),
    (r"ISO 15378\s*:", "ISO 15378"),
    (r"ISO 19443\s*:", "ISO 19443"),
    (r"ISO 29001\s*:", "ISO 29001"),
    (r"EN 15224\s*:", "EN 15224"),
    (r"(?<![\d-])9100\s*:", "AS 9100"),
]
YEAR = r"\s*(?::|/?\s*(?:19|20)\d\d\b)"
STANDARD_RES = [(re.compile(p.replace(r"\s*:", YEAR)), std) for p, std in STANDARDS]

# Programmes that are deliberately not imported, for the review (CertiFind users are Italian
# companies, so German national schemes are left out; see memory "no national schemes").
SKIPPED = [
    (r"SCC[- ]?VAZ|SCC-Regelwerk|SCC/SCP", "SCC / SCP (German-Dutch contractor safety scheme)"),
    (r"IT-Sicherheitskatalog", "IT-Sicherheitskatalog § 11 EnWG (German energy-sector law)"),
    (r"BAR-anerkannt|SGB IX|DEGEMED|QMS-?REHA|QM-?FAM", "BAR / rehabilitation QM schemes (German social law)"),
    (r"PEFC", "PEFC national forest management standard (national scheme)"),
    (r"MAAS-BGW|Managementanforderungen der BGW", "MAAS-BGW (German statutory accident insurance scheme)"),
    (r"AZAV|SGB III", "AZAV (German employment-promotion approval)"),
    (r"(?<![\d-])91[12]0\s*(?::|/?\s*20\d\d\b)", "EN 9110 / 9120 (aviation maintenance / distributors; not in CertiFind)"),
    (r"IATF 16949", "IATF 16949 (IATF oversight, not accreditation)"),
    (r"FAMI-QS", "FAMI-QS (feed additives; not in CertiFind)"),
    (r"62443", "IEC 62443 (industrial automation security; not in CertiFind)"),
    (r"21434", "ISO/SAE 21434 (vehicle cybersecurity; not in CertiFind)"),
    (r"2000/14/EG|Richtlinie \d{2,4}/\d+/E[GU]|Verordnung \(EU\) 20\d\d/\d+ .*Modul",
     "EU directive / regulation modules (notified-body activities)"),
    (r"Prototypenschutz", "VDA prototype protection (German automotive industry)"),
    (r"Entsorgungsfachbetrieb|EfbV", "Entsorgungsfachbetrieb (German waste law)"),
]
SKIPPED_RES = [(re.compile(p), why) for p, why in SKIPPED]

# Certification standard -> (accreditation standard, certificate-number suffix).
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
    "AS 9100": ("AS 9104-1", " (9104)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
GRID_NUMBERS = {"9001": "ISO 9001", "14001": "ISO 14001", "45001": "ISO 45001"}

ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
ENERGY_LINE = re.compile(
    r"^\s*([A-H])\s*[).]?\s+(?:Leicht|Schwer|Gebäude|Transport|Bergbau|Land|Energie|Industry|"
    r"Light|Heavy|Building|Mining|Agricultur|Energy)", re.I)
FOOD_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
FOOD_LINE = re.compile(r"^\s*(?:-\s*)?(?:Kategorie\s+|Category\s+)?([A-K])(?:I{1,3}|IV|0)?\s*[,:]?\s+[A-ZÄÖÜ]")
MEDICAL = [  # (German / English heading, IAF MD 8 main technical area)
    (r"Nicht[- ]?aktive Medizinprodukte|Non-active medical devices", "Non-active medical devices"),
    (r"Aktive Medizinprodukte \(nicht implantierbar\)|Active medical devices \(non-implantable\)",
     "Active (non-implantable) medical devices"),
    (r"Aktive implantierbare Medizinprodukte|Active implantable medical devices",
     "Active implantable medical devices"),
    (r"In-Vitro-Diagnostik|In vitro diagnostic", "In vitro diagnostic medical devices"),
    (r"Sterilisationsmethoden|Sterili[sz]ation methods", "Sterilization methods"),
    (r"bestimmte Stoffe ?/ ?Technologien|incorporating/utili[sz]ing specific|specific substances",
     "Devices incorporating specific substances / technologies"),
    (r"Teile oder Dienstleistungen|Parts or services", "Parts or services"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}

# Annexes read from the page images (scanned tables whose ticks the OCR layer lost, a PDF
# without text, tables that list only the accredited codes): annex -> {standard: EA spec}.
MANUAL: dict[str, dict[str, str]] = {
    "D-ZM-21371-01-02": {"ISO 9001": "31;33;35"},
    "D-ZM-11349-01-01": {"ISO 9001": "6-7;14-15;17-19;23-24;28-29;33-35;39",
                         "ISO 14001": "6-7;14-15;17-19;23;28-29;33-35;39",
                         "ISO 45001": "6-7;14-15;17-19;28-29;33-35"},
    "D-ZM-14143-01-01": {"ISO 9001": "1-39", "ISO 14001": "1-39",
                         "ISO 45001": "1-10;12-19;22-39"},
    "D-ZM-15110-02-00": {"ISO 9001": "17-19;29;33-35"},
    "D-ZM-15209-01-00": {"ISO 9001": "12;14"},
    "D-ZM-16028-01-00": {"ISO 9001": "2;14;17-19;28"},
    "D-ZM-16035-01-00": {"ISO 9001": "17-19;29;35;37-39"},
    "D-ZM-16054-01-01": {"ISO 9001": "24;29;31;35;39",
                         "ISO 45001": "2;12;14;16-17;24-27;31;39"},
    "D-ZM-16062-01-01": {"ISO 9001": "24;29;31;35;39", "ISO 14001": "24;31;35;39",
                         "ISO 45001": "31;35;39"},
    "D-ZM-16083-01-01": {"ISO 9001": "17-19;22;28;34-35", "ISO 45001": "17-19;22;28;34-35"},
    "D-ZM-18660-02-00": {"ISO 9001": "17-19;29;35;37-39"},
    "D-ZM-19509-01-02": {"ISO 9001": "4;6;9;12;14-15;17-19;22-24;29;31;35-36;39",
                         "ISO 14001": "3-4;6-9;12-15;17-19;22-24;27-39",
                         "ISO 45001": "3;13-15;17-19;22;29;32-37"},
    "D-ZM-19660-01-01": {"ISO 9001": "14;17-19;29;31-32;35;37-38"},
    "D-ZM-21202-01-00": {"ISO 45001": "17"},
    "D-ZM-22342-01-00": {"ISO 9001": "14;17-19;29;32;34-35", "ISO 14001": "14;17-19;29;35",
                         "ISO 45001": "14;17-19"},
}

# Partially suspended annexes: DAkkS does not say which part is suspended, so their
# programmes are left out until the register shows them as active again.
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
COVER = re.compile(r"bestätigt mit dieser Akkreditierungsurkunde|attests with this Accreditation")
BOILERPLATE = re.compile(r"Prinzipien der DIN EN ISO 9001|principles of DIN EN ISO 9001|"
                         r"gemäß ISO 13485:2016 tätig sind|according to ISO 13485:2016|"
                         r"Anwendung(?:en)? von (?:EN )?ISO 9001:2015|application of ISO 9001:2015|"
                         r"(?:EN )?ISO 9001:2015 für die Gesundheitsversorgung")
# Automotive annexes (EU 2018/858 type approval, IATF / VDA competence): they confirm ISO 9001
# only for IAF 22 and refer to the body's main ISO 9001 annex for everything else.
AUTOMOTIVE = re.compile(r"Supply Chain IATF 16949|IATF 16949 VDA")
NAME_SUFFIX = re.compile(r"\s+(?:Zertifizierungsstelle für (?:Managementsysteme|Systeme und Personal)"
                         r"|Umweltgutachter(?:organisation)?|Systems Certification Department)$")
DISPLAY = {
    "D-ZM-17500": "QUACERT Gesellschaft zur Zertifizierung von Qualitätsmanagement-Systemen mbH",
    "D-ZM-16012": "InterCert GmbH – Group of MTIC",
    "D-ZM-16083": "DVS ZERT GmbH",
    "D-ZM-17670": "GG-CERT e.V.",
    "D-ZM-18926": "Würth IT GmbH ccSec, Certification Center Security",
    "D-ZM-23393": "WSS Würth Shared Services GmbH ccSec, Certification Center Security",
    "D-ZM-15209": "Ghana Standards Authority",
}
COUNTRIES = {"Deutschland": "Germany", "Ghana": "Ghana", "China": "China"}


def iso_date(raw: str) -> str:
    m = DATE.search(raw or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------------------ IAF tables
GRID_HEADER = re.compile(r"^(9001|14001|45001)$")
MARK_CHARS = set("☒✓✔")  # letters X/x appear in table text and give false ticks


def _header_cols(words: list[dict]) -> list[tuple[float, float, str]]:
    """(top, x centre, number) for each standard-number header cell; the centre spans the
    'ISO' prefix so it sits over the tick box."""
    cols = []
    for w in words:
        m = GRID_HEADER.match(w["text"])
        if not m:
            continue
        x0 = w["x0"]
        for p in words:
            if (abs(p["top"] - w["top"]) < 3 and 0 <= w["x0"] - p["x1"] < 8
                    and re.fullmatch(r"ISO|150|IS0|EN|DIN", p["text"])):
                x0 = min(x0, p["x0"])
        cols.append((w["top"], (x0 + w["x1"]) / 2, m.group(1)))
    return cols


def _marks(page) -> list[tuple[float, float]]:
    """Centres of tick marks: short diagonal strokes and tick glyphs."""
    out = []
    for obj in list(page.lines) + list(page.curves):
        wd, ht = obj["x1"] - obj["x0"], obj["bottom"] - obj["top"]
        if 3 < wd < 20 and 3 < ht < 20:
            out.append(((obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2))
    for c in page.chars:
        if c["text"] in MARK_CHARS:
            out.append(((c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2))
    return out


def parse_grid(path: Path, only: str | None = None) -> dict[str, set[int]]:
    """IAF code table of a vector annex: {'9001': {codes}, ...}; empty if there is none.

    Each header line of standard numbers (ISO 9001 | ISO 14001 | ...) starts a table section
    that runs to the next header line; a page without a header continues the columns of the
    page before. `only` names the standard of a single-column table that has no header."""
    result: dict[str, set[int]] = {}
    cols = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not re.search(r"IAF|EA[- ]?Code|Branchen|Scope", text) and cols is None and not only:
                continue
            words = page.extract_words(x_tolerance=1.5)
            heads = sorted(_header_cols(words))
            groups: list[list[tuple]] = []
            for h in heads:
                if groups and h[0] - groups[-1][0][0] < 15:
                    groups[-1].append(h)
                else:
                    groups.append([h])
            sections = []  # (top, bottom, columns)
            first = groups[0][0][0] if groups else page.height
            if cols and first > 60:
                sections.append((-1.0, first, cols))  # continuation from the page before
            for i, g in enumerate(groups):
                cols = sorted({c[2]: c for c in g}.values(), key=lambda c: c[1])
                bottom = groups[i + 1][0][0] if i + 1 < len(groups) else page.height
                sections.append((max(c[0] for c in g), bottom, cols))
            if not sections and only:
                sections.append((-1.0, page.height, None))
            marks = _marks(page)
            for top, bottom, scols in sections:
                limit = scols[0][1] - 60 if scols else page.width / 2
                ints = [w for w in words if re.fullmatch(r"\d{1,2}", w["text"])
                        and 1 <= int(w["text"]) <= 39 and top + 2 < w["top"] < bottom
                        and w["x0"] < limit]
                if not ints:
                    continue
                left = min(w["x0"] for w in ints)
                codes = sorted((w for w in ints if w["x0"] < left + 15), key=lambda w: w["top"])
                for mx, my in marks:
                    if not top + 5 < my < bottom:
                        continue
                    if scols:
                        col = min(scols, key=lambda c: abs(c[1] - mx))
                        if abs(col[1] - mx) > 25:
                            continue
                        key = col[2]
                    else:
                        if mx < left + 150:
                            continue
                        key = only
                    row = None
                    for w in codes:
                        if w["top"] - 6 <= my:
                            row = w
                    if row is None or my > row["bottom"] + 60:
                        continue
                    result.setdefault(key, set()).add(int(row["text"]))
    return result


# ------------------------------------------------------------------------------ annex text
def standards_in(flat: str) -> list[str]:
    found = []
    for rx, std in STANDARD_RES:
        if rx.search(flat) and std not in found:
            found.append(std)
    return found


def energy_areas(text: str) -> set[str]:
    return {m.group(1) for line in text.splitlines() if (m := ENERGY_LINE.match(line))}


def food_categories(text: str) -> set[str]:
    cats = set()
    for line in text.splitlines():
        if m := FOOD_LINE.match(line):
            cats.add(m.group(1))
    return cats


def medical_areas(flat: str) -> list[str]:
    return [name for rx, name in MEDICAL if re.search(rx, flat, re.I)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--dump", type=Path, help="write a per-annex parse report here")
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    accs = {r["accreditation_id"]: r for r in read(args.scrape / "accreditations.csv")}
    docs: dict[str, dict[str, dict]] = defaultdict(dict)
    for d in read(args.scrape / "documents.csv"):
        docs[d["accreditation_id"]][d["language"]] = d

    review: list[str] = []
    dump: list[str] = []
    # certificate (D-ZM-xxxxx-NN-00) -> standard -> {"codes", "notes", "url"}
    found: dict[str, dict[str, dict]] = defaultdict(dict)
    cert_date: dict[str, str] = {}
    cert_expiry: dict[str, str] = {}  # only the foreign bodies' annexes give an end date
    body_of: dict[str, str] = {}

    for aid, a in sorted(accs.items()):
        cert = aid[:-2] + "00"
        body_of[cert] = a["body_id"]
        if aid == cert:
            cert_date[cert] = iso_date(a["status_since"])
        if a["status"] == "Zurückgezogen":
            continue
        doc = docs[aid].get("DE") or docs[aid].get("EN")
        if not doc or not doc["text_path"]:
            review.append(f"{aid}: no document; not imported")
            continue
        text = (args.scrape / doc["text_path"]).read_text(encoding="utf-8")
        flat = BOILERPLATE.sub("", re.sub(r"\s+", " ", text))
        if m := re.search(r"(?:Valid to|Gültig bis):?\s*(\d\d\.\d\d\.\d{4})", flat):
            cert_expiry[cert] = iso_date(m.group(1))
        if COVER.search(flat):
            continue  # cover sheet of the certificate: no scope
        stds = standards_in(flat)
        for std in MANUAL.get(aid, {}):
            if std not in stds:
                stds.append(std)
        automotive = bool(AUTOMOTIVE.search(flat))
        skipped = sorted({why for rx, why in SKIPPED_RES if rx.search(flat)})
        for why in skipped:
            review.append(f"{aid} {a['name']}: {why} not imported")
        if a["status"] != "Aktiv":
            review.append(f"{aid} {a['name']}: status {a['status']} since {a['status_since']}; "
                          f"{', '.join(stds) or 'nothing'} left out")
            continue
        if not stds:
            if aid == cert and re.search(re.escape(cert[:-3].replace("-", "")) + r"0[1-9]",
                                         re.sub(r"[\s-]+", "", text)):
                continue  # certificate page that only lists its annexes
            if not skipped:
                review.append(f"{aid} {a['name']}: no importable programme found — check the annex")
            dump.append(f"{aid}\t-\t{'; '.join(skipped)}")
            continue

        pdf_path = args.scrape / doc["local_path"]
        grid = None
        if any(s in IAF_STANDARDS for s in stds):
            if aid in MANUAL:
                grid = {s: expand(spec) for s, spec in MANUAL[aid].items()}
            elif automotive:
                grid = {"ISO 9001": {22}}
            else:
                iaf = [s for s in stds if s in IAF_STANDARDS]
                only = iaf[0].split()[-1] if len(iaf) == 1 else None
                raw = parse_grid(pdf_path, only)
                grid = {GRID_NUMBERS[k]: v for k, v in raw.items()}
        for std in stds:
            e = found[cert].setdefault(std, {"codes": set(), "notes": [], "url": doc["url"]})
            how = ""
            if std in IAF_STANDARDS:
                codes = (grid or {}).get(std, set())
                if codes:
                    e["codes"] |= codes
                    how = "grid " + ea_spec(codes)
                    if automotive:
                        e["notes"].append("IAF 22 from the automotive annex (EU 2018/858)")
                        how = "automotive IAF 22"
                elif grid:
                    review.append(f"{aid} {a['name']} {std}: IAF table has no tick for it; "
                                  f"recorded for all EA sectors — check the annex")
                    e["codes"] |= ALL
                    e["notes"].append(ALL_NOTE)
                    how = "ALL (table without ticks)"
                else:
                    review.append(f"{aid} {a['name']} {std}: no IAF table; recorded for all EA "
                                  f"sectors — check the annex")
                    e["codes"] |= ALL
                    e["notes"].append(ALL_NOTE)
                    how = "ALL (no table)"
            elif std == "ISO 50001":
                areas = energy_areas(text)
                if areas:
                    e.setdefault("energy", set()).update(areas)
                    how = "areas " + "".join(sorted(areas))
                else:
                    review.append(f"{aid} {a['name']} ISO 50001: no technical area; all EA sectors")
                    e["codes"] |= ALL
                    e["notes"].append(ALL_NOTE)
                    how = "ALL"
            elif std in ("ISO 22000", "FSSC 22000"):
                cats = food_categories(text)
                if cats:
                    e.setdefault("food", set()).update(cats)
                    how = "categories " + "".join(sorted(cats))
                else:
                    review.append(f"{aid} {a['name']} {std}: no food chain category; all EA sectors")
                    e["codes"] |= ALL
                    e["notes"].append(ALL_NOTE)
                    how = "ALL"
            elif std == "ISO 13485":
                areas = medical_areas(flat)
                if areas:
                    e.setdefault("medical", set()).update(areas)
                    how = "areas " + "; ".join(areas)
                else:
                    review.append(f"{aid} {a['name']} ISO 13485: no technical area; all EA sectors")
                    e["codes"] |= ALL
                    e["notes"].append(ALL_NOTE)
                    how = "ALL"
            elif std == "EN 15224":
                e["codes"] |= {38}
                e["notes"].append("Health care sectors (Sektoren des Gesundheitswesens): EA 38")
                how = "EA 38"
            else:
                e["codes"] |= ALL
                if ALL_NOTE not in e["notes"]:
                    e["notes"].append(ALL_NOTE)
                how = "ALL"
            dump.append(f"{aid}\t{std}\t{how}")
        if grid:
            extra = set(grid) - set(stds)
            if extra:
                review.append(f"{aid} {a['name']}: IAF table has columns {sorted(extra)} "
                              f"that the programme list does not name — check")

    # Food / energy / medical areas -> EA codes.
    for cert, stds in found.items():
        for std, e in stds.items():
            if e.get("food"):
                cats = [c for c in FOOD_ORDER if c in e["food"]]
                e["codes"] = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
                e["notes"] = ["ISO 22003-1 food chain categories: " + ", ".join(cats)
                              + " (classified to EA by category)"]
            if e.get("energy"):
                areas = sorted(e["energy"])
                e["codes"] = set().union(*(expand(ENERGY_EA[x]) for x in areas))
                e["notes"] = ["ISO 50003 technical areas: " + "; ".join(ENERGY_NAMES[x] for x in areas)
                              + " (classified to EA by area)"]
            if e.get("medical"):
                areas = [n for _, n in MEDICAL if n in e["medical"]]
                e["codes"] = set().union(*(expand(MEDICAL_EA[n]) for n in areas))
                e["notes"] = ["IAF MD 8 main technical areas: " + "; ".join(areas)
                              + " (classified to EA by area)"]

    # CertiFind allows one accreditation per body, accreditation body and standard, so a body
    # holding several DAkkS certificates (D-ZM-16006-01-00 ... -05-00) is merged into its
    # first certificate: sector sets and notes are joined, the earliest date is kept.
    first_cert: dict[str, str] = {}
    for cert in sorted(found):
        first_cert.setdefault(body_of[cert], cert)
    merged: dict[str, dict[str, dict]] = defaultdict(dict)
    for cert in sorted(found):
        target = first_cert[body_of[cert]]
        if cert != target:
            review.append(f"{cert}: merged into {target} (one accreditation per body and standard)")
            if cert_date.get(cert) and cert_date[cert] < cert_date.get(target, "9999"):
                cert_date[target] = cert_date[cert]
        for std, e in found[cert].items():
            m = merged[target].setdefault(std, {"codes": set(), "notes": [], "url": e["url"]})
            m["codes"] |= e["codes"]
            m["notes"] += [n for n in e["notes"] if n not in m["notes"]]
    found = merged

    # Bodies, accreditation rows, scopes.
    body_rows, accreditations, scope_rows = [], [], []
    bodies_done: set[str] = set()
    for cert in sorted(found):
        body_id = body_of[cert]
        a = accs.get(cert) or next(r for r in accs.values() if r["body_id"] == body_id)
        name = DISPLAY.get(body_id) or NAME_SUFFIX.sub("", a["name"].strip())
        stds = found[cert]
        issue = cert_date.get(cert) or min(iso_date(r["status_since"]) for r in accs.values()
                                            if r["accreditation_id"].startswith(cert[:-2]))
        base_url = (stds.get("ISO 9001") or next(iter(stds.values())))["url"]
        rows_needed = {BASE: (cert, base_url)}
        for std, e in stds.items():
            if std in SCHEME_ROWS:
                acc_std, suffix = SCHEME_ROWS[std]
                rows_needed.setdefault(acc_std, (cert + suffix, e["url"]))
        for acc_std, (number, url) in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": issue, "expiry_date": cert_expiry.get(cert, ""),
                                   "proof_url": url})
        for std, e in stds.items():
            number = cert + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else cert
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(e["codes"]), "status": "ACTIVE",
                               "scope_note": "; ".join(dict.fromkeys(e["notes"]))})
        if not any(std not in SCHEME_ROWS for std in stds):
            review.append(f"{cert} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")
        if body_id not in bodies_done:
            bodies_done.add(body_id)
            country = COUNTRIES.get(a["country"]) or COUNTRIES.get(a["address"].split(",")[-2].strip(), "")
            address = ", ".join(p for p in (a["street"].strip(),
                                            f"{a['postcode']} {a['city']}".strip()) if p)
            body_rows.append({"name": name, "country": country or "Germany", "registration_no": body_id,
                              "phone": "", "email": "", "website": "", "address": address,
                              "source_url": REGISTER + cert, "verified_at": ""})

    names = defaultdict(list)
    for b in body_rows:
        names[b["name"]].append(b["registration_no"])
    for n, ids in names.items():
        if len(ids) > 1:
            review.append(f"duplicate body name {n}: {ids}")

    # Contacts from the bodies' own websites (find_contacts.py); DAkkS publishes none.
    contacts_file = HERE / "contacts.csv"
    if contacts_file.exists():
        found_contacts = {r["registration_no"]: r for r in read(contacts_file)}
        for row in body_rows:
            if c := found_contacts.get(row["registration_no"]):
                for k in ("phone", "email", "website"):
                    row[k] = c[k] or row[k]

    body_rows.sort(key=lambda r: r["name"].casefold())
    write(args.out / "bodies.csv", BODY_COLUMNS, body_rows)
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))
    if args.dump:
        args.dump.write_text("\n".join(dump) + "\n", encoding="utf-8")

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "dakks_review.md", "w", encoding="utf-8") as f:
        f.write("# DAkkS conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; "
          f"review: {HERE / 'dakks_review.md'}")


if __name__ == "__main__":
    main()
