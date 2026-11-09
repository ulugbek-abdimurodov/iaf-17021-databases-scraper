"""Convert ATS (Accreditation Body of Serbia) scope-of-accreditation PDFs into the
CertiFind CSV dataset (data/ats-serbia).

    python prepare_certifind.py --out <certifind>/data/ats-serbia

Reads every 2-05-*.pdf in this folder (ATS file group 2-05: management-system
certification bodies, ISO/IEC 17021-1). Each PDF is one body: a header with the
accreditation number, initial accreditation date and expiry date, then one section per
reference standard with its technical areas.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

import pypdf

HERE = Path(__file__).resolve().parent

# Serbian Cyrillic -> Latin (official one-to-one transliteration).
CYR = dict(zip("АБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШабвгдђежзијклмнопрстћуфхцчш",
               "ABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠabvgdđežzijklmnoprstćufhcčš"))
CYR.update({"Љ": "Lj", "Њ": "Nj", "Џ": "Dž", "љ": "lj", "њ": "nj", "џ": "dž"})


def latin(text: str) -> str:
    return "".join(CYR.get(ch, ch) for ch in text)


# The NACE Rev. 2 codes IAF ID 1:2023 assigns to each EA sector, in the form ATS writes
# them. A row whose NACE list differs from this is a limited scope.
IAF_NACE = {
    1: "01,02,03", 2: "05,06,07,08,09", 3: "10,11,12", 4: "13,14", 5: "15", 6: "16",
    7: "17", 8: "58.1,59.2", 9: "18", 10: "19", 11: "24.46", 12: "20", 13: "21", 14: "22",
    15: "23 except 23.5,23.6", 16: "23.5,23.6", 17: "24 except 24.46,25 except 25.4,33.11",
    18: "25.4,28,30.4,33.12,33.2", 19: "26,27,33.13,33.14,95.1", 20: "30.1,33.15",
    21: "30.3,33.16", 22: "29,30.2,30.9,33.17", 23: "31,32,33.19", 24: "38.3", 25: "35.1",
    26: "35.2", 27: "35.3,36", 28: "41,42,43", 29: "45,46,47,95.2", 30: "55,56",
    31: "49,50,51,52,53,61", 32: "64,65,66,68,77", 33: "58.2,62,63.1",
    34: "71,72,74 except 74.2,74.3", 35: "69,70,73,74.2,74.3,78,80,81,82", 36: "84", 37: "85",
    38: "75,86,87,88", 39: "37,38.1,38.2,39,59.1,60,63.9,79,90,91,92,93,94,96",
}

# ISO 22003-1:2022 food chain categories, classified to EA by sector as in the other datasets.
FOOD_CATEGORIES = {
    "A": "1", "B": "1", "C": "3", "D": "3", "E": "30", "F": "29", "G": "31", "H": "35",
    "I": "7;14;15;17", "J": "18", "K": "12;13",
}

# ISO 13485 main technical areas (IAF MD 9), classified to EA by sector as in the ESYD dataset.
MEDICAL_AREAS = [
    ("Non-active medical devices", "неактивна", "13;14;17"),
    ("Active implantable medical devices", "активна имплантабилна", "19"),
    ("Active (non-implantable) medical devices", "активна медицинска", "19"),
    ("In vitro diagnostic medical devices", "in vitro", "12;13;19"),
    ("Sterilization methods", "методе", "35"),
    ("Devices incorporating specific substances / technologies", "средства која", "13"),
    ("Parts or services", "делови или услуге", "18;29;31;34;35"),
]

# Reference standard -> (certification standard, accreditation standard, certificate suffix).
SCHEMES = [
    ("ISO 9001", "ISO 9001", "ISO/IEC 17021-1", ""),
    ("ISO 14001", "ISO 14001", "ISO/IEC 17021-1", ""),
    ("ISO 45001", "ISO 45001", "ISO/IEC 17021-1", ""),
    ("ISO 13485", "ISO 13485", "ISO/IEC 17021-1", ""),
    ("ISO 22000", "ISO 22000", "ISO 22003-1", " (22000)"),
    ("ISO/IEC 27001", "ISO/IEC 27001", "ISO/IEC 27006", " (27006)"),
    ("ISO 50001", "ISO 50001", "ISO 50003", " (50003)"),
]

ALL_NOTE = "No sector list in annex; recorded for all EA sectors"
DATE = r"(\d{2})\.(\d{2})\.(\d{4})\.?"
NACE_TAIL = re.compile(r"((?:\b\d{2}(?:\.\d{1,2})?\b|изузев|из узев|\bи\b|[,;]|\s)+)$")


def iso(match: re.Match) -> str:
    return date(int(match[3]), int(match[2]), int(match[1])).isoformat()


def read_text(pdf: Path) -> str:
    pages = [p.extract_text() for p in pypdf.PdfReader(pdf).pages]
    # 2-05-009 is the same scope printed twice; keep the first copy.
    half = len(pages) // 2
    if len(pages) % 2 == 0 and pages[:half] == pages[half:]:
        pages = pages[:half]
    text = "\n".join(pages)
    # SIQ Ljubljana's scope is written in Latin script; read everything in one script.
    return text if re.search("[А-Яа-я]", text) else cyrillic(text)


def cyrillic(text: str) -> str:
    for word, cyr in [("Referentni standard", "Референтни стандард"), ("Napomena", "Напомена"),
                      ("Akreditovano telo", "Акредитованo тело"), ("Standard / Standard", "Стандард / Standard"),
                      ("Datum prve akreditacije", "Датум прве акредитације")]:
        text = text.replace(word, cyr)
    return text


def norm_nace(text: str) -> str:
    text = text.replace("из узев", "изузев").replace("изузев", " except ")
    text = re.sub(r"\s+и\s+", ",", text)
    text = re.sub(r"\s*[,;]\s*", ",", text)
    text = re.sub(r"\s*except\s*", " except ", text)
    return re.sub(r"\s+", ",", text.strip(" ,")).replace(",except,", " except ")


def ea_rows(section: str) -> list[tuple[int, str]]:
    """(EA code, NACE list) per row of an IAF ID 1 table."""
    rows: list[list] = []
    open_row = False
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("Напомена") or line.startswith("*Напомена"):
            break
        if line.startswith("=== PAGE"):
            open_row = False  # rows do not cross pages; skip the page header and footer
            continue
        # A row starts with its EA number; "25 изузев 25.4" continues EA 17's NACE list.
        row = re.match(r"(?:ЕА|EA)?\s*(\d{1,2})\s+(?!из\s?узев)(?=[^\d\s.,])", line)
        if row and 1 <= int(row[1]) <= 39:
            rows.append([int(row[1]), ""])
            line = line[row.end():]
            open_row = True
        if open_row:
            tail = NACE_TAIL.search(line)
            if tail and re.search(r"\d", tail[1]):
                rows[-1][1] += " " + tail[1]
    return [(ea, norm_nace(nace)) for ea, nace in rows]


def compress(codes: list[int]) -> str:
    codes = sorted(set(codes))
    out, i = [], 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1:
            j += 1
        out.append(str(codes[i]) if i == j else f"{codes[i]}-{codes[j]}")
        i = j + 1
    return ";".join(out)


def expand(spec: str) -> list[int]:
    return [int(c) for c in spec.split(";")]


def parse(pdf: Path, review: list[str]) -> dict:
    text = read_text(pdf)
    head = text.split("Референтни стандард")[0]
    number = re.search(r"Accreditation No\.?:?\s*(08-\d{3})", text)[1]
    initial = re.search(r"Date of initial accreditation:\s*" + DATE, text)
    expiry = re.search(r"Accreditation expiry date:?\s*" + DATE, text)
    body = re.search(r"assessment body\s*\n(.*?)\n\s*Стандард", head, re.S)[1]
    lines = [l.strip() for l in body.splitlines() if l.strip(" ,")]
    country = "Serbia"
    if lines[-1] == "Slovenija":
        country, lines = "Slovenia", lines[:-1]
    name, address = " ".join(lines[:-1]).rstrip(" ,"), lines[-1].rstrip(" ,")
    if name.startswith("Друштво за сертификацију система менаџмента"):
        name = name.removeprefix("Друштво за сертификацију система менаџмента").strip()
    out = {"file": pdf.stem, "number": number, "name": latin(name), "address": latin(address),
           "country": country, "issue": iso(initial), "expiry": iso(expiry), "scopes": []}

    sections = text.split("Референтни стандард")[1:]
    merged: dict[str, str] = {}
    for section in sections:
        ref = section.split("\n")[0].replace(" ", "")
        scheme = next((s for s in SCHEMES if s[0].replace(" ", "") in ref), None)
        if scheme is None:
            review.append(f"{pdf.stem}: unknown reference standard '{section.splitlines()[0]}'")
            continue
        merged[scheme[0]] = merged.get(scheme[0], "") + "\n=== PAGE\n" + section.split("\n", 1)[1]

    for key, section in merged.items():
        _, cert_std, acc_std, suffix = next(s for s in SCHEMES if s[0] == key)
        if cert_std in ("ISO 9001", "ISO 14001", "ISO 45001"):
            rows = ea_rows(section)
            limited = [f"EA {ea} (NACE {nace})" for ea, nace in rows if nace != IAF_NACE[ea]]
            for ea, nace in rows:
                if nace != IAF_NACE[ea]:
                    review.append(f"{pdf.stem} {cert_std}: EA {ea} NACE '{nace}' != IAF '{IAF_NACE[ea]}'")
            ea_spec = compress([ea for ea, _ in rows])
            note = "Limited scope (part of the sector) for " + "; ".join(limited) if limited else ""
        elif cert_std == "ISO 22000":
            table = section.split("Напомена")[0]
            # Category letters are sometimes typed in Cyrillic (С for C).
            found = re.findall(r"(?:^|\s)([A-KАВСЕНК])\s+(?=[А-Яа-я])", table, re.M)
            cats = sorted({c.translate(str.maketrans("АВСЕНК", "ABCEHK")) for c in found})
            ea_spec = compress([c for cat in cats for c in expand(FOOD_CATEGORIES[cat])])
            note = f"ISO 22003-1 categories {', '.join(cats)} (classified to EA by sector)"
        elif cert_std == "ISO 13485":
            areas = [" ".join(m.lower().replace("-", " ").split())
                     for m in re.findall(r"^\s*\d\.\s+(.+\n.+)", section, re.M)]
            held = []
            for label, prefix, eas in MEDICAL_AREAS:
                if any(a.replace("aктивна", "активна").startswith(prefix) for a in areas):
                    held.append((label, eas))
            if len(held) != len(areas):
                review.append(f"{pdf.stem} ISO 13485: areas {areas} matched {held}")
            ea_spec = compress([c for _, eas in held for c in expand(eas)])
            note = ("ISO 13485 main technical areas: " + "; ".join(l for l, _ in held)
                    + " (classified to EA by sector)")
        else:
            if re.search(r"^\s*(?:ЕА\s*)?\d{1,2}\s+[А-Я]", section.split("Напомена")[0], re.M):
                review.append(f"{pdf.stem} {cert_std}: has a sector table, recorded as ALL")
            ea_spec, note = "ALL", ALL_NOTE
        if not ea_spec:
            review.append(f"{pdf.stem} {cert_std}: no sectors read")
            continue
        out["scopes"].append((number + suffix, acc_std, cert_std, ea_spec, note))
    return out


REGISTER_URL = "http://www.registar.ats.rs"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["јануар", "фебруар", "март", "април", "мај", "јун", "јул", "август", "септембар",
     "октобар", "новембар", "децембар"])}


def register_date(text: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})\.?", text.strip())
    return date(int(m[3]), MONTHS[m[2]], int(m[1])).isoformat() if m else None


def phone(text: str, country: str) -> str:
    """First number of the field in international form: '+38111 3628188, 362 8189' ->
    '+381 11 3628188'; Slovenian '+386 01 ...' drops the trunk 0."""
    first = re.split(r"[,;]", text)[0].strip()
    m = re.fullmatch(r"\+(381|386)\s*0?(\d{1,2})[\s-]*(.+)", first)
    if m and (m[1] == "381" or country == "Slovenia"):
        return f"+{m[1]} {m[2]} {m[3]}".replace("-", " ")
    m = re.fullmatch(r"0(\d{2})[\s/-]*(.+)", first)  # national form, e.g. 069-710-953
    if m and country == "Serbia":
        return f"+381 {m[1]} {m[2]}".replace("-", " ")
    return first


def read_register(path: Path) -> dict[str, dict]:
    """The ATS register search page saved as HTML, keyed by accreditation number."""
    import html
    text = path.read_text(encoding="utf-8")
    out = {}
    for item in text.split('<div class="item">')[1:]:
        link = re.search(r'href="(/predmet/\d+/)"', item)[1]
        fields = {html.unescape(k).strip(" :"): html.unescape(re.sub(r"<[^>]+>", "", v)).strip()
                  for k, v in re.findall(r"<th>(.*?)</th><td[^>]*>(.*?)</td>", item, re.S)}
        # The body's own table comes first; the contact person's phone/email follow.
        phones = re.findall(r"<th>Телефон:</th><td[^>]*>(.*?)</td>", item)
        note = re.search(r'class="napomena".*?<p>(.*?)</p>', item, re.S)
        out[fields["Акр. број"]] = {
            "url": REGISTER_URL + link, "pib": fields.get("ПИБ", ""), "web": fields.get("Web", ""),
            "phone": re.search(r"<th>Тел:</th><td[^>]*>(.*?)</td>", item)[1].strip() or
                     (phones[0].strip() if phones else ""),
            "email": fields.get("Е-маил", ""), "status": fields.get("Статус акр.", ""),
            "suspended": fields.get("Статус суспензије", ""),
            "initial": register_date(fields.get("Датум прве акр.", "")),
            "expiry": register_date(fields.get("Датум истицања/укидања акр.", "")),
            "note": html.unescape(re.sub(r"<[^>]+>", "", note[1])).strip() if note else "",
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--register", type=Path, default=HERE / "ats_register.html",
                        help="ATS register search page (17021-1 bodies) saved as HTML")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    review: list[str] = []
    bodies = [parse(pdf, review) for pdf in sorted(HERE.glob("2-05-*.pdf"))]
    register = read_register(args.register) if args.register.exists() else {}
    for b in bodies:
        r = register.get(b["number"])
        if r is None:
            review.append(f"{b['number']} {b['name']}: not in the register")
            b.update(url="https://www.ats.rs", pib="", phone="", email="", web="", status="ACTIVE")
            continue
        status = "ACTIVE"
        if r["status"] != "Акредитован":
            status = "WITHDRAWN"
        elif r["suspended"] not in ("Без суспензије", ""):
            status = "SUSPENDED"
        # The register carries extensions the PDFs predate, so its expiry date wins. Its
        # initial dates are sometimes a day later than the signed PDF; the PDF is kept.
        if r["expiry"] and r["expiry"] != b["expiry"]:
            review.append(f"{b['number']}: expiry {b['expiry']} (PDF) -> {r['expiry']} (register)")
            b["expiry"] = r["expiry"]
        if r["initial"] and r["initial"] != b["issue"]:
            review.append(f"{b['number']}: initial accreditation {b['issue']} (PDF, kept), {r['initial']} (register)")
        if r["note"]:
            review.append(f"{b['number']} register note: {r['note']}")
        b.update(url=r["url"], pib=r["pib"], phone=phone(r["phone"], b["country"]), email=r["email"],
                 web=r["web"].rstrip("/") if r["web"] else "", status=status)

    args.out.mkdir(parents=True, exist_ok=True)

    with open(args.out / "bodies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name", "country", "registration_no", "phone", "email", "website", "address",
                    "source_url", "verified_at"])
        for b in bodies:
            w.writerow([b["name"], b["country"], b["pib"], b["phone"], b["email"], b["web"], b["address"],
                        b["url"], ""])

    with open(args.out / "accreditations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                    "issue_date", "expiry_date", "proof_url"])
        for b in bodies:
            # Every ATS certificate is a 17021-1 accreditation, even when its only scheme
            # is ISO/IEC 27001 (SIQ Ljubljana); search needs that base row.
            seen = {b["number"]: "ISO/IEC 17021-1"}
            for cert, acc_std, *_ in b["scopes"]:
                seen.setdefault(cert, acc_std)
            for cert, acc_std in seen.items():
                w.writerow(["ATS", cert, b["name"], acc_std, b["status"], b["issue"], b["expiry"], b["url"]])

    with open(args.out / "scopes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"])
        for b in bodies:
            for cert, _, cert_std, ea_spec, note in b["scopes"]:
                w.writerow([cert, cert_std, ea_spec, "ACTIVE", note])

    for b in bodies:
        print(f"{b['file']} {b['number']} {b['country']:8} {b['status']} {b['issue']} {b['expiry']} {b['name']} | "
              f"{b['address']} | {b['pib']} | {b['phone']} | {b['email']} | {b['web']}")
        for s in b["scopes"]:
            print("   ", s)
    print("\nREVIEW:\n" + "\n".join(review))


if __name__ == "__main__":
    main()
