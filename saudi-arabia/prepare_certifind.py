#!/usr/bin/env python3
"""Convert the SAAC scrape (saac_raw.txt from scrape_sa_saac.py) into a CertiFind dataset.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug ID ...]

SAAC (Saudi Accreditation Center) numbers each registration per scheme (N-QMS-00001, N-FSMS-00035...).
Per body, all active registrations are merged: the first ISO/IEC 17021-1 scheme registration gives the
ISO/IEC 17021-1 row, schemes with their own accreditation standard get a suffixed row (SCHEME_ROWS).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand, FOOD, MEDICAL = esyd.ea_spec, esyd.expand, esyd.FOOD_CATEGORIES, esyd.MEDICAL_AREAS

AB_CODE = "SAAC"
BASE = "ISO/IEC 17021-1"
SRC = "https://saac.gov.sa/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Management+Systems+Certificates"
DETAIL = "https://saac.gov.sa/en/accredited-bodies/?appid={}"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]

SCHEMES = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001", "FSMS": "ISO 22000", "EnMS": "ISO 50001",
           "MDMS": "ISO 13485", "ISMS": "ISO/IEC 27001", "BCMS": "ISO 22301"}
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

# Register spellings of one company -> canonical body index; canonical names.
ALIAS = {10: 9, 35: 9, 13: 8, 19: 4, 48: 11, 25: 14, 39: 14, 28: 26, 44: 26, 40: 21,
         37: 22, 50: 38, 45: 1, 46: 1, 49: 1, 20: 32}
CANON_NAME = {1: "Arabian Certification Company for Business Services (ACC)",
              4: "SGS Inspection Services Saudi Arabia Ltd.",
              8: "Optimal Support Services Company for Verification and Conformity", 9: "QSI Cert Co",
              11: "Intertek Arabia Administrative Company", 14: "TUV Limited Co.",
              21: "Branch of TUV Austria Shanghai Co. Ltd",
              22: "National Inspection & Technical Testing Company Ltd. (FAHSS)",
              26: "Sustainable Management Group Co.", 38: "Pioneers of Quality Systems & Certifications Company",
              15: "ISO Cert International", 18: "Motan Al-Anzama Commercial (TCI Branch)"}
# SAAC name -> name of the same company in another dataset.
OTHER_NAMES = {"Pioneers of Quality Systems & Certifications Company": "Pioneers of Quality Systems and Certifications KSA"}
WEB_FIX = {"null": "", "www,iso-qms.org": "www.iso-qms.org", "www-qsi-cert.com": "www.qsi-cert.com"}


def iso_date(d: str) -> str:
    return datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d") if d else ""


def phone(raw: str, who: str, review: list[str]) -> str:
    d = re.sub(r"\D", "", raw)
    if d.startswith("00"):
        d = d.lstrip("0")
    elif d.startswith("0"):
        d = "966" + d[1:]
    elif len(d) == 9 and d[0] == "5":
        d = "966" + d
    if d.startswith("966") and len(d) == 12:
        n = d[3:]
        return f"+966 {n[:2]} {n[2:5]} {n[5:]}"
    if d.startswith("44") and len(d) == 12:
        return f"+44 {d[2:6]} {d[6:]}"
    if raw:
        review.append(f"{who}: phone '{raw}' is not a valid international number; left empty")
    return ""


def scope(std: str, f: list[str]) -> tuple[str, str]:
    iaf, fc, md, oth = f[6:10]
    if std in ("ISO 9001", "ISO 14001", "ISO 45001") and iaf:
        return ea_spec({int(x) for x in iaf.split(",") if x}), "IAF codes as listed in the SAAC register"
    if std == "ISO 22000":
        cats = set(fc) | {m.group(1) for m in re.finditer(r"(?:^|\|)([A-K]) ", oth)}
        if cats:
            codes = set().union(*(expand(FOOD[c]) for c in cats))
            return ea_spec(codes), f"Classified to EA from ISO 22003-1 categories {', '.join(sorted(cats))}"
    if std == "ISO 13485" and md:
        codes, names = set(), []
        for a in md.split("|"):
            for name, keys, spec in MEDICAL:
                if a.strip().lower().startswith(keys):
                    codes |= expand(spec)
                    names.append(name)
                    break
        if codes:
            return ea_spec(codes), f"Classified to EA from IAF MD 8 main technical areas: {'; '.join(names)}"
    return "1-39", "No sector list in the SAAC register; recorded for all EA sectors"


def write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", nargs="*", default=[])
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    raw = next(args.scrape.rglob("saac_raw.txt"))
    sec, B, C = None, {}, []
    for ln in raw.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            sec = ln[1:6]
            continue
        f = ln.split(";;")
        (B.__setitem__(int(f[0]), f[1:]) if sec == "BODIE" else C.append(f))

    review: list[str] = []
    bodies: dict[str, dict] = {}
    regs: dict[str, list] = {}
    for f in sorted(C, key=lambda x: datetime.strptime(x[4], "%m/%d/%Y")):
        cid, bi, status = f[0], ALIAS.get(int(f[1]), int(f[1])), f[3]
        name = CANON_NAME.get(bi, re.sub(r"\s+", " ", B[bi][0]).strip())
        if status != "Active":
            review.append(f"{cid} {name}: status {status}; not imported")
            continue
        if name not in bodies:
            email, ph, city, web = B[bi][1:5]
            web = WEB_FIX.get(web, web).lower().rstrip("/")
            bodies[name] = dict(name=name, country="Saudi Arabia", registration_no=cid,
                                phone=phone(ph, f"{cid} {name}", review), email=email,
                                website=f"https://{web}" if web else "", address=city.title(),
                                source_url=SRC, verified_at="")
        regs.setdefault(name, []).append(f)
        if cid in args.debug:
            print(cid, name, f)

    # Bodies already in another dataset: reuse that row.
    others = {}
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() != args.out.resolve():
            with open(path, encoding="utf-8-sig", newline="") as fh:
                others.update({(r["country"], r["name"]): (r, path.parent.name) for r in csv.DictReader(fh)})
    for name in list(bodies):
        key = ("Saudi Arabia", OTHER_NAMES.get(name, name))
        if key in others:
            other, ds = others[key]
            bodies.pop(name)
            bodies[key[1]] = {c: other[c] for c in BODY_COLUMNS}
            regs[key[1]] = regs.pop(name)
            review.append(f"{name}: already in {ds}; that dataset's body row is used")

    accs, scopes = [], []
    for name, fs in regs.items():
        rows: dict[str, dict] = {}
        base_f = next((f for f in fs if SCHEMES[f[0].split("-")[1]] not in SCHEME_ROWS), fs[0])
        for f in [base_f] + [f for f in fs if f is not base_f]:
            cid = f[0]
            std = SCHEMES[cid.split("-")[1]]
            acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
            if acc_std not in rows:
                number = (cid if acc_std == BASE else cid + suffix)
                rows[acc_std] = dict(ab_code=AB_CODE, certificate_number=number, body_name=name,
                                     accreditation_standard=acc_std, status="ACTIVE", issue_date=iso_date(f[4]),
                                     expiry_date=iso_date(f[5]), proof_url=DETAIL.format(cid.lower()))
            elif acc_std == BASE and cid != rows[BASE]["certificate_number"]:
                review.append(f"{cid} {name}: merged into {rows[BASE]['certificate_number']}")
            ea, note = scope(std, f)
            scopes.append(dict(certificate_number=rows[acc_std]["certificate_number"],
                               certification_standard=std, ea_codes=ea, status="ACTIVE", scope_note=note))
        if BASE not in rows:
            f = fs[0]
            rows[BASE] = dict(ab_code=AB_CODE, certificate_number=f[0], body_name=name, accreditation_standard=BASE,
                              status="ACTIVE", issue_date=iso_date(f[4]), expiry_date=iso_date(f[5]),
                              proof_url=DETAIL.format(f[0].lower()))
            review.append(f"{f[0]} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")
        accs.extend(rows.values())

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACC_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scopes, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(bodies), len(accs), len(scopes))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "saac_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# SAAC conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                 f"{counts[2]} scope rows before pruning.\n\nSkipped schemes: none (the 'Management Systems "
                 f"Certificates' service lists only ISO 9001, 14001, 45001, 22000, 50001, 13485, ISO/IEC 27001, "
                 f"ISO 22301).\n\n## Notes\n\n")
        fh.writelines(f"- {line}\n" for line in review)
        fh.write("\n## Removed by prune_inactive\n\n")
        fh.writelines(f"- {line}\n" for line in removed)
    print(f"Bodies {counts[0]}, accreditations {counts[1]}, scopes {counts[2]}; pruned {len(removed)}")


if __name__ == "__main__":
    main()
