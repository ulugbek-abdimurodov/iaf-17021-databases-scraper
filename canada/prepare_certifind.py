"""Convert the SCC (Standards Council of Canada) MSAP scrape into CertiFind CSVs + review log.

Usage: python prepare_certifind.py <scrape dir> <dataset dir> [--today YYYY-MM-DD] [--debug FILENO ...]

<scrape dir> holds scc_raw.tsv (register profiles, from scrape_ca_scc.py) and scc_txt/<file>.txt
(text of each Scope of Accreditation PDF, scc_pdfs/<file>.pdf, extracted with pdfplumber).

Standards and sectors come from the scope PDFs, not the register "specialty areas" (which miss
some programs, e.g. BNQ and Intercert EnMS). Each PDF section starts at "Base program: ... (CODE)".
"""
import argparse, csv, datetime, importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent / "certifind"


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand, ENERGY, MEDICAL = esyd.ea_spec, esyd.expand, esyd.ENERGY_AREAS, esyd.MEDICAL_AREAS
MED = {m[0]: m[2] for m in MEDICAL}

AB = "SCC"
BASE = "https://scc-ccn.ca"
ALL = "1-39"
SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "(27006)"), "ISO/IEC 27701": ("ISO/IEC 27006", "(27006)"),
    "ISO 50001": ("ISO 50003", "(50003)"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "(20000)"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "(42001)"), "ISO 22301": ("ISO/IEC 17021-6", "(22301)"),
    "ISO 37001": ("ISO/IEC 17021-9", "(37001)"), "ISO 55001": ("ISO/IEC 17021-5", "(55001)"),
    "ISO 39001": ("ISO/IEC 17021-7", "(39001)"), "AS 9100": ("AS 9104-1", "(9104)"),
}
# certification standard -> regex on the section text
STD_RX = [
    ("ISO 9001", r"ISO 9001"), ("ISO 14001", r"ISO 14001"), ("ISO 45001", r"ISO 45001"),
    ("ISO 13485", r"ISO 13485"), ("ISO/IEC 27001", r"ISO/IEC 27001"), ("ISO/IEC 27701", r"ISO/IEC 27701"),
    ("ISO 50001", r"ISO 50001"), ("ISO 22301", r"ISO 22301"), ("ISO/IEC 20000-1", r"ISO/IEC 20000-1\b"),
    ("ISO/IEC 42001", r"ISO/IEC 42001"), ("ISO 37001", r"ISO 37001"), ("AS 9100", r"AS ?9100"),
]
# schemes deliberately not imported (national / not in the standards table)
SKIP_RX = [
    ("CyberSecure Canada (CAN/CIOSC 104 / CAN/DGSI 104) - national scheme", r"CIOSC|DGSI"),
    ("PEFC Canada (PEFC CAN ST 1001) - national forestry scheme", r"PEFC CAN"),
    ("SFI 2022 forest management / fiber sourcing - North American forestry scheme", r"\bSFI\b"),
    ("ATFS (American Tree Farm System) - national forestry scheme", r"ATFS"),
    ("AS9120 - not in the standards table", r"AS ?9120"),
]
BASE_STD = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OH&SMS": "ISO 45001", "OHSMS": "ISO 45001",
            "MDMS": "ISO 13485", "ISMS": "ISO/IEC 27001", "PIMS": "ISO/IEC 27701", "EnMS": "ISO 50001",
            "BCMS": "ISO 22301", "ITSMS": "ISO/IEC 20000-1", "AIMS": "ISO/IEC 42001", "ABMS": "ISO 37001",
            "AQMS": "AS 9100"}
IAF_STD = {"ISO 9001", "ISO 14001", "ISO 45001"}
MED_RX = [  # SCC main technical areas -> ESYD MEDICAL_AREAS key
    (r"non-active medical", "Non-active medical devices"),
    (r"active \(non|general active medical", "Active (non-implantable) medical devices"),
    (r"active implantable", "Active implantable medical devices"),
    (r"in vitro diagnostic", "In vitro diagnostic medical devices"),
    (r"sterili[sz]ation method", "Sterilization methods"),
    (r"incorporating|utilizing specific", "Devices incorporating specific substances / technologies"),
    (r"parts and services", "Parts or services"),
]
CTRY = {"USA": "United States"}
DIAL = {"Canada": "1", "United States": "1", "China": "86", "Germany": "49", "India": "91",
        "United Arab Emirates": "971", "Taiwan": "886", "Ireland": "353"}
