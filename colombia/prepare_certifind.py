"""Convert the ONAC (Colombia) register snapshot into a CertiFind dataset.

usage: python prepare_certifind.py <onac_raw.tsv> <dataset dir> [--today YYYY-MM-DD] [--debug CODE ...]
"""
import argparse
import csv
import datetime as dt
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand, FOOD_CATEGORIES = esyd.ea_spec, esyd.expand, esyd.FOOD_CATEGORIES

AB = "ONAC"
SRC = "https://onac.org.co/directorio-de-acreditados/"
BASE = "ISO/IEC 17021-1"
SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"),
    "ISO 22000": ("ISO 22003-1", "22000"), "FSSC 22000": ("ISO 22003-1", "22000"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"), "ISO/IEC 42001": ("ISO/IEC 42006", "42001"),
    "ISO 22301": ("ISO/IEC 17021-6", "22301"), "ISO 37001": ("ISO/IEC 17021-9", "37001"),
    "ISO 55001": ("ISO/IEC 17021-5", "55001"), "ISO 39001": ("ISO/IEC 17021-7", "39001"),
    "AS 9100": ("AS 9104-1", "9104"),
}
UNDER_BASE = {"ISO 9001", "ISO 14001", "ISO 45001", "ISO 18788", "ISO 28000", "ISO 28001"}
NATIONAL = {"NTC 5555": "Colombian national scheme (training institutions)",
            "NTC 6001": "Colombian national scheme (micro and small enterprises)"}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
CITY_PREFIX = {"Bogotá": "601", "Cali": "602", "Medellín": "604"}


def phone(raw, country, city, review):
    s = re.split(r"(?i)\s*ext", raw)[0]
    d = re.sub(r"\D", "", s)
    if country == "India" and d.startswith("91") and len(d) == 12:
        return f"+91 {d[2:7]} {d[7:]}"
    if country == "Venezuela" and d.startswith("58") and len(d) == 12:
        return f"+58 {d[2:5]} {d[5:8]} {d[8:]}"
    if country != "Colombia":
        if s.strip().startswith("+1") and len(d) == 11:
            review.append(f"phone {raw} is a US/Canada number for a body in {country}; kept")
            return f"+1 {d[1:4]} {d[4:7]} {d[7:]}"
        review.append(f"phone {raw!r} could not be normalised; left empty")
        return ""
    if d.startswith("57") and len(d) == 12:
        d = d[2:]
    d = d.lstrip("0")
    if len(d) == 10 and d.startswith("571"):  # (571) = old country 57 + Bogotá 1
        d = "601" + d[3:]
    elif len(d) == 9 and d.startswith("31"):  # (031) = old carrier 03 + Bogotá 1
        d = "601" + d[2:]
    if len(d) == 8 and d[0] in "1245678":  # pre-2021 area code + 7 digits
        d = "60" + d
    elif len(d) == 7:
        if city not in CITY_PREFIX:
            review.append(f"phone {raw!r}: unknown city {city!r}; left empty")
            return ""
        d = CITY_PREFIX[city] + d
    if len(d) == 10 and d[0] in "36":
        return f"+57 {d[:3]} {d[3:6]} {d[6:]}"
    review.append(f"phone {raw!r} could not be normalised; left empty")
    return ""


def iaf(val):
    if val == "ALL":
        return set(range(1, 40))
    return set().union(*(expand(p) for p in val.split(",") if p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape")
    ap.add_argument("dataset")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    out = Path(a.dataset)
    out.mkdir(parents=True, exist_ok=True)

    bodies, accs, scopes, review = [], [], [], []
    names = set()
    for r in csv.DictReader(open(a.scrape, encoding="utf-8"), delimiter="\t"):
        code, name = r["code"], r["name"].strip()
        notes = []
        if r["expiry"] and r["expiry"] < a.today:
            review.append(f"| {code} | {name} | expired {r['expiry']} | body dropped |")
            continue
        rows = {}  # acc standard -> (cert, [scope rows])
        skipped = []
        for item in r["scopes"].split("|"):
            std, _, val = item.partition(":")
            std = std.strip()
            if std in NATIONAL:
                skipped.append(f"{std} ({NATIONAL[std]})")
                continue
            if std in SCHEME_ROWS:
                acc, suf = SCHEME_ROWS[std]
                cert = f"{code} ({suf})"
            elif std in UNDER_BASE:
                acc, cert = BASE, code
            else:
                skipped.append(f"{std} (not in standards table)")
                continue
            if std in IAF_STANDARDS and val:
                ea, note = ea_spec(iaf(val)), "IAF codes as listed in the ONAC scope certificate"
            elif std in ("ISO 22000", "FSSC 22000") and val:
                cats = val.split(",")
                ea = ea_spec(set().union(*(expand(FOOD_CATEGORIES[c]) for c in cats)))
                note = f"ISO 22003-1 categories {', '.join(cats)} classified to EA"
            else:
                ea, note = "1-39", "No sector list in the ONAC register; recorded for all EA sectors"
            rows.setdefault(acc, (cert, []))[1].append((std, ea, note))
        if skipped:
            review.append(f"| {code} | {name} | skipped: {'; '.join(skipped)} | |")
        if not rows:
            review.append(f"| {code} | {name} | nothing importable | body dropped |")
            continue
        if BASE not in rows:  # search needs a 17021-1 row
            rows[BASE] = (code, [])
            notes.append("17021-1 row added without scopes")
        if name in names:
            raise SystemExit(f"duplicate body name {name}")
        names.add(name)
        tel = phone(r["phone"], r["country"], r["city"], notes)
        for n in notes:
            review.append(f"| {code} | {name} | {n} | |")
        bodies.append(dict(name=name, country=r["country"], registration_no=code, phone=tel,
                           email=r["email"].strip().lower(), website=r["website"], address=r["address"],
                           source_url=SRC, verified_at=""))
        for acc in sorted(rows, key=lambda s: s != BASE):
            cert, sc = rows[acc]
            accs.append(dict(ab_code=AB, certificate_number=cert, body_name=name, accreditation_standard=acc,
                             status="ACTIVE", issue_date=r["issued"], expiry_date=r["expiry"],
                             proof_url=f"https://onac.org.co/certificados/{code}.pdf"))
            for std, ea, note in sc:
                scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea,
                                   status="ACTIVE", scope_note=note))
        if code in a.debug:
            print(code, rows)

    def write(fn, rows):
        with open(out / fn, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    write("bodies.csv", bodies)
    write("accreditations.csv", accs)
    write("scopes.csv", scopes)
    with open(HERE / "onac_review.md", "w", encoding="utf-8") as f:
        f.write("# ONAC review\n\n| Registration | Body | Note | Action |\n|---|---|---|---|\n")
        f.write("\n".join(review) + "\n")
    print(f"{len(bodies)} bodies, {len(accs)} accreditations, {len(scopes)} scopes")


if __name__ == "__main__":
    main()
