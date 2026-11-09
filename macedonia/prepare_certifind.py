#!/usr/bin/env python3
"""Turn the IARM scraper output into a CertiFind dataset (bodies.csv, accreditations.csv, scopes.csv).

Reads iarm_cb_management/bodies.json and the current annex of each body that
`iarm_scraper.py` downloaded, and writes the three CSVs in the CertiFind importer format.

The annexes give, per certification standard (ISO 9001 / 14001 / 45001), a table
"IAF code | sector | NACE rev. 2" with IAF codes as per IAF ID 1:2023, which are the EA codes.
pdfplumber flattens these tables unpredictably (an IAF cell can land on the line above or
below its row, and a NACE cell like "17" can sit alone on a line), so the tables are
transcribed below in ANNEX_TABLES and checked against the extracted text on every run:
every transcribed EA code and NACE code must appear in the section, and every row that
starts with a code and a sector name must be transcribed. When a row's NACE list is narrower
than the IAF ID 1 sector, the scope note says "Limited scope", as in the BAS dataset; the
IAF ID 1 table and the NACE comparison are reused from database/bulgaria/prepare_certifind.py.

Run:  python prepare_certifind.py  [--data iarm_cb_management] [--out ../../certifind/data/iarm-north-macedonia]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Reuse the IAF ID 1 sector table and NACE helpers of the Bulgarian dataset.
_spec = importlib.util.spec_from_file_location("bas_prepare", HERE.parent / "bulgaria" / "prepare_certifind.py")
bas = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(HERE.parent / "bulgaria"))
_spec.loader.exec_module(bas)

AB_CODE = "IARM"
COUNTRY = "North Macedonia"

BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

# Latin name (Cyrillic look-alike letters in the register fixed) + Macedonian legal name.
NAMES = {
    "CB-005": "MQS – Macedonian Trade Company for Certification and Assessment DOO Skopje "
              "(МКС – Македонско трговско друштво за сертификација и оценување ДОО Скопје)",
    "CB-006": "MKD Sertifikat – Certification Body of AM Cert DOOEL Skopje "
              "(МКД Сертификат – Сертификационо тело при АМ ЦЕРТ ДООЕЛ Скопје)",
    "CB-009": "Intercert DOOEL Skopje (Интерцерт ДООЕЛ Скопје)",
}

# Location from the current annex header (the register page for CB-009 still shows the
# earlier street name, Jordan Mijalkov; both annexes since 26.11.2025 say Železnička).
ADDRESSES = {
    "CB-005": "Bul. Partizanski Odredi 106-1/002, Skopje, North Macedonia",
    "CB-006": "16 Makedonska brigada No. 2, 1000 Skopje, North Macedonia",
    "CB-009": "Železnička 44/2-10, 1000 Skopje, North Macedonia",
}

# The annex each body's scope is read from: the one the register page links as current.
CURRENT_ANNEX = {
    "CB-005": "2026-08_OB-05-23-prilog-2026-web_ST-005_25.08.2026.txt",
    "CB-006": "2025-11_OB-05-23-Прилог-МКД-za-web_ST-006_17.11.2025.txt",
    "CB-009": "2026-08_OB-05-23-prilog-Intercert-2026_ST-009_19.08.2026.txt",
}
ANNEX_DATES = {"CB-005": "14.08.2026", "CB-006": "29.10.2025", "CB-009": "05.08.2026"}

# CB-009's current annex is published stamped "ПРЕДЛОГ" (draft) with an unsigned signature
# block. Codes it adds over the last signed annex (26.11.2025) are kept, with a note.
# SIGNED_EA is the EA list of that signed annex, transcribed and checked like ANNEX_TABLES.
DRAFT_ANNEX = {
    "CB-009": ("2025-12_OB-05-23-3.7-Prilog-OA-Intercert-2025-Final_ST-009_11.12.2025.txt", "26.11.2025"),
}
SIGNED_EA = {
    "CB-009": {
        "ISO 9001": {2, 7, 8, 9, 15, 16, 17, 18, 19, 24, 25, 27, 28, 29, 31, 32, 33, 34, 35, 36, 37, 38, 39},
        "ISO 14001": {2, 7, 8, 9, 14, 15, 16, 17, 18, 19, 22, 24, 25, 26, 27, 28, 29, 31, 32, 33, 34, 35,
                      36, 37},
        "ISO 45001": {2, 7, 8, 9, 14, 15, 16, 17, 18, 19, 22, 24, 25, 26, 27, 28, 29, 31, 32, 33, 34, 35,
                      36, 37, 39},
    },
}

# EA (= IAF ID 1:2023 code) -> NACE rev. 2 cell, transcribed from the current annexes.
_INTERCERT_FULL = {
    2: "05, 06, 07, 08, 09", 3: "10, 11, 12", 4: "13, 14", 7: "17", 8: "58.1, 59.2", 9: "18",
    14: "22", 15: "23 except 23.5, 23.6", 16: "23.5, 23.6", 17: "25 except 25.4, 33.11",
    18: "25.4, 28, 30.4, 33.12, 33.2", 19: "26, 27, 33.13, 33.14, 95.1", 22: "29, 30.2, 30.9, 33.17",
    23: "31, 32, 33.19", 24: "38.3", 25: "35.1", 26: "35.2", 27: "35.3, 36", 28: "41, 42, 43",
    29: "45, 46, 47, 95.2", 30: "55, 56", 31: "49, 50, 51, 52, 53, 61", 32: "64, 65, 66, 68, 77",
    33: "58.2, 62, 63.1", 34: "71, 72, 74 except 74.2, 74.3",
    35: "69, 70, 73, 74.2, 74.3, 78, 80, 81, 82", 36: "84", 37: "85",
}
ANNEX_TABLES = {
    "CB-005": {
        "ISO 9001": {3: "10.83, 12", 25: "35.11", 28: "42", 29: "46, 47", 33: "62, 63.1", 36: "84"},
        "ISO 14001": {3: "10.83, 12", 25: "35.11", 28: "42", 29: "46, 47", 33: "62, 63.1"},
        "ISO 45001": {25: "35.11", 28: "42", 33: "63.1"},
    },
    "CB-006": {
        "ISO 9001": {18: "28.12", 29: "45, 47", 34: "71", 35: "69", 36: "84", 38: "86"},
        "ISO 14001": {18: "28.12", 29: "45, 47", 35: "69", 36: "84"},
        "ISO 45001": {18: "28.12", 29: "45, 47", 35: "69", 36: "84"},
    },
    "CB-009": {
        "ISO 9001": {
            **{k: v for k, v in _INTERCERT_FULL.items() if k not in (14, 22, 26)},
            1: "01, 02, 03", 17: "24 except 24.46, 25 except 25.4, 33.11",
            38: "75, 86, 87, 88", 39: "37, 38.1, 38.2, 39, 59.1, 60, 63.9, 79, 90, 91, 92, 93, 94, 96",
        },
        "ISO 14001": {**_INTERCERT_FULL, 38: "75, 86, 87, 88"},
        "ISO 45001": {**_INTERCERT_FULL, 39: "37, 38.1, 38.2, 39"},
    },
}

# Section headings (English line of each annex section) -> certification standard.
SECTION_HEADINGS = {
    "ISO 9001": "Quality management system certification, according to",
    "ISO 14001": "Environmental management systems certification, according to",
    "ISO 45001": "Occupational health and safety management systems certification, according to",
}
SECTION_END = "*IAF код"
PAGE_FURNITURE = re.compile(r"^(?:Издание|Страна|Верзија|ИНСTИТУТ|INSTITUTE|ПРЕДЛОГ)\b.*$", re.M)
ROW_START = re.compile(r"^(\d{1,2}) +[А-Яа-яЃѓЌќЉљЊњЏџЅѕЈј]", re.M)
CODE = re.compile(r"\d{1,2}(?:\.\d{1,2})?")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def iso_date(value: str) -> str:
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", re.sub(r"\s+", "", value))
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def sections_of(text: str) -> dict[str, str]:
    """Annex text -> {standard: text of its sector table}."""
    text = PAGE_FURNITURE.sub("", text)
    out = {}
    for standard, heading in SECTION_HEADINGS.items():
        start = text.find(heading)
        if start < 0:
            continue
        end = text.find(SECTION_END, start)
        out[standard] = text[start:end if end > 0 else None]
    return out


def table_of(section: str) -> str:
    """Section text without its heading (which cites the standard numbers)."""
    return section.split("NACE rev.2**", 1)[-1]


def check(cert: str, standard: str, section: str, table: dict[int, str], problems: list[str]) -> None:
    body = table_of(section).replace("и", " , ")
    tokens = {bas.norm_code(t) for t in CODE.findall(body)}
    for ea, nace in table.items():
        if bas.norm_code(str(ea)) not in tokens:
            problems.append(f"{cert} {standard}: EA {ea} not in the annex text")
        for code in CODE.findall(nace):
            if bas.norm_code(code) not in tokens:
                problems.append(f"{cert} {standard}: NACE {code} (EA {ea}) not in the annex text")
    for m in ROW_START.finditer(table_of(section)):
        if int(m[1]) not in table:
            problems.append(f"{cert} {standard}: annex row '{m[0]}…' is not transcribed")


def scope_note(table: dict[int, str], extra: list[str]) -> str:
    limited = []
    for ea in sorted(table):
        listed = bas.parse_nace(table[ea])
        if bas.is_limited(ea, listed):
            limited.append(f"EA {ea} (NACE {', '.join(str(n) for n in listed)})")
    parts = [f"Limited scope (part of the sector): {'; '.join(limited)}"] if limited else []
    return "; ".join(parts + extra)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    payload = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    bodies, accreditations, scopes = [], [], []

    for body in payload["bodies"]:
        cert = body["certificate_key"]
        en = body["translations"]["en"]
        if body["status"] != "active":
            problems.append(f"{cert}: status '{body['status']}' is not handled")
            continue
        current = next(d for d in body["documents"] if d["kind"] == "current_annex")
        if Path(current["local_path"]).with_suffix(".txt").name != CURRENT_ANNEX[cert]:
            problems.append(f"{cert}: register now links {current['file_name']}; update ANNEX_TABLES")
        folder = args.data / Path(current["local_path"]).parent
        sections = sections_of((folder / CURRENT_ANNEX[cert]).read_text(encoding="utf-8"))
        if set(sections) != set(ANNEX_TABLES[cert]):
            problems.append(f"{cert}: annex sections {sorted(sections)} differ from ANNEX_TABLES")

        previous = {}
        if cert in DRAFT_ANNEX:
            previous = sections_of((folder / DRAFT_ANNEX[cert][0]).read_text(encoding="utf-8"))

        name = NAMES[cert]
        page = en["url"]
        website = en["websites"][0] if en["websites"] else ""
        bodies.append({
            "name": name, "country": COUNTRY, "registration_no": "", "phone": "", "email": "",
            "website": f"http://{website}" if website and not website.startswith("http") else website,
            "address": ADDRESSES[cert], "source_url": page, "verified_at": "",
        })
        accreditations.append({
            "ab_code": AB_CODE, "certificate_number": cert, "body_name": name,
            "accreditation_standard": "ISO/IEC 17021-1", "status": "ACTIVE",
            "issue_date": iso_date(en["first_accreditation"]),
            "expiry_date": iso_date(en["valid_until"]), "proof_url": page,
        })
        for standard, table in ANNEX_TABLES[cert].items():
            check(cert, standard, sections.get(standard, ""), table, problems)
            extra = []
            if cert in DRAFT_ANNEX:
                signed = SIGNED_EA[cert][standard]
                check(f"{cert} (signed annex)", standard, previous.get(standard, ""),
                      {ea: "" for ea in signed}, problems)
                added = sorted(set(table) - signed)
                if signed - set(table):
                    extra.append(f"EA {', '.join(map(str, sorted(signed - set(table))))} in the signed annex "
                                 f"dated {DRAFT_ANNEX[cert][1]} but not in the current one")
                if added:
                    extra.append(f"EA {', '.join(map(str, added))} from the annex dated {ANNEX_DATES[cert]}, "
                                 f"published marked draft (ПРЕДЛОГ); not in the signed annex dated "
                                 f"{DRAFT_ANNEX[cert][1]}")
            scopes.append({
                "certificate_number": cert, "certification_standard": standard,
                "ea_codes": bas.ea_spec(set(table)), "status": "ACTIVE",
                "scope_note": scope_note(table, extra),
            })

    if problems:
        print("Problems:", *problems, sep="\n  ")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda r: r["name"]))
    write_csv(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, accreditations)
    write_csv(args.out / "scopes.csv", SCOPE_COLUMNS, scopes)
    print(f"{len(bodies)} bodies, {len(accreditations)} accreditations, {len(scopes)} scopes -> {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=HERE / "iarm_cb_management")
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "certifind" / "data" / "iarm-north-macedonia")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
