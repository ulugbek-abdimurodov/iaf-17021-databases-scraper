import json, re, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (compress_ea_codes, resolve_cert_number, ISO22003_TO_EA, MD8_TO_EA, write_certifind_csvs)

ROOT = Path(__file__).resolve().parents[2]
RAW = json.loads((ROOT / "raw/uaf.json").read_text())
OUT = ROOT / "data/uaf-united-states"
TODAY = date(2026, 11, 10)
MD = ["Non-active medical devices", "Active implantable medical devices", "Active (non-implantable) medical devices",
      "In vitro diagnostic medical devices", "Sterilization methods",
      "Devices incorporating specific substances / technologies", "Parts or services"]
COUNTRY = {"Republic of Korea": "South Korea"}
SRC = "https://www.uafaccreditation.org/directory/listofAccreditedCabs/CABDetails/"

def iso(d):
    m, dd, y = d.split("/"); return f"{y}-{int(m):02d}-{int(dd):02d}"

def tc(s):
    return s.title() if s and s.isupper() else (s or "")

def web(w):
    w = (w or "").strip()
    if not w or "." not in w: return ""
    return w if w.startswith("http") else "https://" + w

bodies, accs, scopes, excl = [], [], [], []
for c in RAW:
    rows = [(d["u"], s) for d in c["docs"] for s in d["s"]]
    xs = sorted({re.sub(r"\s+", " ", x).strip() for x in c["x"] if len(x) > 3})
    if not rows:
        excl.append((c["n"], "no in-scope ISO/IEC 17021-1 scheme; holds: " + (", ".join(xs) or "non-MS schedules only")))
        continue
    if xs: excl.append((c["n"], "skipped schemes: " + "; ".join(xs)))
    name = re.sub(r"\s+", " ", c["n"]).strip()
    city = tc(c["ci"]); addr = (c["a"] or "").strip().rstrip(",")
    parts = [addr] if addr else []
    pc = " ".join(p for p in [c["z"] or "", city] if p)
    if pc and (not city or city.lower() not in addr.lower()): parts.append(pc)
    phone = "" if (c["p"] or "") in ("undefined", "null") else c["p"]
    bodies.append(dict(name=name, country=COUNTRY.get(c["co"], c["co"]), registration_no=c["sc"], phone=phone,
                       email=c["e"] or "", website=web(c["w"]), address=", ".join(parts), source_url=SRC + c["id"], verified_at=""))
    for url, (std, no, f, e, iaf, cats, md) in rows:
        cert, acc_std = resolve_cert_number(no, std)
        exp = iso(e); st = "active" if date.fromisoformat(exp) >= TODAY else "expired"
        accs.append(dict(ab_code="UAF", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                         status=st, issue_date=iso(f), expiry_date=exp, proof_url=url))
        if cats:
            ea = compress_ea_codes(x for k in cats for x in ISO22003_TO_EA[k])
            note = f"Classified to EA from ISO 22003-1 food chain categories {', '.join(sorted(set(cats)))}"
        elif md:
            areas = [MD[int(i)] for i in sorted(set(md))]
            ea = compress_ea_codes(x for a in areas for x in MD8_TO_EA[a])
            note = "Classified to EA from IAF MD 8 main technical areas: " + "; ".join(areas)
        elif iaf:
            ea = compress_ea_codes(int(x) for x in iaf.split(",")); note = "IAF codes as listed in UAF schedule"
        else:
            ea = ""; note = "No sector codes listed in UAF schedule for this scheme"
        scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea, status=st, scope_note=note))

import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, accs, scopes)
rv = ["# UAF review log", "", "Scope: UAF Management Systems programme, active and visible CABs (64 listed).", "",
      "Non-17021-1 schedules ignored (inspection, testing lab, product certification, GHG validation/verification).", "",
      "| Body | Reason |", "| --- | --- |"] + [f"| {n} | {r} |" for n, r in excl]
(ROOT / "database/united-states/uaf_review.md").write_text("\n".join(rv) + "\n")
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {sum(1 for n,r in excl if r.startswith('no '))}")
