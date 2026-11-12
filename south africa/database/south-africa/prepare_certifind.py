import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (compress_ea_codes, resolve_cert_number, ISO22003_TO_EA, MD8_TO_EA, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "sanas-south-africa"
SRC = "https://www.sanas.co.za/Pages/index.aspx"
PDF = "https://www.sanas.co.za/Certificate%20Published/{}.pdf"
SCHEME = {"9001": "ISO 9001", "14001": "ISO 14001", "45001": "ISO 45001", "3834": "ISO 3834",
          "22000": "ISO 22000", "F": "FSSC 22000", "I27001": "ISO/IEC 27001", "13485": "ISO 13485", "50001": "ISO 50001"}
CANON = [  # (canonical name, raw idxs)
    ("i-Cert (Pty) Ltd", [0]), ("SGS South Africa (Pty) Ltd", [1]),
    ("TUV Rheinland Inspection Services (Pty) Ltd", [2, 41]), ("Alpha Certification Services CC", [3, 15]),
    ("Southern African Institute of Welding NPC", [4]),
    ("Environmental Quality Certification Services Africa (Pty) Ltd", [5, 6, 29]),
    ("SABS Commercial SOC Ltd", [7, 9, 14]),
    ("South African Certification and Auditing Services (Pty) Ltd", [8, 10, 11, 12, 22]),
    ("SHEQ National Cert (Pty) Ltd", [13]), ("African Certification and Testing (Pty) Ltd", [16]),
    ("Uganda National Bureau of Standards", [17]), ("Judah Compliance Auditors CC", [18]),
    ("BSI Group South Africa (Pty) Ltd", [19, 20]), ("Isoqar Africa (Pty) Ltd", [21]),
    ("AfriCert (Pty) Ltd", [23]), ("South African Compliance and Certification (Pty) Ltd", [24, 25]),
    ("Sancert (Pty) Ltd", [26]), ("Industry Compliance and Certification Authority of South Africa (Pty) Ltd", [27]),
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
NON_ZA = {"Uganda"}

def md8(areas):
    ea = set()
    for a in areas:
        a = a.lower()
        if "non-active" in a or "non - active" in a: ea.update(MD8_TO_EA["Non-active medical devices"])
        elif "active" in a: ea.update(MD8_TO_EA["Active (non-implantable) medical devices"])
        if "steril" in a: ea.update(MD8_TO_EA["Sterilization methods"])
    return ea

raw = (HERE / "sanas_raw.txt").read_text(encoding="utf-8").split("\n#\n")
certs = [l.split("|") for l in raw[0].strip().splitlines()]
binfo = {int(r[0]): r for r in (l.split("|") for l in raw[1].strip().splitlines())}

bases = {}
for c in certs:
    bases.setdefault(IDX[int(c[1])], []).append(re.match(r"C\d+", c[0]).group())
bodies, seen = [], set()
for c in certs:
    name = IDX[int(c[1])]
    if name in seen: continue
    seen.add(name)
    r = binfo[int(c[1])]
    country = r[5] if r[5] in NON_ZA else "South Africa"
    pc = r[4] if re.fullmatch(r"\d{4}", r[4] or "") else ""
    addr = ", ".join(x for x in [r[2].strip(), f"{pc} {r[3].strip().title() if r[3].isupper() else r[3].strip()}".strip()] if x)
    reg = sorted(set(bases[name]), key=lambda b: int(b[1:]))[0]
    bodies.append(dict(name=name, country=country, registration_no=reg, phone=r[6].strip(), email=r[7].strip(),
                       website="", address=addr, source_url=SRC, verified_at=""))

accs, scopes = [], []
for fac, bi, idate, exp, sch, ea, cats, md, stem in certs:
    fac = fac.strip(); std = SCHEME[sch]
    cert_no, acc_std = resolve_cert_number(fac, std)
    accs.append(dict(ab_code="SANAS", certificate_number=cert_no, body_name=IDX[int(bi)], accreditation_standard=acc_std,
                     status="active", issue_date=idate, expiry_date=exp, proof_url=PDF.format(stem.strip().replace(" ", "%20"))))
    note = ""
    if ea:
        codes = set()
        for p in ea.split(";"):
            a, _, b = p.partition("-"); codes.update(range(int(a), int(b or a) + 1))
        ea_s = compress_ea_codes(codes)
    elif cats:
        ea_s = compress_ea_codes(e for k in cats for e in ISO22003_TO_EA.get(k, []))
        note = f"Classified to EA from ISO 22003-1 categories {', '.join(sorted(cats))}"
    elif md:
        ea_s = compress_ea_codes(md8(md.split(";")))
        note = f"Classified to EA from IAF MD 8 technical areas ({md})"
    else:
        ea_s = ""; note = "No sector/category breakdown in SANAS scope schedule"
    scopes.append(dict(certificate_number=cert_no, certification_standard=std, ea_codes=ea_s, status="active", scope_note=note))

import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, accs, scopes)
excluded = 13 + 41
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {excluded}")
