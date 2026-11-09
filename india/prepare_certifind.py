#!/usr/bin/env python3
"""Turn the NABCB scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads nabcb_output/all_data.json (written by nabcb_ms_scraper.py): one entry per NABCB
certificate page, with the page's scope table rows.

NABCB gives every scheme of a body its own certificate number (QM002 for QMS, EM002 for EMS,
OH006 for OHSMS, ...), but QMS, ISO 13485 (MDQMS), ISO 21001 and ICMED pages share the QM
number. CertiFind holds one ISO/IEC 17021-1 row per body and accreditation body, so:

- QMS (ISO 9001), EMS (ISO 14001), OHSMS (ISO 45001), MDQMS (ISO 13485), ISO 21001 and
  ISO 15378 certificates are merged into the body's ISO/IEC 17021-1 row. Its certificate
  number is the active QM number (else EM, else OH, else any other merged one); scopes that
  come from another certificate say so in the scope note, with that certificate's validity.
- Other schemes get their own row under their own number, with the accreditation standard
  used by the other datasets: FSMS -> ISO 22003-1, EnMS -> ISO 50003, ISMS -> ISO/IEC 27006,
  ITSMS -> ISO/IEC 20000-6, BCMS -> ISO/IEC 17021-6, ABMS -> ISO/IEC 17021-9,
  AMS -> ISO/IEC 17021-5, AIMS -> ISO/IEC 42006, AQMS -> AS 9104-1.
- A body with no active merged certificate still gets the 17021-1 base row that search
  requires; it borrows the number of its first active scheme certificate, and that scheme
  row gets a suffix as in the BAS dataset (`FS029` + `FS029 (22000)`).

Sector conversion to EA:
- QMS / EMS / OHSMS tables list IAF codes, which are the EA codes; a description that
  narrows the sector ("Limited to ...", "restricted to NACE ...", "except ...") makes a
  limited scope, except where it only restates IAF ID 1 (FULL_SECTOR).
- ISO 22003-1 food chain categories, ISO 50003 technical areas and IAF MD 8 main technical
  areas are classified with the BAS / ESYD tables. FSSC 22000 is recorded for categories the
  page marks as approved for FSSC 22000 (FSSC normative document, "approved category for
  FSSC 22000" or an FSSC section). FAMI-QS feed tables are left out.
- Schemes without a sector list are recorded for all EA sectors.

Run:  python prepare_certifind.py  [--data nabcb_output] [--out ../../certifind/data/nabcb-india]
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


bas = _load("bas_prepare", HERE.parent / "bulgaria" / "prepare_certifind.py")
esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")

AB_CODE = "NABCB"
TODAY = date.today()
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list on the NABCB page; recorded for all EA sectors"
BASE = "ISO/IEC 17021-1"

# NABCB scheme name -> (kind, certification standard). kind "base" = merged into 17021-1.
SCHEMES = {
    "quality management systems": ("base", "ISO 9001"),
    "environmental management systems": ("base", "ISO 14001"),
    "occupational health and safety management system": ("base", "ISO 45001"),
    "medical devices quality management systems": ("base", "ISO 13485"),
    "iso 21001": ("base", "ISO 21001"),
    "iso 15378": ("base", "ISO 15378"),
    "food safety management systems": ("scheme", "ISO 22000"),
    "food safety management system": ("scheme", "ISO 22000"),
    "energy management systems": ("scheme", "ISO 50001"),
    "information security management systems": ("scheme", "ISO/IEC 27001"),
    "information technology service management systems": ("scheme", "ISO/IEC 20000-1"),
    "business continuity management systems": ("scheme", "ISO 22301"),
    "abms": ("scheme", "ISO 37001"),
    "ams": ("scheme", "ISO 55001"),
    "artificial intelligence management systems": ("scheme", "ISO/IEC 42001"),
    "aerospace quality management systems": ("scheme", "AS 9100"),
}
# Left out, with the reason recorded in SOURCES.md.
SKIPPED_SCHEMES = {
    "indian certification of medical devices (icmed)": "ICMED 9000 / ICMED 13485 are Indian national schemes",
    "social management system": "FSSC 24000 (social management) is not in CertiFind's standards",
    "trustworthy digital repositories management systems": "ISO 16363 repository audits are not a management-system standard",
}
# Certification standard -> (accreditation standard, suffix when the row borrows the base number).
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", " (37001)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "AS 9100": ("AS 9104-1", " (9100)"),
}
BASE_PRIORITY = {"QM": 0, "EM": 1, "OH": 2}

# Body name variants that are one organisation but do not normalise to the same key.
ALIASES = {"stqcitcertificationservices": "stqcdirectoratestqccertificationservices"}
# Display names (by key) where NABCB's spelling varies between pages.
DISPLAY = {
    "tuvindia": "TUV India Pvt. Ltd.",
    "isspl": "ISSPL Limited (formerly IRCLASS Systems and Solutions; Indian Register Quality Systems)",
    "galaxycertificationservices": "Galaxy Certification Services Pvt. Ltd.",
    "stqcdirectoratestqccertificationservices": "STQC Directorate (STQC Certification Services)",
    "internationalcertificationservices": "International Certification Services Pvt. Ltd.",
}
COUNTRY = {"testst.petersburgco": "Russia", "intercertifika": "Russia", "dksrus": "Russia",
           "certificationassociationrussianregister": "Russia",
           "nepalbureauofstandardsmetrology": "Nepal", "bhutanstandardsbureau": "Bhutan",
           "mauritiusstandardsbureau": "Mauritius"}
PHONE_OVERRIDE = {"dksrusllc": "+7 4852 66 39 30", "agsicertification": "+91 22 40167901",
                  "certificationassociationrussianregister": "+7 812 670 90 01"}
# Rows of the NABCB withdrawn tables that copy another body's certificate number and dates.
SKIP_BODIES = {"standardsorganisationofnigeria"}

# IAF codes whose description narrows the wording but only restates IAF ID 1.
FULL_SECTOR = {("QM009", 15), ("QM009", 17), ("QM016", 17), ("QM057", 15), ("QM057", 17),
               ("QM057", 34), ("QM071", 17), ("QM071", 19), ("QM082", 17), ("EM023", 17),
               ("EM032", 15), ("EM032", 17)}
LIMIT = re.compile(r"limit|restrict|only|except|exclud", re.I)

MD_AREAS = {1: "Non-active medical devices", 2: "Active (non-implantable) medical devices",
            3: "Active implantable medical devices", 4: "In vitro diagnostic medical devices",
            5: "Sterilization methods", 6: "Devices incorporating specific substances / technologies",
            7: "Parts or services"}
MD_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: (ENERGY_NAMES[letter], spec) for letter, names, spec in esyd.ENERGY_AREAS}
ENERGY_WORDS = [("B", r"heavy"), ("A", r"light"), ("D", r"building complex"), ("C", r"building"),
                ("E", r"transport"), ("F", r"mining"), ("G", r"agricultur"), ("H", r"energy supply")]

review: list[str] = []


# ------------------------------------------------------------------------------ helpers
def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text: str | None) -> date | None:
    """'12 September 2002', 'November 19, 2019', '28Apr 2029', '08 Dec 25', '18th Dec 2014'."""
    tokens = re.findall(r"[A-Za-z]+|\d+", text or "")
    for i, tok in enumerate(tokens):
        month = MONTHS.get(tok[:3].lower()) if len(tok) >= 3 and tok.isalpha() else None
        if not month:
            continue
        nums = [t for t in tokens[i + 1:i + 4] if t.isdigit()]
        before = tokens[i - 1] if i > 0 and tokens[i - 1].isdigit() else None
        if before is None and i > 1 and tokens[i - 1].lower() in ("st", "nd", "rd", "th") and tokens[i - 2].isdigit():
            before = tokens[i - 2]
        if before and int(before) <= 31 and nums:
            day, year = int(before), int(nums[0])
        elif len(nums) >= 2:
            day, year = int(nums[0]), int(nums[1])
        else:
            continue
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def body_key(name: str) -> str:
    k = name.lower().replace("&", " and ")
    k = re.sub(r"\(\s*(accreditation|formerly|operating).*$", "", k)
    k = re.sub(r"\((formerly|operating)[^)]*\)", "", k)
    k = re.sub(r"\b(private|pvt|limited|ltd|llp|and|co\. pvt|india pvt)\b", " ", k)
    k = re.sub(r"certifications", "certification", k)
    k = re.sub(r"[^a-z0-9.]", "", k).strip(".")
    if k.startswith("isspl"):
        k = "isspl"
    if k.startswith("tuvindia"):
        k = "tuvindia"
    return ALIASES.get(k, k)


def display_name(name: str) -> str:
    n = clean(name)
    n = re.sub(r"\s*\(\s*Accreditation.*$", "", n)
    n = re.sub(r"\.\(", ". (", n)
    return n.rstrip(" ,")


def norm_cert(raw: str) -> str:
    m = re.fullmatch(r"([A-Z]{2})0*(\d{1,3})", raw.strip().upper())
    return f"{m[1]}{int(m[2]):03d}" if m else raw.strip().upper()


def phone(raw: str, key: str) -> str:
    if key in PHONE_OVERRIDE:
        return PHONE_OVERRIDE[key]
    text = re.sub(r"(?i)tel\.?:?", " ", raw or "")
    for chunk in re.split(r"[/,;|]|\s(?=\+)|\bext", text):
        chunk = chunk.strip()
        digits = re.sub(r"\D", "", chunk)
        if len(digits) < 7:
            continue
        if chunk.startswith("+") and not re.match(r"\+\s*91", chunk):
            return "+" + clean(re.sub(r"[^\d]+", " ", chunk)).strip()
        if digits.startswith("0091"):
            digits = digits[2:]
        if digits.startswith("1800"):
            continue
        national = digits[2:] if digits.startswith("91") and len(digits) >= 12 else digits
        national = national.lstrip("0")[:10]
        if len(national) == 10:
            return f"+91 {national}"
    return ""


def email(raw: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw or "")
    return m[0].rstrip(".") if m else ""


def website(raw: str) -> str:
    for tok in re.split(r"[\s,;]+", raw or ""):
        tok = tok.strip()
        if "." not in tok or tok.upper().startswith("N.A") or "@" in tok:
            continue
        if not re.match(r"[\w/:.-]+\.[a-z]{2,}", tok, re.I):
            continue
        return tok if tok.startswith("http") else "https://" + tok
    return ""


def country(key: str, address: str) -> str:
    if key in COUNTRY:
        return COUNTRY[key]
    a = address.lower()
    for word, c in (("russia", "Russia"), ("moscow", "Russia"), ("nepal", "Nepal"),
                    ("bhutan", "Bhutan"), ("mauritius", "Mauritius")):
        if word in a:
            return c
    return "India"


def cells(row: dict) -> list[str]:
    return [clean(c) for c in row.get("cells", []) if clean(c)]


# ------------------------------------------------------------------------- scope parsers
class Scope:
    """EA codes of one certification standard from one NABCB certificate page."""

    def __init__(self) -> None:
        self.ea: set[int] = set()
        self.notes: list[str] = []
        self.all = False

    def spec(self) -> str:
        return "ALL" if self.all else bas.ea_spec(self.ea)


def iaf_scope(cert: str, rows: list[dict]) -> Scope:
    s = Scope()
    limited = []
    for r in rows:
        c = cells(r)
        if r["row_type"] != "data" or not c:
            continue
        m = re.fullmatch(r"(\d{1,2}(?:\s+\d{1,2})*)", c[0])
        if not m:
            continue
        codes = [int(x) for x in c[0].split()]
        desc = c[1] if len(c) > 1 else ""
        for code in codes:
            if not 1 <= code <= 39:
                review.append(f"{cert}: IAF code {code} out of range, skipped")
                continue
            s.ea.add(code)
        if len(codes) == 1 and LIMIT.search(desc) and (cert, codes[0]) not in FULL_SECTOR:
            limited.append(f"EA {codes[0]} ({desc.replace('“', '').replace('”', '').replace('‘‘', '').replace('’’', '')})")
        if len(codes) > 1 and LIMIT.search(desc):
            # QM095: one row for six codes; only EA 19 is narrowed ("except NACE 2 Code 26.6").
            limited.append("EA 19 (Electrical and Optical Equipment, except NACE 2 Code 26.6)")
    if limited:
        s.notes.append("Limited scope (part of the sector): " + "; ".join(limited))
    return s


def md_scope(cert: str, rows: list[dict]) -> Scope:
    s = Scope()
    areas: list[int] = []
    limits = []
    for r in rows:
        text = " | ".join(cells(r))
        nums = [int(n) for n in re.findall(r"A\s?1\.\s?(\d)", text)]
        if not nums:
            continue
        for n in nums[:1]:
            if n not in areas:
                areas.append(n)
        lm = re.search(r"\((?:Limited|Restricted|restricted|limited)[^)]*\)", text)
        if lm and lm[0] not in limits:
            limits.append(lm[0])
    for n in areas:
        s.ea |= bas.expand(MD_EA[MD_AREAS[n]])
    if areas:
        s.notes.append("IAF MD 8 main technical areas: " + "; ".join(
            f"A1.{n} {MD_AREAS[n]}" for n in sorted(areas)) + " (classified to EA by sector)")
    if limits:
        s.notes.append("Limited scope: " + "; ".join(l.strip("()") for l in limits))
    if not areas:
        review.append(f"{cert}: ISO 13485 page without main technical areas")
    return s


FOOD_CODE = re.compile(r"^([A-K])(0|IV|I{1,3}|[1-4])?(?=$|\s|[-–.])")
FAMI = re.compile(r"Animal Feed Production|^Distribution$|Products not given directly|When Operators trade", re.I)


def food_scope(cert: str, rows: list[dict]) -> tuple[Scope, Scope | None]:
    """(ISO 22000 scope, FSSC 22000 scope or None)."""
    iso: list[str] = []
    fssc: dict[str, bool] = {}
    not_fsms: set[str] = set()
    limits: list[str] = []
    letter = None
    fssc_section = False
    for r in rows:
        section = clean(r.get("section"))
        c = cells(r)
        text = " | ".join(c)
        if "FAMI" in section.upper():
            continue
        if r["row_type"] == "header":
            continue
        if any(FAMI.search(x) for x in c):
            continue
        if c and c[0].startswith("Cat.") or "Standards / Regulations" in text:
            fssc_section = True          # FS024: second table lists FSSC normative documents
            continue
        if "FSSC" in section:
            fssc_section = True
        candidates = c if r["row_type"] == "data" else [section]
        found = None
        for x in candidates:
            m = FOOD_CODE.match(x)
            if m:
                found = m[1]
                break
        if not found:
            continue
        explicit_letter = any(re.fullmatch(r"[A-K]", x) or re.match(r"^[A-K]\s*[-–]", x) for x in candidates)
        if explicit_letter or found != letter:
            letter = found
        if letter not in iso:
            iso.append(letter)
        if re.search(r"not approved for fsms", text, re.I):
            not_fsms.add(letter)
        if re.search(r"not approved (category )?for fssc", text, re.I):
            fssc[letter] = False
        elif fssc_section or re.search(r"22002|PAS\s*221|approved (category )?for FSSC|FSSC 22000 additional", text, re.I):
            fssc.setdefault(letter, True)
        lm = re.search(r"\(limited to[^)]*\)", text, re.I)
        if lm:
            limits.append(f"{letter}: {lm[0].strip('()')}")
    iso_letters = [l for l in iso if l not in not_fsms]
    s = Scope()
    for l in iso_letters:
        s.ea |= bas.expand(bas.FOOD_CATEGORIES[l])
    s.notes.append(f"ISO 22003-1 categories {', '.join(sorted(iso_letters))} (classified to EA by sector)")
    if limits:
        s.notes.append("Limited scope: " + "; ".join(limits))
    if not iso_letters:
        review.append(f"{cert}: no food chain categories found")
    approved = sorted(l for l, ok in fssc.items() if ok)
    f = None
    if approved:
        f = Scope()
        for l in approved:
            f.ea |= bas.expand(bas.FOOD_CATEGORIES[l])
        f.notes.append(f"FSSC 22000 approved categories {', '.join(approved)} (classified to EA by sector)")
    return s, f


def energy_scope(cert: str, rows: list[dict]) -> Scope:
    s = Scope()
    letters: set[str] = set()
    for r in rows:
        c = cells(r)
        if r["row_type"] != "data" or len(c) < 2:
            continue
        desc = c[1].lower()
        for letter, pat in ENERGY_WORDS:
            if re.search(pat, desc):
                if letter == "C" and "D" in letters and "complex" in desc:
                    continue
                letters.add(letter)
                if letter in "BA" and pat in ("heavy", "light"):
                    break
                if letter == "D":
                    break
    for l in letters:
        s.ea |= bas.expand(ENERGY_EA[l][1])
    s.notes.append("ISO 50003 technical areas " + ", ".join(
        f"{l} ({ENERGY_EA[l][0]})" for l in sorted(letters)) + " (classified to EA by sector)")
    return s


def all_scope() -> Scope:
    s = Scope()
    s.all = True
    s.notes.append(ALL_NOTE)
    return s


# --------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "nabcb_output"))
    ap.add_argument("--out", default=str(HERE.parent.parent / "certifind" / "data" / "nabcb-india"))
    args = ap.parse_args()

    entries = json.load(open(Path(args.data) / "all_data.json", encoding="utf-8"))["accreditations"]

    # Certificates listed both as active and in the withdrawn table: withdrawn wins.
    # Matched per scheme: QM001 is DNV's active QMS and its withdrawn MDQMS certificate.
    withdrawn_keys = {(norm_cert(e["certificate_no"]), body_key(e["name"]), SCHEMES.get(clean(e["scheme"]).lower()))
                      for e in entries if e["status"].lower() not in ("active", "suspended")}

    certs = []   # normalised certificate pages
    skipped = defaultdict(list)
    for e in entries:
        cert = norm_cert(e["certificate_no"] or "")
        key = body_key(e["name"])
        scheme = clean(e["scheme"]).lower()
        if not cert:
            skipped["no certificate number"].append(e["name"])
            continue
        if key in SKIP_BODIES:
            skipped["Standards Organisation of Nigeria rows (copy other bodies' numbers)"].append(cert)
            continue
        if scheme in SKIPPED_SCHEMES:
            skipped[SKIPPED_SCHEMES[scheme]].append(f"{cert} {display_name(e['name'])}")
            continue
        kind, standard = SCHEMES[scheme]
        status = {"active": "ACTIVE", "suspended": "SUSPENDED"}.get(e["status"].lower(), "WITHDRAWN")
        if status == "ACTIVE" and (cert, key, (kind, standard)) in withdrawn_keys:
            review.append(f"{cert} {e['name'][:40]}: listed as active and as withdrawn; withdrawn kept")
            status = "WITHDRAWN"
        issued = parse_date(e["initial_issue_date"]) or parse_date(e["valid_from"]) or parse_date(e["listing_valid_upto"])
        detail_exp = parse_date(e["valid_upto"])
        list_exp = parse_date(e["listing_valid_upto"])
        expires = (detail_exp or list_exp) if status != "WITHDRAWN" else (list_exp or detail_exp)
        if status != "WITHDRAWN" and detail_exp and list_exp and detail_exp != list_exp:
            review.append(f"{cert} ({standard}) {display_name(e['name'])}: valid to {detail_exp} on the "
                          f"certificate page, {list_exp} in the list; certificate page used")
        if status == "ACTIVE" and expires and expires < TODAY:
            # Still in NABCB's active list, but the validity has passed: expired, not searchable.
            review.append(f"{cert} ({standard}) {display_name(e['name'])}: listed as active but valid to "
                          f"{expires}; treated as expired and removed")
            status = "WITHDRAWN"
        certs.append(dict(e=e, cert=cert, key=key, kind=kind, standard=standard, status=status,
                          issued=issued, expires=expires, url=e["detail_url"]))

    by_body = defaultdict(list)
    for c in certs:
        by_body[c["key"]].append(c)

    bodies_out, acc_out, scope_out = [], [], []
    used_numbers: dict[str, str] = {}

    def claim(number: str, key: str) -> None:
        if number in used_numbers and used_numbers[number] != key:
            raise SystemExit(f"certificate number {number} used by {used_numbers[number]} and {key}")
        used_numbers[number] = key

    def fmt(d: date | None) -> str:
        return d.isoformat() if d else ""

    for key, cs in sorted(by_body.items()):
        live = [c for c in cs if c["status"] != "WITHDRAWN"]
        active = [c for c in cs if c["status"] == "ACTIVE"]
        base_live = [c for c in live if c["kind"] == "base"]
        base_active = [c for c in base_live if c["status"] == "ACTIVE"]
        scheme_live = [c for c in live if c["kind"] == "scheme"]

        def prio(c):
            return (BASE_PRIORITY.get(c["cert"][:2], 9), c["cert"])

        if base_active:
            base_cert = min(base_active, key=prio)
            borrowed = None
        elif scheme_live:
            borrowed = min([c for c in scheme_live if c["status"] == "ACTIVE"] or scheme_live,
                           key=lambda c: c["cert"])
            base_cert = borrowed
        elif base_live:
            base_cert, borrowed = min(base_live, key=prio), None
        else:
            # Only withdrawn / expired certificates: kept for the record, without scopes.
            base_cert = min([c for c in cs if c["kind"] == "base"] or cs, key=prio)
            borrowed = None

        name_src = base_cert["e"]
        name = DISPLAY.get(key) or display_name(name_src["name"])
        contact = next((c["e"] for c in [base_cert] + cs if c["e"].get("address")), name_src)
        body_country = country(key, contact.get("address", ""))
        bodies_out.append({
            "name": name, "country": body_country, "registration_no": "",
            "phone": phone(contact.get("tel") or contact.get("mobile"), key),
            "email": email(contact.get("email")), "website": website(contact.get("website")),
            "address": clean(contact.get("address")), "source_url": base_cert["url"], "verified_at": "",
        })

        # ISO/IEC 17021-1 base row.
        base_number = base_cert["cert"]
        claim(base_number, key)
        if live:
            merged = base_active or base_live
            src = merged if merged and not borrowed else [base_cert]
            issued = min(c["issued"] for c in src if c["issued"])
            exps = [c["expires"] for c in src if c["expires"]]
            expires = max(exps) if exps else None
            status = "ACTIVE" if active else "SUSPENDED"
        else:
            issued, expires = base_cert["issued"], base_cert["expires"]
            status = "WITHDRAWN"
        if expires and issued and expires < issued:
            expires = None
        acc_out.append({"ab_code": AB_CODE, "certificate_number": base_number, "body_name": name,
                        "accreditation_standard": BASE, "status": status, "issue_date": fmt(issued),
                        "expiry_date": fmt(expires), "proof_url": base_cert["url"]})

        # Scopes merged into the base row.
        base_scopes: dict[str, list[tuple[dict, Scope]]] = defaultdict(list)
        for c in base_live:
            rows = c["e"].get("scope_rows", [])
            std = c["standard"]
            if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
                if c["cert"] == "EM036":
                    review.append("EM036 URS: page lists only SERI R2v3, no ISO 14001 sectors; not imported")
                    continue
                sc = iaf_scope(c["cert"], [r for r in rows if not re.search(r"A\s?1\.", " ".join(cells(r)))])
                if not sc.ea:
                    review.append(f"{c['cert']} ({std}) {name}: no IAF codes on the page; not imported")
                    continue
            elif std == "ISO 13485":
                sc = md_scope(c["cert"], rows)
                if not sc.ea:
                    continue
            else:
                sc = all_scope()
            base_scopes[std].append((c, sc))
        for std, parts in base_scopes.items():
            ea: set[int] = set()
            notes: list[str] = []
            statuses = {c["status"] for c, _ in parts}
            for c, sc in parts:
                if sc.all:
                    ea = set(range(1, 40))
                ea |= sc.ea
                notes += sc.notes
                if c["cert"] != base_number:
                    v = f"valid to {c['expires']}" if c["expires"] else "no valid-to date"
                    st ="" if c["status"] == "ACTIVE" else f", {c['status'].lower()}"
                    notes.append(f"NABCB certificate {c['cert']}{st}, {v}")
            scope_out.append({"certificate_number": base_number, "certification_standard": std,
                              "ea_codes": "ALL" if len(ea) == 39 else bas.ea_spec(ea),
                              "status": "ACTIVE" if "ACTIVE" in statuses else "SUSPENDED",
                              "scope_note": "; ".join(dict.fromkeys(notes))})

        # Scheme rows.
        seen_standards: dict[str, str] = {}
        for c in sorted(scheme_live, key=lambda c: c["cert"]):
            acc_std, suffix = SCHEME_ROWS[c["standard"]]
            if acc_std in seen_standards:
                raise SystemExit(f"{key}: two live {acc_std} certificates ({seen_standards[acc_std]}, {c['cert']})")
            number = c["cert"] + (suffix if c is borrowed else "")
            seen_standards[acc_std] = number
            claim(number, key)
            expires = c["expires"]
            acc_out.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                            "accreditation_standard": acc_std, "status": c["status"],
                            "issue_date": fmt(c["issued"]), "expiry_date": fmt(expires), "proof_url": c["url"]})
            rows = c["e"].get("scope_rows", [])
            extra: list[tuple[str, Scope]] = []
            if c["standard"] == "ISO 22000":
                iso, fssc = food_scope(number, rows)
                extra.append(("ISO 22000", iso))
                if fssc:
                    extra.append(("FSSC 22000", fssc))
            elif c["standard"] == "ISO 50001":
                extra.append(("ISO 50001", energy_scope(number, rows)))
            else:
                extra.append((c["standard"], all_scope()))
                if c["standard"] == "ISO/IEC 27001" and any("27701" in " ".join(cells(r)) + r.get("section", "")
                                                            for r in rows):
                    extra.append(("ISO/IEC 27701", all_scope()))
            for std, sc in extra:
                if not sc.all and not sc.ea:
                    continue
                scope_out.append({"certificate_number": number, "certification_standard": std,
                                  "ea_codes": sc.spec(), "status": c["status"],
                                  "scope_note": "; ".join(sc.notes)})

    # Display names must be unique within a country (bodies.csv key).
    names = defaultdict(list)
    for b in bodies_out:
        names[(b["country"], b["name"])].append(b)
    dup = [n for n, v in names.items() if len(v) > 1]
    if dup:
        raise SystemExit(f"duplicate body names: {dup}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for file, cols, rows, sort in (
            ("bodies.csv", BODY_COLUMNS, bodies_out, lambda r: r["name"].lower()),
            ("accreditations.csv", ACCREDITATION_COLUMNS, acc_out, lambda r: r["certificate_number"]),
            ("scopes.csv", SCOPE_COLUMNS, scope_out, lambda r: (r["certificate_number"], r["certification_standard"]))):
        with open(out / file, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(sorted(rows, key=sort))

    # CertiFind keeps only bodies with a valid accreditation (database/prune_inactive.py):
    # withdrawn, expired and suspended bodies and rows are removed.
    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    pruned = prune(out)
    acc_out = list(csv.DictReader(open(out / "accreditations.csv", encoding="utf-8")))
    bodies_out = list(csv.DictReader(open(out / "bodies.csv", encoding="utf-8")))
    scope_out = list(csv.DictReader(open(out / "scopes.csv", encoding="utf-8")))

    with open(HERE / "nabcb_review.md", "w", encoding="utf-8") as f:
        f.write("# NABCB conversion review\n\nGenerated by prepare_certifind.py.\n\n## Open points\n\n")
        f.writelines(f"- {line}\n" for line in dict.fromkeys(review))
        f.write("\n## Not imported\n\n")
        for reason, items in skipped.items():
            f.write(f"- {reason}: {', '.join(items)}\n")
        f.write(f"\n## Removed: no valid accreditation ({len(pruned)})\n\n")
        f.writelines(f"- {line}\n" for line in pruned)

    by_status = defaultdict(int)
    for a in acc_out:
        by_status[(a["accreditation_standard"], a["status"])] += 1
    print(f"bodies {len(bodies_out)}, accreditations {len(acc_out)}, scope rows {len(scope_out)}")
    for k, v in sorted(by_status.items()):
        print(f"  {k[0]:18} {k[1]:10} {v}")
    print(f"review points: {len(dict.fromkeys(review))} (see nabcb_review.md)")


if __name__ == "__main__":
    main()
