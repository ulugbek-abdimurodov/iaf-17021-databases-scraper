"""Convert the INN (Chile) register scrape + certificate PDFs into CertiFind CSVs.

Usage: python prepare_certifind.py <scrape dir> <dataset dir> [--today YYYY-MM-DD] [--debug CODE ...]

<scrape dir> holds inn_raw.tsv (register rows) and pdf/<CODE>.pdf (certificate + annex, downloaded
from https://directorio.inn.cl/Directorio/DisplayPDF/<token>).
INN issues one registration per scheme (SC quality, SGA environment, SGR OHS, SGC ISMS, SGE energy).
All 17021-1 schemes of a body are merged under its first registration; 27001 and 50001 get their
own suffixed rows. Annex sectors are IAF numbers (9001/14001/45001/27001) or ISO 50003 areas (50001).
"""
import argparse, csv, datetime, importlib.util, re, sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand, ENERGY = esyd.ea_spec, esyd.expand, esyd.ENERGY_AREAS

AB = "INN"
REGISTER = "https://directorio.inn.cl/"
PDF_URL = "https://directorio.inn.cl/Directorio/DisplayPDF/"
STANDARDS = {"ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001:2018": "ISO 45001",
             "NCh-ISO IEC 27001:2023": "ISO/IEC 27001", "ISO 50001": "ISO 50001"}
SKIPPED = {"HACCP": "HACCP (not in standards table)",
           "NCh2728:2015": "NCh 2728 training-provider standard (Chilean national scheme)",
           "CERTFOR-Chile": "CERTFOR-Chile forestry (Chilean national scheme)",
           "NCh3262-2021": "NCh 3262 gender equality / work-life (Chilean national scheme)"}
SCHEME_ROWS = {"ISO/IEC 27001": ("ISO/IEC 27006", "(27006)"), "ISO 50001": ("ISO 50003", "(50003)")}
NAMES = {"SGS CHILE LTDA.": "SGS Chile Ltda.", "Bureau Veritas Certification Chile S.A": "Bureau Veritas Certification Chile S.A.",
         "Lgai Chile S.A": "LGAI Chile S.A.", "SCI CERTIFICACIONES LIMITADA": "SCI Certificaciones Limitada",
         "ASR CERTIFICACIONES LIMITADA": "ASR Certificaciones Limitada"}
# Same legal entity already in another dataset -> reuse that body row exactly
REUSE = {"AENOR CONFIA S.A.U.": ("enac-spain", "AENOR CONFÍA, S.A. (Unipersonal)")}
# ISO 50003 areas as written in INN annexes (Spanish) -> ESYD letter
ENERGY_ES = [("A", "industria ligera"), ("B", "industria pesada"), ("D", "complejos de edificios"),
             ("C", "edificios"), ("E", "transporte"), ("F", "miner"), ("G", "agricultura"), ("H", "suministro")]
COLS = {
    "bodies.csv": ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"],
    "accreditations.csv": ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"],
    "scopes.csv": ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"],
}


def iso(d):
    dd, mm, yy = d.split("-")
    return f"{yy}-{mm}-{dd}"


def phone(raw, review, name):
    d = re.sub(r"\D", "", raw)
    if d.startswith("56"):
        d = d[2:]
    if len(d) == 8 and d[0] == "2":  # pre-2013 Santiago number: 2 + 7 digits -> 22 + 7 digits
        review.append(f"{name}: old Santiago phone {raw!r} converted to the 9-digit format (22...)")
        d = "2" + d
    if len(d) == 8 and d[0] == "9":
        d = "9" + d
    if len(d) != 9:
        review.append(f"{name}: phone {raw!r} not convertible, left empty")
        return ""
    if d[0] in "29":
        return f"+56 {d[0]} {d[1:5]} {d[5:]}"
    return f"+56 {d[:2]} {d[2:5]} {d[5:]}"


