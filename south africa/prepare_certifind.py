"""SANAS (South Africa) -> CertiFind CSVs.

Usage: python prepare_certifind.py <scrape dir> <dataset dir> [--today YYYY-MM-DD]
Reads <scrape>/sanas_raw.txt (see database/south-africa/scrape_za_sanas.py for the format).
One accreditation row per body + accreditation standard (facilities of one body merged into the
lowest facility number); one scope row per certification standard (codes of all facilities combined).
"""
import csv, importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
esyd = importlib.util.module_from_spec(spec); spec.loader.exec_module(esyd)
ea_spec, expand, FOOD, MED = esyd.ea_spec, esyd.expand, esyd.FOOD_CATEGORIES, esyd.MEDICAL_AREAS

AB = "SANAS"
SRC = "https://www.sanas.co.za/Pages/index.aspx"
PDF = "https://www.sanas.co.za/Certificate%20Published/{}.pdf"
SCHEME = {"9001": "ISO 9001", "14001": "ISO 14001", "45001": "ISO 45001", "3834": "ISO 3834",
          "22000": "ISO 22000", "F": "FSSC 22000", "I27001": "ISO/IEC 27001", "13485": "ISO 13485",
          "50001": "ISO 50001"}
ROWS = {"ISO 22000": ("ISO 22003-1", "22000"), "FSSC 22000": ("ISO 22003-1", "22000"),
        "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO 50001": ("ISO 50003", "50003")}
ALL = "1-39"

# canonical name -> raw body idxs. Two bodies reuse rows from other datasets exactly.
CANON = [
    ("i-Cert (Pty) Ltd", [0]), ("SGS South Africa (Pty) Ltd", [1]),
    ("TUV Rheinland Inspection Services (Pty) Ltd", [2, 41]), ("Alpha Certification Services CC", [3, 15]),
    ("Southern African Institute of Welding NPC", [4]),
    ("Environmental Quality Certification Services Africa (Pty) Ltd", [5, 6, 29]),
    ("SABS Commercial SOC Ltd.", [7, 9, 14]),
    ("South African Certification and Auditing Services (Pty) Ltd", [8, 10, 11, 12, 22]),
    ("Sheq National Cert International (PTY) LTD", [13]), ("African Certification and Testing (Pty) Ltd", [16]),
    ("Uganda National Bureau of Standards", [17]), ("Judah Compliance Auditors CC", [18]),
    ("BSI Group South Africa (Pty) Ltd", [19, 20]), ("Isoqar Africa (Pty) Ltd", [21]),
    ("AfriCert (Pty) Ltd", [23]), ("South African Compliance and Certification (Pty) Ltd", [24, 25]),
    ("Sancert (Pty) Ltd", [26]),
    ("Industry Compliance and Certification Authority of South Africa (Pty) Ltd", [27]),
    ("Certification and Training Services for Africa (Pty) Ltd", [28, 37]),
    ("NST Total Compliance (Pty) Ltd", [30]), ("Wynleigh International Certification Services (Pty) Ltd", [31]),
    ("Southern Africa Conformity Assessment Authority (Pty) Ltd", [32, 38]), ("CertX SA (Pty) Ltd", [33]),
    ("CMA Certification Services (Pty) Ltd", [34]),
    ("Institute of Bio Research Auditing and Training in Southern Africa (Pty) Ltd", [35]),
    ("General Food Safety Company (Pty) Ltd", [36]), ("DQS (Pty) Ltd", [39]), ("MI Cert Africa (Pty) Ltd", [40]),
    ("UbiCerts (Pty) Ltd", [42]), ("ISO Global Certification (Pty) Ltd", [43, 44]),
    ("Certification Partner Global FZ LLC", [45]), ("ESSH", [46]),
]
IDX = {i: n for n, ids in CANON for i in ids}
REUSE = {  # exact rows from other datasets
    "SABS Commercial SOC Ltd.": ("rva-netherlands", "SABS Commercial SOC Ltd."),
    "Sheq National Cert International (PTY) LTD": ("eiac-uae", "Sheq National Cert International (PTY) LTD"),
}
NON_ZA = {"Uganda": ("Uganda", "256")}
BCOLS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACOLS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
         "expiry_date", "proof_url"]
SCOLS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]


def phone(raw, cc, review, name):
    first = re.split(r"/", raw)[0]
    d = re.sub(r"\D", "", first.replace("(0)", ""))
    if not d:
        return ""
    if d.startswith(cc):
        d = d[len(cc):]
    elif cc == "27" and d.startswith("0") and len(d) == 10:
        d = d[1:]
    elif cc == "256" and d.startswith("25"):  # "25-641-733-3250" = +256 41 7333250
        d = d[3:]
    if cc == "27" and len(d) == 9:
        return f"+27 {d[:2]} {d[2:5]} {d[5:]}"
    if cc == "256" and len(d) == 9:
        return f"+256 {d[:2]} {d[2:]}"
    review.append(f"- {name}: phone '{raw}' could not be normalised; left empty")
    return ""


def md_ea(areas):
    ea = set()
    for a in areas:
        a = re.sub(r"^[A-Z]?\d[\d.]*\s*", "", a).lower()
        for _, keys, spec_ in MED:
            if any(a.startswith(k) for k in keys):
                ea |= expand(spec_); break
    return ea


