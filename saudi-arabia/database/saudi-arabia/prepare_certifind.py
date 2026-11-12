"""Convert saac_raw.txt -> data/saac-saudi-arabia/*.csv (CertiFind format)."""
import re
from datetime import datetime
from pathlib import Path
from certifind_common import (ISO22003_TO_EA, MD8_TO_EA, compress_ea_codes,
                              resolve_cert_number, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "saac-saudi-arabia"
SRC = "https://saac.gov.sa/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Management+Systems+Certificates"
DETAIL = "https://saac.gov.sa/en/accredited-bodies/?appid={}"

# duplicate register spellings -> canonical body index
ALIAS = {10: 9, 35: 9, 13: 8, 19: 4, 48: 11, 25: 14, 39: 14, 28: 26, 44: 26, 40: 21,
         37: 22, 50: 38, 45: 1, 46: 1, 49: 1, 20: 32}
CANON_NAME = {1: "Arabian Certification Company for Business Services (ACC)", 4: "SGS Inspection Services Saudi Arabia Ltd.",
              8: "Optimal Support Services Company for Verification and Conformity", 9: "QSI Cert Co",
              11: "Intertek Arabia Administrative Company", 14: "TUV Limited Co.", 21: "Branch of TUV Austria Shanghai Co. Ltd",
              22: "National Inspection & Technical Testing Company Ltd. (FAHSS)", 26: "Sustainable Management Group Co.",
              38: "Pioneers of Quality Systems & Certifications Company", 15: "ISO Cert International",
              18: "Motan Al-Anzama Commercial (TCI Branch)"}
WEB_FIX = {"null": "", "www,iso-qms.org": "www.iso-qms.org", "www-qsi-cert.com": "www.qsi-cert.com"}
SCHEME = [("ISO 22301", "BCMS"), ("ISO 14001", "EMS"), ("ISO/IEC 27001", "ISMS"), ("ISO 45001", "OHS"),
          ("ISO 9001", "QMS"), ("ISO 22000", "FSMS"), ("ISO 50001", "EnMS"), ("ISO 13485", "MDMS")]
MD8_NORM = {"non-active": "Non-active medical devices", "active medical devices (non-implantable)": "Active (non-implantable) medical devices",
            "active implantable": "Active implantable medical devices", "in vitro": "In vitro diagnostic medical devices",
            "sterilization": "Sterilization methods", "parts or services": "Parts or services"}
STATUS = {"Active": "active", "Cancelled": "withdrawn", "Expired": "expired"}


def iso(d):
    return datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d") if d else ""


def main():
    sec, B, C = None, {}, []
    for ln in (HERE / "saac_raw.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            sec = ln[1:6]; continue
        f = ln.split(";;")
        if sec == "BODIE":
            B[int(f[0])] = f[1:]
        else:
            C.append(f)

    bodies, accs, scopes, used = {}, [], [], {}
    for f in sorted(C, key=lambda x: datetime.strptime(x[4], "%m/%d/%Y")):
        cid, bi, field, status, start, end, iaf, fc, md, oth = f[:10]
        bi = ALIAS.get(int(bi), int(bi))
        name = CANON_NAME.get(bi, re.sub(r"\s+", " ", B[bi][0]).strip())
        std = next(s for s, k in SCHEME if f"-{k}-" in cid)
        if name not in bodies:
            email, phone, city, web = B[bi][1:5]
            web = WEB_FIX.get(web, web).lower().rstrip("/")
            bodies[name] = dict(name=name, country="Saudi Arabia", registration_no=cid, phone=phone.replace(" ", ""),
                                email=email, website=f"https://{web}" if web else "", address=city.title(),
                                source_url=SRC, verified_at="")
        cert, acc_std = resolve_cert_number(cid, std)
        st = STATUS[status]
        accs.append(dict(ab_code="SAAC", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                         status=st, issue_date=iso(start), expiry_date=iso(end), proof_url=DETAIL.format(cid.lower())))
        ea, note = "", ""
        if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
            ea = compress_ea_codes(int(x) for x in iaf.split(",") if x)
            note = "IAF codes as listed in the SAAC register" if ea else "No IAF codes published in the SAAC register"
        elif std == "ISO 22000":
            cats = set(fc) | {m.group(1) for m in re.finditer(r"(?:^|\|)([A-K]) ", oth)}
            ea = compress_ea_codes(c for k in cats for c in ISO22003_TO_EA[k])
            note = f"Classified to EA from ISO 22003-1 categories {', '.join(sorted(cats))}" if cats else "No food chain categories published in the SAAC register"
        elif std == "ISO 13485":
            areas = []
            for a in [x for x in md.split("|") if x]:
                n = next((v for k, v in MD8_NORM.items() if a.lower().startswith(k)), None)
                n and n not in areas and areas.append(n)
            ea = compress_ea_codes(c for a in areas for c in MD8_TO_EA[a])
            note = f"Classified to EA from IAF MD 8 main technical areas: {'; '.join(areas)}" if areas else "No technical areas published in the SAAC register"
        else:
            note = "No technical areas or sectors published in the SAAC register"
        scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea, status=st, scope_note=note))

    write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: 0")


if __name__ == "__main__":
    main()
