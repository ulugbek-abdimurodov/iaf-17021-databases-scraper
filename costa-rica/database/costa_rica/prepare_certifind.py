import json,sys
from certifind_common import compress_ea_codes,resolve_cert_number,write_certifind_csvs
from scrape_cr_eca import RAW,BASE
B,A,S=[],[],[];seen=set()
for r in RAW:
    B.append(dict(name=r["name"],country="Costa Rica",registration_no=r["id"],phone=r["phone"],email=r["email"],
      website=r["website"],address=r["address"],source_url=r["source_url"],verified_at=""))
    for std,ea,pdf in r["schemes"]:
        cn,acc=resolve_cert_number(r["id"],std)
        if cn not in seen:
            seen.add(cn);A.append(dict(ab_code="ECA",certificate_number=cn,body_name=r["name"],accreditation_standard=acc,
              status="active",issue_date=r["issue_date"],expiry_date="",proof_url=BASE+pdf))
        S.append(dict(certificate_number=cn,certification_standard=std,ea_codes=compress_ea_codes(ea),status="active",
          scope_note="" if ea else "No IAF/EA sectors listed in annex"))
import io,contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs("../../data/eca-costa_rica",B,A,S)
print(f"Bodies: {len(B)}\nAccreditations: {len(A)}\nScopes: {len(S)}\nExcluded: 4 schemes (INTE G38-3, ISO 28000, ISO 37001, ISO 22000/FSSC reduced)")
