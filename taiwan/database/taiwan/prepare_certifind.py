"""Convert raw TAF scrape (raw/*.txt) into CertiFind CSVs under data/taf-taiwan/."""
import re
from datetime import date
from pathlib import Path
from certifind_common import (ISO22003_TO_EA, ISO50003_TO_EA, compress_ea_codes,
                              resolve_cert_number, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "taf-taiwan"
LIST = "https://www.taftw.org.tw/en/find-facility/scheme/msv/"
SCOPE = "https://accreditation.taftw.org.tw/taf/public/basic/viewApplyItems.action?unitNo={}&language=EN"
TODAY = date(2026, 11, 9)

# TAF code -> CertiFind certification standard (None = out of scope)
SCHEMES = {"01": "ISO 9001", "02": "ISO 14001", "0301": "ISO 45001", "0401": "ISO 22000",
           "0501": "ISO/IEC 27001", "0302": None, "0502": None, "07": None}
SKIP_NOTE = {"0302": "TOSHMS (Taiwan OSH national scheme)", "0502": "Cyber Security Management Act scheme",
             "07": "Water Efficiency Management Systems (ISO 46001)"}
# ISO 50003 technical areas (TAF 06xx) -> EA via certifind_common letters
ENERGY = {"01": ("Industry – light to medium", ISO50003_TO_EA["A"]),
          "02": ("Industry – heavy", ISO50003_TO_EA["A"] + [10]),
          "03": ("Buildings", ISO50003_TO_EA["B"]), "04": ("Building complexes", ISO50003_TO_EA["B"]),
          "05": ("Transport", ISO50003_TO_EA["E"]), "06": ("Mining", ISO50003_TO_EA["F"]),
          "07": ("Agriculture", ISO50003_TO_EA["G"]), "08": ("Energy supply", ISO50003_TO_EA["D"])}

def iso(d): return d.replace("/", "-")

def clean_addr(a):
    a = re.sub(r",?\s*\(?R\.?O\.?C\.?\)?\s*$", "", a.strip()).strip(" ,")
    return re.sub(r"\s+,", ",", a)

def main():
    bodies, accs, scopes, review = [], [], [], []
    braw = {l.split("|")[0]: l.split("|") for l in (HERE / "raw/msv_bodies.txt").read_text("utf-8").splitlines() if l}
    for line in (HERE / "raw/msv_scopes.txt").read_text("utf-8").splitlines():
        if not line: continue
        cid, oa, eff, exp, sc = line.split("|")
        _, name, addr, phone, web, mail = braw[cid]
        groups = dict(g.split(":", 1) for g in sc.split(";") if g)
        rows = []
        energy = [k[2:] for k in groups if re.fullmatch(r"06\d\d", k)]
        for k, v in groups.items():
            if k.startswith("06"): continue
            std = SCHEMES.get(k)
            items = [x for x in v.split(",") if x]
            susp = [x[:-1] for x in items if x.endswith("#")]
            act = [x for x in items if not x.endswith("#")]
            if std is None:
                review.append(f"| {cid} | {name} | {SKIP_NOTE.get(k, k)} | out of CertiFind scope |"); continue
            note = ""
            if std == "ISO 22000":
                cats = sorted(set(x[0] for x in act))
                ea = compress_ea_codes(c for x in cats for c in ISO22003_TO_EA[x])
                note = f"ISO 22003-1 categories {', '.join(act)}"
            elif std == "ISO/IEC 27001":
                ea = ""; note = "ISMS (no EA sectors in TAF scope)"
            else:
                ea = compress_ea_codes(int(x) for x in act)
            if susp:
                note = (note + "; " if note else "") + f"suspended EA {', '.join(s.lstrip('0') for s in susp)}"
            rows.append((std, ea, note))
        if energy:
            ea = compress_ea_codes(c for e in energy for c in ENERGY[e][1])
            rows.append(("ISO 50001", ea, "ISO 50003 technical areas: " + ", ".join(ENERGY[e][0] for e in energy)))
        if not rows:
            review.append(f"| {cid} | {name} | all schemes out of scope | body excluded |"); continue
        bodies.append(dict(name=name, country="Taiwan", registration_no=cid, phone=phone, email=mail,
                           website=web, address=clean_addr(addr), source_url=LIST, verified_at=""))
        status = "active" if date.fromisoformat(iso(exp)) >= TODAY else "expired"
        seen = set()
        for std, ea, note in rows:
            num, acc_std = resolve_cert_number(cid, std)
            if num not in seen:
                seen.add(num)
                accs.append(dict(ab_code="TAF", certificate_number=num, body_name=name, accreditation_standard=acc_std,
                                 status=status, issue_date=iso(oa), expiry_date=iso(exp), proof_url=SCOPE.format(cid)))
            scopes.append(dict(certificate_number=num, certification_standard=std, ea_codes=ea, status="active", scope_note=note))
    write_certifind_csvs(OUT, bodies, accs, scopes)
    print(f"Excluded: {len(review)}")
    (HERE / "taf_review.md").write_text(
        "# TAF (Taiwan) review log\n\nSkipped schemes / bodies (source: viewApplyItems scope pages).\n\n"
        "| ID | Body | Scheme | Reason |\n|---|---|---|---|\n" + "\n".join(review) + "\n", "utf-8")

if __name__ == "__main__":
    main()
