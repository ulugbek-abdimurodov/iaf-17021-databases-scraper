#!/usr/bin/env python3
"""Convert the SAS (Swiss Accreditation Service) SCESm scrape into a CertiFind dataset folder
(bodies.csv, accreditations.csv, scopes.csv).

Input: the SCESm folder written by sas_scraper.py (bodies.csv and text/<id>-<lang>.txt, the
text of each body's "SCESm directory" PDF in every language SAS publishes). Each SCESm
number is one accreditation with one validity; its directory lists the certification
standards and, per standard, the IAF codes (ISO 9001 / 14001 / 45001, ISO/IEC 20000-1),
ISO 22003-1 food chain categories (ISO 22000, FSSC 22000), ISO 50003 technical areas
(ISO 50001) or IAF MD 8 main technical areas (ISO 13485).

Language: every directory says which language version prevails (German, for SCESm 0095
Italian). IAF codes are read from that version; the other versions are parsed as well and
any difference is written to sas_review.md. Food categories, energy areas and medical
areas are read by name from the English version (else the prevailing one).

    python prepare_certifind.py <SCESm scrape folder> <dataset folder> [--today YYYY-MM-DD]

Open points go to sas_review.md next to this script; prune_inactive.prune() then drops
everything that is not currently valid.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
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

AB_CODE = "SAS"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://www.seco.admin.ch/en/search-accredited-bodies-sas"
PDF_URL = "https://sas.seco.amboss.liip.cloud/media/pdf/{id}-{lang}.pdf"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the SAS directory; recorded for all EA sectors"

# Section heading in the directory -> (CertiFind certification standard, kind of sector list).
# kind "skip": known, deliberately not imported (national schemes, PKI audits, directives);
# it still opens a section so its text is not read as part of the previous standard.
HEADINGS = [
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*9001\s*:", "ISO 9001", "iaf"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*14001\s*:", "ISO 14001", "iaf"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*45001\s*:", "ISO 45001", "iaf"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*22000\b", "ISO 22000", "food"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*50001\s*:", "ISO 50001", "energy"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*13485\s*:", "ISO 13485", "medical"),
    (r"ISO/IEC\s*27001\s*:", "ISO/IEC 27001", "iaf"),
    (r"ISO/IEC\s*20000-1\s*:", "ISO/IEC 20000-1", "iaf"),
    (r"ISO/IEC\s*42001\s*:", "ISO/IEC 42001", "iaf"),
    (r"(?:SN\s+)?(?:EN\s+)?ISO\s*3834-[234]\s*:", "ISO 3834", "all"),
    (r"ISO\s*21001\s*:", "ISO 21001", "all"),
    (r"ISO\s*15378\s*:", "ISO 15378", "all"),
    (r"EN\s*9100\s*:", "AS 9100", "all"),
    (r"EN\s*9120\s*:", None, "skip"), (r"AQAP", None, "skip"), (r"eduQua", None, "skip"),
    (r"IN-Qualis", None, "skip"), (r"QSC\s*:", None, "skip"), (r"FAMI-QS", None, "skip"),
    (r"DIN\s+EN\s+15593", None, "skip"), (r"ISO\s*27799", None, "skip"),
    (r"ISO\s*21188", None, "skip"), (r"SR\s+\d", None, "skip"), (r"BS\s+10008", None, "skip"),
    (r"CA/Browser", None, "skip"), (r"WEBTRUST", None, "skip"),
    (r"Normative Grundlage", None, "skip"), (r"Qualitätsstandards für", None, "skip"),
    (r"Ordinance on the safety", None, "skip"), (r"Verordnung über die Sicherheit", None, "skip"),
]
HEADING_RES = [(re.compile(r"^\s*" + p), std, kind) for p, std, kind in HEADINGS]
SKIP_NAMES = {
    "EN\\s*9120": "EN 9120 / AS 9120 (aerospace stockist distributors)",
    "AQAP": "NATO AQAP 2110", "eduQua": "eduQua (Swiss label for continuing education)",
    "IN-Qualis": "IN-Qualis (Swiss labour-market integration measures)",
    "QSC": "QSC (Swiss quality standard for schools)",
    "FAMI-QS": "FAMI-QS (feed additives code)", "DIN\\s+EN\\s+15593": "DIN EN 15593 (packaging hygiene)",
    "ISO\\s*27799": "ISO 27799 (only with ISO/IEC 27001; not in CertiFind's standards)",
    "ISO\\s*21188": "ISO 21188 (PKI for financial services)",
    "SR\\s+\\d": "Swiss ordinance (data protection VDSZ, electronic patient record, pressure "
                 "equipment / lifts module H)",
    "BS\\s+10008": "BS 10008 (electronic records)",
    "CA/Browser": "CA/Browser Forum requirements", "WEBTRUST": "WebTrust for CAs",
    "Normative Grundlage": "Swiss Care Excellence Certificate (nursing quality)",
    "Qualitätsstandards für": "SanaCERT quality standards (Swiss health care)",
    "Ordinance on the safety": "Swiss ordinance (lifts / pressure equipment, module H)",
    "Verordnung über die Sicherheit": "Swiss ordinance (lifts / pressure equipment, module H)",
}

# Certification standard -> (accreditation standard, certificate-number suffix). Everything
# else is certified under the ISO/IEC 17021-1 row with the plain SCESm number.
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "FSSC 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", " (42001)"),
    "AS 9100": ("AS 9104-1", " (9104)"),
}

# One IAF row: label text then the code at the end of the line, optionally restricted to one
# of two standards sharing the table ("4 (only for ISO 9001:2015)", "4 (einzig für ISO 9 001:2015)"),
# or followed by a NACE restriction ("20 Code NACE 35-12 pleasure and sporting boats").
IAF_ROW = re.compile(r"(?:^|\s)(\d{1,2})\s*(?:\((?:only for|nur für|einzig für|uniquement pour|"
                     r"seulement pour|solo per)\s*ISO\s*([\d ]{4,6}?)\s*:[^)]*\)|\s+(Code NACE.*))?\s*$",
                     re.I)
NOT_A_ROW = re.compile(r"Code\s+\d|IAF-?\s*Code\s+\d|Codice IAF\s+\d|IAF\s+\d|MD\s*\d|Table|"
                       r"Tabelle|Version|Ausgabe|Anhang|Annex|Article|Artikel|SR\s", re.I)
# Food chain categories (ISO 22003-1; FSSC 22000 subcategories start with the same letter).
FOOD_CODE = re.compile(r"(?:^|\s)(BIII|BII|BI|C0|CIV|CIII|CII|CI|FII|FI|[A-K])\s+(?=[A-ZÀ-Ý][a-zà-ÿ])")
ENERGY_WORDS = [("A", r"light to medium|leicht bis mittel|légère|leggera"),
                ("B", r"Industry\s*[–-]\s*heavy|Schwerindustrie|lourde|pesante"),
                ("D", r"Building complexes|Gebäudekomplexe|Complexes|Complessi"),
                ("C", r"^-\s*(?:Buildings|Gebäude|Bâtiments|Edifici)\s*$"),
                ("E", r"^-\s*(?:Transport|Trasporti)"), ("F", r"^-\s*(?:Mining|Bergbau|Mines|Estrazione)"),
                ("G", r"^-\s*(?:Agricultur|Landwirtschaft|Agricoltura)"),
                ("H", r"Energy supply|Energieversorgung|Approvisionnement|Fornitura")]
ENERGY_NAMES = {"A": "industry – light to medium", "B": "industry – heavy", "C": "buildings",
                "D": "building complexes", "E": "transport", "F": "mining", "G": "agriculture",
                "H": "energy supply"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
MEDICAL_HEADINGS = [  # upper-case table headings of the English directories (IAF MD 8)
    ("Non-active medical devices", r"NON-ACTIVE MEDICAL"),
    ("Active (non-implantable) medical devices", r"ACTIVE \(NON-IMPLANTABLE\)"),
    ("Active implantable medical devices", r"ACTIVE IMPLANTABLE"),
    ("In vitro diagnostic medical devices", r"IN VITRO DIAGNOSTIC MEDICAL"),
    ("Sterilization methods", r"STERILIZATION METHODS"),
    ("Devices incorporating specific substances / technologies", r"INCORPORATING\s*/"),
    ("Parts or services", r"PARTS AND SERVICES"),
]
MEDICAL_EA = {name: spec for name, _, spec in esyd.MEDICAL_AREAS}
# Words in an IAF row label that restrict the code; kept in the scope note.
LIMITING = re.compile(r"\b(only|without|limited|excluding|nur|ohne|ausschliesslich|"
                      r"uniquement|sans|solo|senza|NACE)\b", re.I)

BINDING = [(r"deutsche Fassung|German\s+version|version allemande|versione tedesca", "de"),
           (r"italienische Fassung|Italian\s+version|version italienne|versione italiana", "it"),
           (r"französische Fassung|French\s+version|version française|versione francese", "fr")]
SCOPE_START = re.compile(r"Scope of accreditation as|Geltungsbereich der Akkreditierung|"
                         r"Portée de l.accréditation|Campo d.applicazione dell.accreditamento")
SCOPE_END = re.compile(r"In case of contradictions|Bei Widersprüchen|En cas de contradictions|"
                       r"In caso di contraddizioni|^Abbreviation|^Abkürzung|^Abréviation|^Abbreviazione")
PAGE_HEADER = re.compile(r"^(Federal Department|Education and Research|State Secretariat|"
                         r"Swiss Accreditation Service|SCESm[- ]|Eidgenössisches|Wirtschaft, Bildung|"
                         r"Staatssekretariat|Schweizerische Akkreditierungsstelle|Département fédéral|"
                         r"de la formation|Secrétariat d|Service d.accréditation|Registre SCESm|"
                         r"Dipartimento federale|della formazione|Segreteria di Stato|"
                         r"Servizio di accreditamento|Registro SCESm|Standards\s+Approved|"
                         r"Normen\s+Zugelassene|Normes\s+Domaines|Norma\s+Campi|Bereiche\s*$|"
                         r"Bemerkungen\s*$)|^\s*\d{2}\.\d{2}\.\d{4}\s*/|^jzdr", re.I)

# Body names: SAS prints the department or branch after the legal entity's name.
DISPLAY = {
    "SCESm 0001": "Schweizerische Vereinigung für Qualitäts- und Managementsysteme (SQS)",
    "SCESm 0013": "Swiss Safety Center AG",
    "SCESm 0017": "SGS Société Générale de Surveillance SA",
    "SCESm 0047": "QS Zürich AG",
    "SCESm 0067": "SI Cert Sagl",
    "SCESm 0071": "KPMG AG",
    "SCESm 0095": "IAS Register AG",
}
# Address of the accredited site when the scraper's street field is not it.
ADDRESS = {
    "SCESm 0047": "Erlenstrasse 31, 4106 Therwil",
    "SCESm 0105": "Wasgenring 94, 4055 Basel",
}
DATE = re.compile(r"(\d{2})\s*\.\s*(\d{2})\s*\.\s*(\d\s*\d\s*\d\s*\d)")
CURRENT = re.compile(r"(?:Current accreditation|Aktuelle Akkreditierung|Accréditation actuelle|"
                     r"Accreditamento attuale)\s*:\s*([\d.\s]+?)\s+(?:to|bis|au|al)\s+([\d.\s]+?\d)\s*$",
                     re.M)


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def iso_date(raw: str) -> str:
    m = DATE.search(raw or "")
    return f"{m.group(3).replace(' ', '')}-{m.group(2)}-{m.group(1)}" if m else ""


def email(raw: str) -> str:
    value = clean(raw).replace("mailto:", "").replace(" ", "")
    return value


def website(raw: str) -> str:
    value = clean(raw).replace(" ", "").rstrip("/")
    if not value:
        return ""
    value = re.sub(r"^http://", "https://", value)
    return value if value.startswith("http") else "https://" + value


def ea_spec(codes: set[int]) -> str:
    if set(range(1, 40)) <= codes:
        return "ALL"
    out, run = [], []
    for c in sorted(codes):
        if run and c == run[-1] + 1:
            run.append(c)
        else:
            if run:
                out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [c]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ";".join(out)


def expand(spec: str) -> set[int]:
    out: set[int] = set()
    for part in spec.split(";"):
        lo, _, hi = part.partition("-")
        out |= set(range(int(lo), int(hi or lo) + 1))
    return out


# --------------------------------------------------------------------------- directory parsing
class Section:
    def __init__(self, standards: list[tuple[str | None, str, str]]):
        self.heads = standards           # [(standard, kind, heading text)]
        self.lines: list[str] = []

    def text(self) -> str:
        return "\n".join([h for _, _, h in self.heads] + self.lines)


def scope_lines(text: str) -> list[str]:
    lines, inside = [], False
    for line in text.splitlines():
        if not inside:
            inside = bool(SCOPE_START.search(line))
            continue
        if SCOPE_END.search(line):
            break
        if line.strip() and not PAGE_HEADER.search(line.strip()):
            lines.append(line.rstrip())
    return lines


def heading(line: str):
    for rx, std, kind in HEADING_RES:
        if rx.search(line):
            return std, kind
    return None


def split_sections(text: str) -> list[Section]:
    """Sections start at a standard's heading. Headings on consecutive lines with nothing in
    between (ISO 9001 / ISO 14001 sharing one table) form one section."""
    sections: list[Section] = []
    for line in scope_lines(text)[1:]:          # first line: the body's domain sentence
        head = heading(line)
        if head:
            std, kind = head
            if sections and not sections[-1].lines and sections[-1].heads[-1][1] != "skip" \
                    and kind != "skip":
                sections[-1].heads.append((std, kind, line.strip()))
            else:
                sections.append(Section([(std, kind, line.strip())]))
            # The heading line may carry the first IAF row ("ISO 9001:2015 Information technology 33").
            rest = re.sub(r"^\s*\S.*?:\s*\d{4}", "", line)
            if rest != line and IAF_ROW.search(rest) and not NOT_A_ROW.search(rest):
                sections[-1].lines.append(rest)
            continue
        if sections:
            sections[-1].lines.append(line)
    return sections


def iaf_codes(section: Section) -> tuple[dict[str, set[int]], list[str]]:
    """IAF codes per standard of the section, and the labels that limit a code."""
    stds = [s for s, k, _ in section.heads if k == "iaf"]
    per = {s: set() for s in stds}
    notes: dict[str, list[str]] = {}
    label: list[str] = []
    for i, line in enumerate(section.lines):
        m = IAF_ROW.search(line)
        if not m or NOT_A_ROW.search(line[:m.start(1)]):
            label.append(line.strip())
            continue
        code, only = int(m.group(1)), (m.group(2) or "").replace(" ", "") or None
        text = clean(" ".join(label[-3:] + [line[:m.start()]])) if not line[:m.start()].strip() \
            else clean(line[:m.start()])
        label = []
        if not 1 <= code <= 39:
            continue
        targets = [s for s in stds if only is None or s.endswith(only)]
        for s in targets:
            per[s].add(code)
        note = None
        if m.group(3):
            remark = clean(m.group(3))
            if remark.endswith("-") and i + 1 < len(section.lines):   # hyphenated over two lines
                remark = remark[:-1] + clean(section.lines[i + 1])
            note = f"EA {code}: {text} ({remark})"
        elif LIMITING.search(text):
            note = f"EA {code}: {text}"
        if note:
            for s in targets:
                notes.setdefault(s, []).append(note)
    return per, notes


def food_codes(text: str) -> tuple[set[str], bool]:
    """ISO 22003-1 category letters named in a food section, and whether it is FSSC 22000."""
    fssc = "FSSC" in text
    letters = {m.group(1)[0] for m in FOOD_CODE.finditer(text)}
    return letters, fssc


def energy_areas(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        for letter, rx in ENERGY_WORDS:
            if re.search(rx, line.strip(), re.I | re.M):
                found.add(letter)
                break
    return found


def medical_areas(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [name for name, rx in MEDICAL_HEADINGS if re.search(rx, flat)]


def skip_name(heading_text: str) -> str:
    for rx, name in SKIP_NAMES.items():
        if re.match(r"\s*" + rx, heading_text):
            return name
    return heading_text


# --------------------------------------------------------------------------- conversion
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    today = args.today.isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    with open(args.scrape / "bodies.csv", encoding="utf-8-sig") as f:
        records = list(csv.DictReader(f))

    review: list[str] = []
    body_rows, accreditations, scopes = [], [], []
    for rec in sorted(records, key=lambda r: r["accreditation_id"]):
        number = rec["accreditation_id"]
        stem = number.replace(" ", "-")
        texts = {p.stem.rsplit("-", 1)[1]: p.read_text(encoding="utf-8")
                 for p in sorted((args.scrape / "text").glob(f"{stem}-*.txt"))}
        any_text = next(iter(texts.values()))
        binding = "de"
        for rx, lang in BINDING:
            if any(re.search(rx, t) for t in texts.values()):
                binding = lang
                break
        main_lang = binding if binding in texts else next(iter(texts))
        if main_lang != binding:
            review.append(f"{number}: prevailing {binding} version not published; read {main_lang}")
        named_lang = "en" if "en" in texts else main_lang
        name = DISPLAY.get(number, clean(rec["company_name"]))

        # Validity: the scraper misses dates written with stray spaces ("24.03.202 5").
        start, end = iso_date(rec["accreditation_from"]), iso_date(rec["accreditation_to"])
        if not end:
            for t in texts.values():
                m = CURRENT.search(t)
                if m:
                    start, end = iso_date(m.group(1)), iso_date(m.group(2))
                    review.append(f"{number} {name}: validity read from the directory text "
                                  f"({start} to {end})")
                    break

        sections = {lang: split_sections(t) for lang, t in texts.items()}
        # IAF codes per standard, per language.
        iaf_by_lang: dict[str, dict[str, set[int]]] = {}
        notes_by_std: dict[str, list[str]] = {}
        for lang, secs in sections.items():
            acc: dict[str, set[int]] = {}
            for sec in secs:
                if not any(k == "iaf" for _, k, _ in sec.heads):
                    continue
                per, notes = iaf_codes(sec)
                for s, codes in per.items():
                    acc.setdefault(s, set()).update(codes)
                    if lang == named_lang:
                        have = notes_by_std.setdefault(s, [])
                        have.extend(n for n in notes.get(s, []) if n not in have)
            iaf_by_lang[lang] = acc
        main_iaf = iaf_by_lang[main_lang]
        for lang, acc in iaf_by_lang.items():
            if lang == main_lang:
                continue
            for s in sorted(set(acc) | set(main_iaf)):
                a, b = main_iaf.get(s, set()), acc.get(s, set())
                if a != b:
                    review.append(f"{number} {name}: {s} IAF codes differ, {main_lang} "
                                  f"{ea_spec(a) or '-'} vs {lang} {ea_spec(b) or '-'} "
                                  f"(the {main_lang} version is used)")

        # Standards present (from the prevailing version) and named-area sections.
        result: dict[str, tuple[set[int], str]] = {}
        food: dict[str, set[str]] = {}
        for sec in sections[main_lang]:
            for std, kind, head in sec.heads:
                if kind == "skip":
                    msg = f"{number} {name}: {skip_name(head)} not imported"
                    if msg not in review:
                        review.append(msg)
                elif kind == "all":
                    result.setdefault(std, (set(range(1, 40)), ALL_NOTE))
                elif kind == "iaf":
                    codes = main_iaf.get(std, set())
                    note = "; ".join(notes_by_std.get(std, []))
                    if codes:
                        result[std] = (codes, note)
                    else:
                        result.setdefault(std, (set(range(1, 40)), ALL_NOTE))
        named = sections[named_lang]
        for sec in named:
            kinds = {k for _, k, _ in sec.heads}
            if "food" in kinds:
                letters, fssc = food_codes(sec.text())
                food.setdefault("FSSC 22000" if fssc else "ISO 22000", set()).update(letters)
            if "energy" in kinds:
                areas = energy_areas(sec.text())
                if areas:
                    codes = set().union(*(expand(ENERGY_EA[a]) for a in areas))
                    result["ISO 50001"] = (codes, "ISO 50003 technical areas: " + "; ".join(
                        ENERGY_NAMES[a] for a in sorted(areas)) + " (classified to EA by area)")
                else:
                    result["ISO 50001"] = (set(range(1, 40)), "No ISO 50003 technical areas listed "
                                           "in the SAS directory; recorded for all EA sectors")
            if "medical" in kinds:
                areas = medical_areas(sec.text())
                prev = result.get("ISO 13485", (set(), ""))[0]
                if areas:
                    codes = prev | set().union(*(expand(MEDICAL_EA[a]) for a in areas))
                    old = result.get("ISO 13485", (None, ""))[1]
                    names = [a for a in MEDICAL_HEADINGS_ORDER if a in areas or a in old]
                    result["ISO 13485"] = (codes, "IAF MD 8 main technical areas: " + "; ".join(names)
                                           + " (classified to EA by area)")
        for std, letters in food.items():
            if not letters:
                review.append(f"{number} {name}: {std} section names no food chain category; "
                              f"recorded for all EA sectors")
                result[std] = (set(range(1, 40)), ALL_NOTE)
                continue
            codes = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in letters))
            result[std] = (codes, "ISO 22003-1 food chain categories: " + ", ".join(sorted(letters))
                           + " (classified to EA by category)")
        if "FSSC 22000" in result and "ISO 22000" not in result:
            result["ISO 22000"] = result["FSSC 22000"]

        if not result:
            review.append(f"body {name} ({number}): only national schemes; not imported")
            continue

        proof = PDF_URL.format(id=stem, lang=main_lang)
        e = {"status": "ACTIVE", "issue": start, "expiry": end, "url": proof}
        rows_needed = {BASE: number}
        for std in result:
            if std in SCHEME_ROWS:
                acc_std, suffix = SCHEME_ROWS[std]
                rows_needed[acc_std] = number + suffix
        for acc_std, cert in rows_needed.items():
            accreditations.append(acc_row(cert, name, acc_std, e))
        for std, (codes, note) in result.items():
            cert = number + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else number
            scopes.append(scope_row(cert, std, codes, note))

        street = clean(rec["street_address"])
        address = ADDRESS.get(number) or ", ".join(
            p for p in (street, f"{rec['postal_code']} {clean(rec['locality'])}".strip()) if p)
        body_rows.append({
            "name": name, "country": "Switzerland", "registration_no": number,
            "phone": clean(rec["phone"]), "email": email(rec["email"]),
            "website": website(rec["website"]), "address": address,
            "source_url": SOURCE_URL, "verified_at": "",
        })

    body_rows.sort(key=lambda b: b["name"].casefold())
    write(args.out / "bodies.csv", BODY_COLUMNS, body_rows)
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda a: a["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes, key=lambda s: (s["certificate_number"], s["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scopes))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)

    with open(HERE / "sas_review.md", "w", encoding="utf-8") as f:
        f.write("# SAS (Switzerland) conversion review\n\n")
        f.write(f"Generated {today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'sas_review.md'}")


MEDICAL_HEADINGS_ORDER = [n for n, _ in MEDICAL_HEADINGS]


def acc_row(cert: str, body: str, standard: str, e: dict) -> dict:
    return {"ab_code": AB_CODE, "certificate_number": cert, "body_name": body,
            "accreditation_standard": standard, "status": e["status"], "issue_date": e["issue"],
            "expiry_date": e["expiry"], "proof_url": e["url"]}


def scope_row(cert: str, std: str, codes: set[int], note: str) -> dict:
    return {"certificate_number": cert, "certification_standard": std, "ea_codes": ea_spec(codes),
            "status": "ACTIVE", "scope_note": note}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