PHONE_FIX = {"8073": ("+91 97160 06477", "register and PDF give '+1 919716006477' / '+1-91-9716006477'; "
                                         "an Indian mobile in Noida, corrected to +91")}
COLS = {
    "bodies.csv": ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"],
    "accreditations.csv": ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"],
    "scopes.csv": ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"],
}
NOISE = re.compile(r"^(Page \d+ of \d+.*|The controlled version.*|repository for the latest version\.)$")


def phone(raw, country, review, name):
    p = re.split(r"\s*ext\.?", raw)[0].strip()
    if p.startswith("+"):
        return re.sub(r"[^\d+ ]", " ", p).strip()
    d = re.sub(r"\D", "", p)
    cc = DIAL.get(country)
    if not cc or not d:
        review.append(f"{name}: phone '{raw}' could not be made international; left empty")
        return ""
    if cc == "1":
        if len(d) == 11 and d[0] == "1":
            d = d[1:]
        if len(d) != 10:
            review.append(f"{name}: phone '{raw}' is not a 10-digit NANP number; left empty")
            return ""
        out = f"+1 {d[:3]} {d[3:6]} {d[6:]}"
    else:
        out = f"+{cc} {d.lstrip('0')}"
    if "ext" in raw:
        review.append(f"{name}: extension dropped from phone '{raw}'")
    return out


def sections(text):
    lines = [l for l in text.splitlines() if not NOISE.match(l.strip())]
    starts = [i for i, l in enumerate(lines) if l.startswith("Base program:")]
    for k, s in enumerate(starts):
        yield "\n".join(lines[s:starts[k + 1] if k + 1 < len(starts) else len(lines)])


def iaf_codes(sec):
    codes = set()
    for l in sec.splitlines():
        for m in re.finditer(r"(?:^|\s)(\d{1,2})\s+[A-Z][a-z]", l):
            if 1 <= int(m.group(1)) <= 39:
                codes.add(int(m.group(1)))
    return codes


def scope_of(fileno, text, review, debug):
    """-> {standard: (ea set, note)}"""
    out = {}
    for sec in sections(text):
        base = sec.splitlines()[0]
        cert_part = sec.split("Certification", 1)[-1] if "Certification" in sec else sec
        stds = [s for s, rx in STD_RX if re.search(rx, cert_part)]
        skipped = False
        for lab, rx in SKIP_RX:
            if re.search(rx, sec):
                skipped = True
                review.append(f"{fileno}: skipped {lab}")
        if not stds and not skipped:
            m = re.search(r"\(([A-Za-z&]+)\)", " ".join(sec.splitlines()[:2]))
            if m and m.group(1) in BASE_STD:
                stds = [BASE_STD[m.group(1)]]
                review.append(f"{fileno}: no certification standard line in the {m.group(1)} section; "
                              f"taken from the base program as {stds[0]}")
            else:
                review.append(f"{fileno}: UNRECOGNISED section '{base}'")
        if debug:
            print(f"--- {fileno} {base} -> {stds}")
        for s in stds:
            note = ""
            if s in IAF_STD:
                ea = iaf_codes(sec)
                if not ea:
                    ea, note = expand(ALL), "No IAF code list in the SCC scope; recorded for all EA sectors"
            elif s == "ISO 13485":
                low = sec.lower()
                areas = [k for rx, k in MED_RX if re.search(rx, low)]
                ea = set().union(*(expand(MED[k]) for k in areas)) if areas else expand(ALL)
                note = ("IAF MD 8 main technical areas classified to EA: " + ", ".join(areas)) if areas else \
                    "No technical areas in the SCC scope; recorded for all EA sectors"
            elif s == "ISO 50001":
                low = sec.lower()
                areas = [a for a, keys, _ in ENERGY if any(k in low for k in keys)]
                if areas:
                    ea = set().union(*(expand(sp) for a, _, sp in ENERGY if a in areas))
                    note = "ISO 50003 technical areas " + ", ".join(areas) + " classified to EA"
                else:
                    ea, note = expand(ALL), "No technical area list in the SCC scope; recorded for all EA sectors"
            else:
                ea, note = expand(ALL), "No sector list in the SCC scope; recorded for all EA sectors"
            if s in out:  # e.g. EMS + forestry sub-section both naming ISO 14001
                old, n = out[s]
                out[s] = (old | ea, n or note)
            else:
                out[s] = (ea, note)
    return out


