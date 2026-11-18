"""EGAC ISO/IEC 17065 scrape -> CertiFind dataset (data/egac-egypt-17065).

Usage: python prepare_certifind_17065.py <scrape out dir> <dataset dir> [--today YYYY-MM-DD]

The register's scope tree is EGAC's full product catalogue (identical 310 nodes for every body), so it is NOT
used as scope. Scope comes from annex_transcription.csv, transcribed from the annex PDFs (8 of 14 active
annexes are scans). Scheme and industry are classified by hand in that file and validated here.
Only bodies listed as "Accredited" are imported (withdrawn / expired are logged).
"""
import csv, re, sys, os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SCRAPE, OUT = args[0], args[1]
TODAY = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else datetime.now().strftime("%Y-%m-%d")
DATA = os.path.dirname(os.path.abspath(OUT))

SCHEMES = {"EU Organic Regulation (EU) 2018/848", "GLOBALG.A.P. IFA", "ISO 3834", "EN 15085-2",
           "Gas Appliances Regulation (EU) 2016/426"}
INDUSTRIES = set("agriculture food textiles wood_paper chemicals rubber_plastics construction metals machinery "
                 "electrical transport_equipment other_manufacturing energy trade_logistics tourism ict professional "
                 "public_education health".split())
# Body rows reused verbatim from data/egac-egypt (MS dataset): register ref -> body name there.
REUSE = {"062204": "Bureau Veritas Egypt", "0626001": "INFINITY CERT INTERNATIONAL ICI", "062505": "IEMA STANDARDS LTD"}
REF = re.compile(r"\b(?:(EN)\s*)?(ISO/IEC|ISO|IEC|EN|ES\.?|ASTM|OIML[ -]?R|OIML[ -]?D|CISPR)\s*([A-Z]?\d{1,5}(?:-\d{1,3})?)")

def date(s):
    return datetime.strptime(s.strip(), "%d %b %Y").strftime("%Y-%m-%d") if s.strip() else ""

def phone(p):
    p = re.sub(r"^\+(\d+) 0", r"+\1 ", p.strip())
    return p if re.fullmatch(r"\+\d[\d -]{6,}", p) else ""

def refs(text):
    out = []
    for en, kind, num in REF.findall(text):
        kind = kind.rstrip(".").replace("-", " ")
        kind = re.sub(r"OIML ?([RD])", r"OIML \1", kind)
        r = f"{'EN ' if en else ''}{kind} {num}"
        if r not in out: out.append(r)
    return ";".join(out)

def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))

def write(name, cols, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols, lineterminator="\n"); w.writeheader(); w.writerows(data)

ms_bodies = {r["name"]: r for r in rows(os.path.join(DATA, "egac-egypt", "bodies.csv"))}
cabs = rows(os.path.join(SCRAPE, "cabs.csv"))
lines = rows(os.path.join(HERE, "annex_transcription.csv"))
notes, skipped = [], []

bodies, accs, ps = [], [], []
active = {}
for c in cabs:
    ref = c["reference_no"].rstrip(".")
    if c["listed_status"] != "Accredited":
        skipped.append(f"- {ref} {c['name']}: {c['listed_status']} (not imported)"); continue
    if ref in REUSE:
        b = dict(ms_bodies[REUSE[ref]]); notes.append(f"- {ref}: body row reused from egac-egypt (`{b['name']}`)")
    else:
        country = {"Russia": "Russia", "China": "China", "Nigeria": "Nigeria"}.get(c["country"], c["country"])
        b = {"name": c["name"].strip(), "country": country, "registration_no": "", "phone": phone(c["Phone No."]),
             "email": c["Email"].strip().lower(), "website": c["Website"].strip(), "address": re.sub(r",\s*,", ",", c["Address"].strip()),
             "source_url": c["detail_url"], "verified_at": TODAY}
        if c["Phone No."] and not b["phone"]: notes.append(f"- {ref}: phone `{c['Phone No.']}` invalid, left empty")
    bodies.append(b); active[ref] = b["name"]
    accs.append({"ab_code": "EGAC", "certificate_number": ref, "body_name": b["name"],
                 "accreditation_standard": "ISO/IEC 17065", "status": "ACTIVE",
                 "issue_date": date(c["accreditation_date"]), "expiry_date": date(c["expiry_date"]),
                 "proof_url": c["detail_url"]})

for l in lines:
    assert l["registration_no"] in active, l["registration_no"]
    assert not l["scheme"] or l["scheme"] in SCHEMES, l["scheme"]
    assert l["scheme"] or l["industry"] in INDUSTRIES, (l["registration_no"], l["line_no"])
    ps.append({"certificate_number": l["registration_no"], "line_no": l["line_no"], "scheme": l["scheme"],
               "industry": "" if l["scheme"] else l["industry"], "product_text": " ".join(l["product_text"].split()),
               "product_text_en": "", "scheme_text": " ".join(l["scheme_text"].split()),
               "normative_docs": " ".join(l["normative_docs"].split()),
               "standard_refs": refs(l["scheme_text"] + " " + l["normative_docs"]), "status": "ACTIVE"})
missing = set(active) - {p["certificate_number"] for p in ps}
assert not missing, missing

os.makedirs(OUT, exist_ok=True)
write("bodies.csv", list(bodies[0]), bodies)
write("accreditations.csv", list(accs[0]), accs)
write("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
write("product_scopes.csv", list(ps[0]), ps)

from collections import Counter
sc = Counter(p["scheme"] or f"(text) {p['industry']}" for p in ps)
with open(os.path.join(HERE, "egac_17065_review.md"), "w", encoding="utf-8") as f:
    f.write("# EGAC ISO/IEC 17065 - review\n\nGenerated by `prepare_certifind_17065.py`.\n\n"
            "## Register scope tree ignored\n\nThe register's scope tree (310 nodes) is identical for all 20 bodies: it is "
            "EGAC's product catalogue, not a body's scope. Lines come from `annex_transcription.csv` (annex PDFs; 8 of 14 "
            "active annexes are scans, transcribed from images).\n\n## Bodies not imported\n\n" + "\n".join(skipped) +
            "\n\n## Notes\n\n" + "\n".join(notes) +
            "\n- 061901 (EOS-CB): the annex PDF (619001B) says valid to 2025-04-08, the register says 2029-04-08; register used.\n"
            "- 062301 (WSCT): annex rows 19 and 22 are the same (scooters); imported once.\n"
            "- Schemes left as text: SASO / GSO technical regulations, Egyptian ES standards, in-house schemes, Proudly Made "
            "in Egypt (national); Demeter, Economy of Love, ISO 22716 cosmetics GMP, OIML (one body each, not in catalogue).\n\n"
            "## Lines by scheme / industry\n\n" + "\n".join(f"- {k}: {v}" for k, v in sc.most_common()) + "\n")
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nProduct lines (with scheme): {len(ps)} "
      f"({sum(1 for p in ps if p['scheme'])})\nNot imported bodies: {len(skipped)}")
