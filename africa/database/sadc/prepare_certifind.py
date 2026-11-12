import json, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import compress_ea_codes, resolve_cert_number, ISO22003_TO_EA, write_certifind_csvs

HERE = Path(__file__).parent
REG = "https://www.sadcas.org/accredited-organisations/management-bodies"
FILES = "https://www.sadcas.org/sites/default/files/"
STD = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001", "FSMS": "ISO 22000", "ISMS": "ISO/IEC 27001"}
BODIES = {
 "Botswana Bureau of Standards - Certification Unit": ("Botswana", "+267 390 3200", "bannyaditse@bobstandards.bw", "Plot 55745, Block 8, Airport Road, Gaborone"),
 "Eswatini Standards Authority - Certification Services": ("Eswatini", "+268 2518 4610", "pmndawe@swasa.co.sz", "Plot 247, King Mswati III Avenue, Matsapha Industrial Site, Matsapha"),
 "Malawi Bureau of Standards - Management Systems Certification": ("Malawi", "+265 1 320 327", "gchaonamwene@mbsmw.org", "Ali Hassan Mwinyi Road, Blantyre"),
 "Namibian Standards Institution - Certification Department": ("Namibia", "+264 61 386 400", "mwakatundui@nsi.com.na", "37 Feld Street, Windhoek"),
 "Standards Association of Zimbabwe - Certification Services": ("Zimbabwe", "+263 242 662 165", "nmatshitse@saz.org.zw", "66 Craster Road, Southerton, Harare"),
 "Tanzania Bureau of Standards - Management System Certification Services": ("Tanzania", "+255 22 2450 206", "magdalena.sademaki@tbs.go.tz", "Junction of Morogoro/Sam Nujoma Roads, Ubungo, Dar es Salaam"),
 "Zambia Bureau of Standards - Certification Services": ("Zambia", "+260 211 231 386", "sshawa@zabs.org.zm", "Lechwe House, Freedom Way, South End, Lusaka"),
}
d = lambda s: datetime.strptime(s.replace(",", ""), "%d %B %Y").strftime("%Y-%m-%d")
bodies, accs, scopes, excl, firstid = [], [], [], [], {}
for cid, name, i, e, p, iaf, cat in json.loads((HERE / "sadcas_raw.json").read_text()):
    pre = cid.split("-")[0]
    if pre not in STD:
        excl.append(cid); continue
    firstid.setdefault(name, cid)
    std = STD[pre]
    cert, acc_std = resolve_cert_number(cid, std)
    accs.append(dict(ab_code="SADCAS", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                     status="active", issue_date=d(i), expiry_date=d(e), proof_url=FILES + p))
    if cat:
        ea = compress_ea_codes(c for k in cat for c in ISO22003_TO_EA[k]); note = f"Classified to EA from ISO 22003-1 categories {', '.join(cat)}"
    elif iaf:
        ea = compress_ea_codes(iaf); note = ""
    else:
        ea = ""; note = "No sector restriction listed in the schedule of accreditation"
    scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea, status="active", scope_note=note))
for name, cid in firstid.items():
    c, ph, em, ad = BODIES[name]
    bodies.append(dict(name=name, country=c, registration_no=cid, phone=ph, email=em, website="", address=ad, source_url=REG, verified_at=""))
write_certifind_csvs(HERE.parent.parent / "data/sadcas-sadc", bodies, accs, scopes)
print(f"Excluded: {len(excl)} ({', '.join(excl)})")
