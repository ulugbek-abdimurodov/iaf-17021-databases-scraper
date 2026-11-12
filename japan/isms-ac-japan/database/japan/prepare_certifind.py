"""Convert raw ISMS-AC scrape into CertiFind CSVs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from certifind_common import write_certifind_csvs, resolve_cert_number

OUT = Path(__file__).resolve().parents[2] / "data" / "isms-ac-japan"
SRC = "https://isms.jp/english/"
URLS = {"ISMS": "lst/isr/isr.html", "ITSMS": "itsms/lst/isr/isr.html", "BCMS": "bcms/lst/isr/isr.html",
        "PIMS": "pims/lst/isr/isr.html", "AIMS": "", "ISPIMS": "lst/isr/isr-ismspims.html"}
STD = {"ISMS": "ISO/IEC 27001", "ISPIMS": "ISO/IEC 27701", "PIMS": "ISO/IEC 27701",
       "ITSMS": "ISO/IEC 20000-1", "BCMS": "ISO 22301", "AIMS": "ISO/IEC 42001"}
NOTE = "No sector list in the ISMS-AC register; recorded for all EA sectors"
import csv, re
JAB = Path(__file__).resolve().parents[3] / "certifind_jab_japan/data/jab-japan/bodies.csv"
JAB_ROWS = {r["registration_no"]: r for r in csv.DictReader(open(JAB, encoding="utf-8"))}
# JAB raw names by cert number -> final body row (JAB row may be a reused UKAS/RvA row)
RAW = {l.split("|")[1].strip(): l.split("|")[0] for l in open(JAB.parents[2] / "database/japan/jab_raw.txt", encoding="utf-8")}
ALIAS = {"Perry Johnson Holding, Inc. Perry Johnson Registrars": "Perry Johnson Registrars, Inc."}
def jab_body(n):
    n = re.sub(r"\s*\([^)]*\)$", "", n).strip(); n = ALIAS.get(n, n)
    cm = RAW.get(n)
    if not cm: return None
    final = list(csv.DictReader(open(JAB, encoding="utf-8")))
    acc = list(csv.DictReader(open(JAB.with_name("accreditations.csv"), encoding="utf-8")))
    bn = next(a["body_name"] for a in acc if a["certificate_number"] == cm)
    return next(r for r in final if r["name"] == bn)
dropped = set(); FINAL = {}

raw_b = [l.rstrip("\n").split("\t") for l in open("raw_bodies.tsv", encoding="utf-8")]
raw_a = [l.strip().split(",") for l in open("raw_accreditations.csv") if l.strip()]
accs, scopes, used, excluded = {}, [], {}, 0
for scheme, reg, bi, date in raw_a:
    if scheme not in STD:
        excluded += 1; continue
    b = raw_b[int(bi)]
    jb = jab_body(b[0])
    if not jb:
        dropped.add(b[0]); continue
    b = [jb["name"]] + b[1:]; FINAL[jb["name"]] = jb
    base = reg if scheme != "ISPIMS" else reg  # ISPIMS extends the ISR accreditation
    cert, acc_std = resolve_cert_number(base, STD[scheme])
    first = next((c for c, a in accs.items() if a["body_name"] == b[0] and a["accreditation_standard"] == acc_std), None)
    if first: cert = first  # uq_cb_ab_standard: merge into first registration
    if cert not in accs:
        accs[cert] = dict(ab_code="ISMS-AC", certificate_number=cert, body_name=b[0], accreditation_standard=acc_std,
                          status="ACTIVE", issue_date=date, expiry_date="", proof_url=SRC + URLS[scheme])
    scopes.append(dict(certificate_number=cert, certification_standard=STD[scheme], ea_codes="1-39", status="ACTIVE", scope_note=NOTE))
    used.setdefault(b[0], (reg, b))
bodies = [FINAL[n] for n in used]
print("Dropped (no ISO/IEC 17021-1 from JAB or another AB):", *sorted(dropped), sep="; ")
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(OUT, bodies, list(accs.values()), scopes)
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {excluded}")
