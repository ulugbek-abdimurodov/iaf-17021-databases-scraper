import json, sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import resolve_cert_number, write_certifind_csvs

SRC = "https://center.tisi.go.th/report/certificate?sort=CB"
OUT = Path(__file__).parents[2] / "data" / "tisi-thailand"
SCHEME = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001", "OHSMS": "ISO 45001", "EnMS": "ISO 50001"}
BODY = {  # name: (phone, email, address)
    "TUV NORD (Thailand) Ltd.": ("0867129350", "Thitiporn@tuv-nord.com", "1858/103-104, 23rd Floor Interlink Tower, Debaratna Road, Bangna Tai, Bangna, Bangkok 10260"),
    "Global Certification Service Co., Ltd.": ("089-501-6468", "info@thaigcs.com", "3 Soi Rattanathibet 30, Bang Krasor, Mueang Nonthaburi, Nonthaburi 11000"),
    "Management System Certification Institute (Thailand)": ("085-1166571", "cb&IB@masci.or.th", "1025 Yakult Building, Phaholyothin Road, Phayathai, Bangkok 10400"),
    "Bureau Veritas Certification (Thailand) Ltd.": ("026704800", "thanakorn.wainiyom@bureauveritas.com", "2170 Bangkok Tower, 16th Floor, New Petchburi Road, Bangkapi, Huaykwang, Bangkok 10310"),
    "Thai International Certification Co., Ltd.": ("02-678-5154", "ticacert@gmail.com", "2/10 Soi 28/1 Rama 3 Road, Bang Phong Phang, Yan Nawa, Bangkok 10120"),
    "Thailand Institute of Scientific and Technological Research (TISTR)": ("025779374", "kanrawee_t@tistr.or.th", "35 Moo 3 Technopolis, Khlong 5, Khlong Luang, Pathum Thani 12120"),
    "International Certification & Compliance Co., Ltd.": ("", "office@intcertthai.com", "8/11 Soi Ramintra 4/2A, Anusawari, Bang Khen, Bangkok 10220"),
    "SGS (Thailand) Limited": ("0881515514", "SGSTHTISI@sgs.com", "238 TRR Tower, 19th-21st Floor, Naradhiwas Rajanagarindra Road, Chong Nonsi, Yannawa, Bangkok 10120"),
}

def d(s):
    return datetime.strptime(s, "%d %B %Y").date().isoformat() if s else ""

def main():
    raw = json.load(open(Path(__file__).parent / "tisi_raw.json", encoding="utf-8"))
    bodies, accs, scopes, excl, reg = [], [], [], 0, {}
    for cert, acc, body, f, t, note in raw:
        pref = acc.split()[0]
        if pref not in SCHEME or note.startswith("superseded"):
            excl += 1
            continue
        reg.setdefault(body, acc)
        num, std = resolve_cert_number(acc, SCHEME[pref])
        exp = d(t)
        status = "expired" if exp and exp < date.today().isoformat() else "active"
        accs.append({"ab_code": "TISI", "certificate_number": num, "body_name": body, "accreditation_standard": std,
                     "status": status, "issue_date": d(f), "expiry_date": exp, "proof_url": SRC})
        scopes.append({"certificate_number": num, "certification_standard": SCHEME[pref], "ea_codes": "", "status": status,
                       "scope_note": f"TISI certificate {cert}; scope annex is a scanned PDF, EA codes not listed in register"})
    for name, r in reg.items():
        ph, em, ad = BODY[name]
        bodies.append({"name": name, "country": "Thailand", "registration_no": r, "phone": ph, "email": em,
                       "website": "", "address": ad, "source_url": SRC, "verified_at": ""})
    write_certifind_csvs(OUT, bodies, accs, scopes)
    print(f"Excluded: {excl}")

if __name__ == "__main__":
    main()