def main():
    scrape, out = Path(sys.argv[1]), Path(sys.argv[2])
    today = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else ""
    raw = (scrape / "sanas_raw.txt").read_text(encoding="utf-8").split("\n#\n")
    certs = [[x.strip() for x in l.split("|")] for l in raw[0].strip().splitlines()]
    binfo = {int(r[0]): r for r in (l.split("|") for l in raw[1].strip().splitlines())}
    review = [f"# SANAS review ({today})", "", "## Converter notes"]
    others = {}
    for f in (out.parent).glob("*/bodies.csv"):
        for r in csv.DictReader(f.open(encoding="utf-8")):
            others[(f.parent.name, r["name"])] = r

    # group facilities per body
    per = {}
    for c in certs:
        per.setdefault(IDX[int(c[1])], []).append(c)
    num = lambda f: (int(re.match(r"C(\d+)", f).group(1)), f)

    bodies, accs, scopes = [], [], []
    for name, cs in per.items():
        cs.sort(key=lambda c: num(c[0]))
        stds = {SCHEME[c[4]] for c in cs}
        if not stds - set(ROWS):
            review.append(f"- Dropped {name}: only {', '.join(sorted(stds))}, no ISO/IEC 17021-1 scheme "
                          f"({', '.join(c[0] for c in cs)})")
            continue
        r = binfo[int(cs[0][1])]
        if name in REUSE:
            row = dict(others[REUSE[name]])
            review.append(f"- {name}: reuses body row from {REUSE[name][0]}")
        else:
            country, cc = NON_ZA.get(r[5], ("South Africa", "27"))
            pc = r[4] if re.fullmatch(r"\d{4}", r[4] or "") else ""
            city = r[3].strip().title() if r[3].isupper() else r[3].strip()
            addr = ", ".join(x for x in [re.sub(r"\s+", " ", r[2].strip()), f"{pc} {city}".strip()] if x)
            row = dict(name=name, country=country, registration_no="", phone=phone(r[6], cc, review, name),
                       email=r[7].strip(), website="", address=addr, source_url=SRC, verified_at="")
        base = cs[0][0]
        if name not in REUSE:
            row["registration_no"] = base
        bodies.append(row)

        grouped = {}  # acc std -> {cert std -> [facilities]}
        for c in cs:
            std = SCHEME[c[4]]
            acc = ROWS.get(std, ("ISO/IEC 17021-1", ""))
            grouped.setdefault(acc, {}).setdefault(std, []).append(c)
        for (acc_std, suf), by_std in grouped.items():
            facs = [c for l in by_std.values() for c in l]
            cert = f"{base} ({suf})" if suf else base
            first = min(facs, key=lambda c: num(c[0]))
            accs.append(dict(ab_code=AB, certificate_number=cert, body_name=row["name"], accreditation_standard=acc_std,
                             status="ACTIVE", issue_date=min(c[2] for c in facs),
                             expiry_date=max(c[3] for c in facs), proof_url=PDF.format(first[8].replace(" ", "%20"))))
            for std, fl in by_std.items():
                codes, notes = set(), []
                for _, _, _, _, _, ea, cats, md, _ in fl:
                    if ea:
                        codes |= expand(ea)
                    elif cats:
                        codes |= {e for k in cats for e in expand(FOOD[k])}
                        notes.append(f"ISO 22003-1 categories {', '.join(cats)} classified to EA")
                    elif md:
                        codes |= md_ea(md.split(";"))
                        notes.append(f"IAF MD 8 technical areas classified to EA ({md})")
                if not codes:
                    codes = expand(ALL)
                    notes = [f"No sector list in the SANAS register; recorded for all EA sectors"]
                fn = ", ".join(c[0] for c in fl)
                if len(fl) > 1:
                    notes.append(f"Merged SANAS facilities {fn}")
                    review.append(f"- {row['name']}: {std} facilities {fn} merged into {cert}")
                elif fl[0][0] != base:
                    notes.append(f"SANAS facility {fn}")
                scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea_spec(codes),
                                   status="ACTIVE", scope_note="; ".join(notes)))

    regs = {}
    for b in bodies:
        if b["registration_no"] in regs and b["name"] not in REUSE:
            review.append(f"- {b['name']}: registration_no {b['registration_no']} already used by "
                          f"{regs[b['registration_no']]}; left empty")
            b["registration_no"] = ""
        regs.setdefault(b["registration_no"], b["name"])
    names = [b["name"] for b in bodies]
    assert len(names) == len(set(names)), "duplicate body names"
    out.mkdir(parents=True, exist_ok=True)
    for fn, cols, rows in (("bodies.csv", BCOLS, bodies), ("accreditations.csv", ACOLS, accs),
                           ("scopes.csv", SCOLS, scopes)):
        with (out / fn).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    old = scrape / "sanas_review.md"
    skipped = old.read_text(encoding="utf-8").split("\n", 2)[2] if old.exists() else ""
    (HERE / "sanas_review.md").write_text("\n".join(review) + "\n\n## From the scrape\n" + skipped, encoding="utf-8")
    print(f"Bodies: {len(bodies)}  Accreditations: {len(accs)}  Scopes: {len(scopes)}")


if __name__ == "__main__":
    main()
