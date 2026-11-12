import json, re
from pathlib import Path
from certifind_common import resolve_cert_number, compress_ea_codes, ISO22003_TO_EA, write_certifind_csvs
H = Path(__file__).resolve().parent
B, REG = "https://e-accreditation.gov.mn", "https://e-accreditation.gov.mn/login"

def iaf(s):
    out = []
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", s):
        out += range(int(a), int(b or a) + 1)
    return out

def cat22000(s):
    letters = set(re.findall(r"\b([A-K])(?:0|I|II|III|IV)?\b", s))
    for a, b in re.findall(r"\b([A-K])[0IV]*\s*-\s*([A-K])\b", s):
        letters |= {chr(c) for c in range(ord(a), ord(b) + 1)}
    return sorted(letters)

bodies, accs, scopes, excl = [], [], [], 0
for r in json.load(open(H / "raw_mnas.json", encoding="utf-8")):
    base = r["cert"]; proof = B + r["pdf"]
    bodies.append(dict(name=r["name"], country="Mongolia", registration_no=base, phone=r["phone"], email=r["email"],
                       website="", address=r["address"], source_url=REG, verified_at=""))
    seen = set()
    for std, sc in r["scopes"].items():
        cn, acc = resolve_cert_number(base, std)
        if cn not in seen:
            seen.add(cn)
            accs.append(dict(ab_code="MNAS", certificate_number=cn, body_name=r["name"], accreditation_standard=acc,
                             status=r["status"], issue_date=r["issue"], expiry_date=r["expiry"], proof_url=proof))
        if std == "ISO 22000":
            cats = cat22000(sc); ea = compress_ea_codes(c for k in cats for c in ISO22003_TO_EA[k])
            note = f"Classified to EA from ISO 22003-1 categories ({sc})"
        elif sc.startswith("IAF"):
            ea, note = compress_ea_codes(iaf(sc)), ""
        else:
            ea, note = "", "No sector restriction stated on certificate"
        scopes.append(dict(certificate_number=cn, certification_standard=std, ea_codes=ea, status=r["status"], scope_note=note))
    excl += len(r.get("skipped", []))
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(H.parents[1] / "data/mnas-mongolia", bodies, accs, scopes)
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {excl}")
