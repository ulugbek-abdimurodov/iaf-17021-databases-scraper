"""Convert jab_raw.txt into CertiFind CSVs under data/jab-japan/."""
import re, sys
from pathlib import Path
from certifind_common import compress_ea_codes, resolve_cert_number, write_certifind_csvs, ISO22003_TO_EA, MD8_TO_EA

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "jab-japan"
SRC = "https://www.jab.or.jp/en/certification_institutions"
PDF = "https://www.jab.or.jp/cms/uploads/"
SCHEME = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHSMS": "ISO 45001", "FSMS": "ISO 22000",
          "FSSC 22000": "FSSC 22000", "MD-QMS": "ISO 13485", "ISMS": "ISO/IEC 27001", "EnMS": "ISO 50001",
          "AS-QMS(9100)": "AS 9100"}
MD = {"1": "Non-active medical devices", "2": "Active (non-implantable) medical devices",
      "3": "Active implantable medical devices", "4": "In vitro diagnostic medical devices",
      "5": "Sterilization methods", "6": "Devices incorporating specific substances / technologies", "7": "Parts or services"}
import csv
_D = Path(r"C:/Users/vbrgr/Desktop/CertiFind/certifind/data")
def _row(ds, n): return next(r for r in csv.DictReader(open(_D/ds/"bodies.csv", encoding="utf-8")) if r["name"] == n)
REUSE = {"CM009": _row("ukas-united-kingdom", "Japan Quality Assurance Organization"),
         "CM021": _row("ukas-united-kingdom", "Japan Audit and Certification Organization for Environment & Quality"),
         "CM004": _row("rva-netherlands", "Japan Gas Appliances Inspection Association")}
COUNTRY = {"JAPAN": "Japan", "U.S.A.": "United States"}

def ea_for(scheme, codes):
    if scheme in ("FSMS", "FSSC 22000"):
        cats = [c for c in codes if c in ISO22003_TO_EA]
        return compress_ea_codes(e for c in cats for e in ISO22003_TO_EA[c]), "Food chain categories " + ", ".join(cats)
    if scheme == "MD-QMS":
        ids = [c.split("~")[0] for c in codes]
        return compress_ea_codes(e for i in ids for e in MD8_TO_EA[MD[i]]), "IAF MD 8 areas: " + "; ".join(MD[i] for i in ids)
    return compress_ea_codes(int(c) for c in codes if c.isdigit()), ""

bodies, accs, scopes, excluded = [], [], [], []
for line in (HERE / "jab_raw.txt").read_text(encoding="utf-8").splitlines():
    cn, name, loc, tel, web, init, renew, exp, pdf, secs, rst = line.split("|")
    rest = {k: v for k, v in (s.split(":", 1) for s in rst.split(";") if s)}
    sec = {k: [c for c in v.split(",") if c] for k, v in (s.split(":", 1) for s in secs.split(";"))}
    keep = {k: v for k, v in sec.items() if k in SCHEME}
    excluded += [f"{cn} {k}" for k in sec if k not in SCHEME]
    if not keep:
        continue
    m = re.search(r",?\s*(Japan|JAPAN|U\.S\.A\.)\s*$", loc)
    country = COUNTRY.get(m.group(1).upper(), "Japan") if m else "Japan"
    addr = loc[:m.start()].strip(" ,") if m else loc
    tel = re.sub(r"[-\s]+", " ", tel.strip())
    if tel and not re.fullmatch(r"\+\d[\d ]{6,}", tel):
        print("BAD PHONE", cn, tel); tel = ""
    if cn in REUSE:
        name = REUSE[cn]["name"]; bodies.append(dict(REUSE[cn]))
    else:
      bodies.append(dict(name=name.strip(), country=country, registration_no=cn, phone=tel, email="", website=web,
                       address=addr, source_url=SRC, verified_at=""))
    by_cert = {}
    for k, codes in keep.items():
        cert, std = resolve_cert_number(cn, SCHEME[k])
        by_cert.setdefault(cert, std)
        ea, note = ea_for(k, codes)
        if k in rest:
            r = "Restricted codes (see proof_url): " + rest[k].replace(",", "; ")
            note = f"{note}; {r}" if note else r
        scopes.append(dict(certificate_number=cert, certification_standard=SCHEME[k], ea_codes=ea, status="ACTIVE",
                           scope_note=(note or "") if ea else "No sector list in the JAB register; recorded for all EA sectors"))
        if not ea: scopes[-1]["ea_codes"] = "1-39"
    for cert, std in by_cert.items():
        accs.append(dict(ab_code="JAB", certificate_number=cert, body_name=name.strip(), accreditation_standard=std,
                         status="ACTIVE", issue_date=init, expiry_date=exp, proof_url=PDF + pdf))

import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, accs, scopes)
(HERE / "excluded.txt").write_text("\n".join(excluded), encoding="utf-8")
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excluded)}")