def parse_pdf(path):
    lines = [l.strip() for p in pymupdf.open(path) for l in p.get_text().splitlines()]
    text = "\n".join(lines)
    m = re.search(r"ubicad[oa] en (.+?)\n\s*\n?\s*ha ", text, re.S)
    address = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    start = next(i for i, l in enumerate(lines) if l.upper().startswith("ALCANCE"))
    start = next(i for i, l in enumerate(lines) if i > start and l.startswith("Sector"))
    end = next((i for i, l in enumerate(lines) if i > start and l.startswith("Creado el")), len(lines))
    body = [l for l in lines[start + 1:end] if l]
    nums, areas = set(), set()
    for i, l in enumerate(body):
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if re.fullmatch(r"\d{1,2}", l) and re.match(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", nxt):
            n = int(l)
            if 1 <= n <= 39:
                nums.add(n)
            low = nxt.lower()
            for letter, key in ENERGY_ES:
                if low.startswith(key):
                    areas.add(letter)
                    break
    return address, nums, areas, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    review, skipped = [], []
    bodies, A, S, first = {}, [], [], {}
    for row in csv.reader(open(a.scrape / "inn_raw.tsv", encoding="utf-8"), delimiter="\t"):
        code, name, commune, scheme, tel, issue, expiry, state, token = row
        name = NAMES.get(name, name)
        if scheme in SKIPPED:
            skipped.append(f"| {code} | {name} | {scheme} | {SKIPPED[scheme]} |")
            continue
        std = STANDARDS[scheme]
        if state != "Vigente" or iso(expiry) < a.today:
            skipped.append(f"| {code} | {name} | {scheme} | {state}, expires {iso(expiry)} |")
            continue
        address, nums, areas, body = parse_pdf(a.scrape / "pdf" / (code.replace(" ", "") + ".pdf"))
        if code.replace(" ", "") in a.debug:
            print(code, address, sorted(nums), sorted(areas), "\n".join(body), sep="\n")
        if name not in bodies:
            bodies[name] = dict(name=name, country="Chile", registration_no=code, phone=phone(tel, review, name),
                                email="", website="", address=address or f"{commune}, Chile",
                                source_url=REGISTER, verified_at="")
            if name in REUSE:
                ds, alias = REUSE[name]
                rows = csv.DictReader(open(HERE.parent.parent / "certifind" / "data" / ds / "bodies.csv", encoding="utf-8"))
                bodies[name] = next(r for r in rows if r["name"] == alias)
                review.append(f"{name}: same entity as {alias} ({ds}, Madrid address in INN certificate); body row reused")
            first[name] = (code, token, iso(issue), iso(expiry))
        acc, suf = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", ""))
        base, btok, bissue, bexp = first[name] if not suf else (code, token, iso(issue), iso(expiry))
        cert = f"{base} {suf}".strip()
        if not any(r["certificate_number"] == cert for r in A):
            A.append(dict(ab_code=AB, certificate_number=cert, body_name=bodies[name]["name"], accreditation_standard=acc,
                          status="ACTIVE", issue_date=bissue, expiry_date=bexp, proof_url=PDF_URL + btok))
        note = f"INN registration {code}"
        if std == "ISO 50001":
            ea = set().union(*(expand(next(s for l, _, s in ENERGY if l == x)) for x in areas))
            note += "; ISO 50003 areas " + ", ".join(sorted(areas)) + " (classified to EA by sector)"
        else:
            ea = nums
        if not ea:
            review.append(f"{code} {name}: no sectors parsed from annex")
        S.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea_spec(ea),
                      status="ACTIVE", scope_note=note))
        review.append(f"{code} {name} {std}: {ea_spec(ea)}")
    # body with no 17021-1 row would be unsearchable
    for n in bodies:
        if not any(r["body_name"] == bodies[n]["name"] and r["accreditation_standard"] == "ISO/IEC 17021-1" for r in A):
            review.append(f"WARNING {n}: no ISO/IEC 17021-1 row")
    a.out.mkdir(parents=True, exist_ok=True)
    for fn, data in zip(COLS, (list(bodies.values()), A, S)):
        with open(a.out / fn, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLS[fn]); w.writeheader(); w.writerows(data)
    with open(HERE / "inn_review.md", "w", encoding="utf-8") as f:
        f.write(f"# INN conversion review ({a.today})\n\n## Skipped registrations\n\n| Code | Body | Scheme | Reason |\n|---|---|---|---|\n")
        f.write("\n".join(skipped) + "\n\n## Notes and parsed sectors\n\n")
        f.writelines(f"- {l}\n" for l in review)
    print(f"bodies {len(bodies)}, accreditations {len(A)}, scopes {len(S)}")


if __name__ == "__main__":
    main()