def existing_bodies():
    idx = {}
    for f in (ROOT / "data").glob("*/bodies.csv"):
        if f.parent.name == "scc-canada":
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            idx.setdefault((r["country"], r["name"].lower()), r)
    return idx


# SCC name -> (country, name) of the row in another dataset
ALIASES = {
    "KVQA CERTIFICATION SERVICES PRIVATE LIMITED": ("India", "KVQA Certification Services PVT. LTD."),
    "National Standards Authority of Ireland (NSAI)": ("Ireland", "NSAI"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    review, B, A, S = [], [], [], []
    known = existing_bodies()
    for r in csv.reader(open(a.scrape / "scc_raw.tsv", encoding="utf-8"), delimiter="\t"):
        name, addr, city, ctry, web, ph, fileno, init, exp, areas, pdf, slug, email = r
        name = re.sub(r" Client L$", "", name).strip()
        country = CTRY.get(ctry, ctry)
        fno = fileno.lstrip("0")
        if exp < a.today:
            review.append(f"{name} ({fno}): accreditation expired {exp}; dropped")
            continue
        text = (a.scrape / "scc_txt" / f"{fno}.txt").read_text(encoding="utf-8")
        scope = scope_of(fno, text, review, fno in a.debug)
        if not scope:
            review.append(f"{name} ({fno}): nothing importable; dropped")
            continue
        m = re.match(r"(.*?)(?: Province (.*?))?(?: Postal Code (.*))?$", city)
        cty, prov, pc = m.group(1), m.group(2) or "", m.group(3) or ""
        cty = cty.title() if cty.isupper() else cty
        address = ", ".join(x for x in [addr, " ".join(x for x in [pc, cty] if x), prov] if x)
        key = ALIASES.get(name, (country, name))
        hit = known.get((key[0], key[1].lower()))
        if hit:
            body = dict(hit)
            review.append(f"{name} ({fno}): reuses existing body row '{hit['name']}' ({hit['country']})")
        else:
            if fno in PHONE_FIX:
                p, why = PHONE_FIX[fno]
                review.append(f"{name}: phone {why}")
            else:
                p = phone(ph, country, review, name)
            body = dict(name=name, country=country, registration_no=fno, phone=p, email=email,
                        website=("https://" + web) if web and not web.startswith("http") else web,
                        address=address, source_url=f"{BASE}/accreditation/management-systems/{slug}", verified_at="")
        if any(b["name"] == body["name"] for b in B):
            review.append(f"DUPLICATE body name {body['name']}")
        B.append(body)
        proof = f"{BASE}/system/files/{pdf}" if pdf else ""
        rows = {}
        for std in sorted(scope, key=lambda s: s not in IAF_STD):
            ea, note = scope[std]
            acc, suf = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", ""))
            cert = f"{fno} {suf}".strip()
            if cert not in rows:
                rows[cert] = acc
            S.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea_spec(ea),
                          status="ACTIVE", scope_note=note))
        if "ISO/IEC 17021-1" not in rows.values():
            review.append(f"{name} ({fno}): no ISO/IEC 17021-1 row; dropped (prune)")
            B.pop()
            S = [s for s in S if s["certificate_number"].split()[0] != fno]
            continue
        for cert, acc in sorted(rows.items(), key=lambda x: x[1] != "ISO/IEC 17021-1"):
            A.append(dict(ab_code=AB, certificate_number=cert, body_name=body["name"], accreditation_standard=acc,
                          status="ACTIVE", issue_date=init, expiry_date=exp, proof_url=proof))
        reg = {x for x in re.findall(r"\(([^)]+)\)", areas)}
        review.append(f"{name} ({fno}): register areas {sorted(reg)}; imported {sorted(scope)}")
    a.out.mkdir(parents=True, exist_ok=True)
    for fn, data in zip(COLS, (B, A, S)):
        with open(a.out / fn, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLS[fn]); w.writeheader(); w.writerows(data)
    (HERE / "scc_review.md").write_text("# SCC review\n\n" + "\n".join(f"- {x}" for x in review) + "\n", encoding="utf-8")
    print(f"bodies {len(B)}, accreditations {len(A)}, scopes {len(S)}")


if __name__ == "__main__":
    main()
