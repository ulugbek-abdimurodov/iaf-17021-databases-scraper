"""Convert the SOAC-WAAS ISO/IEC 17065 scrape into certifind/data/soac-west-africa-17065/.
Usage: python prepare_certifind_17065.py [--today YYYY-MM-DD]
Input: soac_17065/raw.json (register + attestation page data). The annexes are one short table each
(a handful of lines), so scope lines are listed below, transcribed from soac_17065/annex_text/*.txt.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "SOAC", "soac-west-africa-17065", "soac-cote-divoire"
URL = "https://soacwaas.org/en/oec/referentiel/CERTIFICATION_DE_PRODUITS_DE_PROCEDES_ET_DE_SERVICES"
FR = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
      "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}
NAME = {"ATT-00151787734496": "BUREAU NORME AUDIT (BNA)",  # same entity as the MS row CS20001
        "ATT-28691764596525": "BUREAU DE CONFORMITE A LA DURABILITE (BCD)",
        "ATT-09261764596594": "AGENCE BURKINABE DE NORMALISATION DE LA METROLOGIE ET DE LA QUALITE (ABNORM) - CERTIFICATION",
        "ATT-00251790984018": "GLOBAL SUSTAIN CERTIFICATION (GSC)",
        "ATT-59521785498182": "SGS COTE D’IVOIRE SA - CERTIFICATION PRODUIT"}
WEB = {"ATT-00151787734496": "www.bna-groupe.org", "ATT-00251790984018": "gsc-corporate.org",
       "ATT-59521785498182": "www.sgs.ci"}
PHONE = {"ATT-09261764596594": "+226 25 37 14 43", "ATT-28691764596525": "+225 07 47 44 48 27", "ATT-00151787734496": "+225 27 22 42 62 18", "ATT-59521785498182": "+225 27 21 75 22 00"}
L = cf.Line
LINES = {  # product_text = category, scheme_text = certification programme (verbatim, English half where bilingual)
    "ATT-00151787734496": [
        L("Productions végétales / plants", "GLOBALG.A.P. General Regulations Version 6.0", scheme="GLOBALG.A.P. IFA"),
        L("Productions végétales / plants", "Principles and criteria IFA v 6 SMART for fruit and vegetables", scheme="GLOBALG.A.P. IFA"),
        L("Productions végétales / plants", "Principles and criteria IFA v6 SMART for flowers and ornamentals", scheme="GLOBALG.A.P. IFA"),
        L("Productions végétales / plants", "Principles and criteria IFA v6 SMART for hops", scheme="GLOBALG.A.P. IFA")],
    "ATT-28691764596525": [L("Cacao", "Série ARS 1000 (ARS 1000-1, ARS 1000-2, ARS 1000-3) pour le cacao durable", scheme="", industry="food")],
    "ATT-09261764596594": [L("Mangue séchée", "Abnorm-AUD-006-Règlement de Certification du Produit - Mangues séchées / ECOSTAND 100:2022 - Mangues séchées – Spécifications", scheme="", industry="food")],
    "ATT-00251790984018": [L("Cacao", "Série ARS 1000 (ARS 1000-1, ARS 1000-2, ARS 1000-3) pour le cacao durable", scheme="", industry="food")],
    "ATT-59521785498182": [L("Cacao", "Rainforest Alliance Sustainable Agriculture Standard 2020 – Farm Requirements (Version 1.4)", scheme="", industry="food")],
}


def iso(fr):
    d, m, y = fr.split()
    return f"{int(y):04d}-{FR[m.lower()]:02d}-{int(d):02d}"


raw = json.loads((HERE / "soac_17065/raw.json").read_text("utf-8"))
bodies = []
for r in raw:
    if r.get("status") != "ACCREDITED":
        continue
    country = cf.country_name(r["country_city"].split("/")[0].strip().replace("'", "’"))
    reg = re.sub(r"^N°|\s+version.*", "", r["certificate_no"])
    b = cf.Body(reg=reg, name=NAME[r["attestation_id"]], country=country,
                phone=PHONE.get(r["attestation_id"], r["phone"]), email=r["email"],
                website=WEB.get(r["attestation_id"], ""), address=", ".join(x for x in [r["address"], r["mailbox"]] if x),
                issued=iso(r["start_date"]), expiry=iso(r["end_date"]), proof_url=r["source_url"], source_url=URL)
    b.lines = LINES[r["attestation_id"]]
    bodies.append(b)

today = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else cf.date.today().isoformat()
cf.run(AB, FOLDER, MS, URL, bodies, HERE / "soac_17065_review.md", today)

# new body rows carry the accreditation number as registration_no (reused rows keep theirs)
import csv  # noqa: E402
p = cf.DATA / FOLDER / "bodies.csv"
rows = list(csv.DictReader(open(p, encoding="utf-8", newline="")))
regs = {b.name: b.reg for b in bodies}
for r in rows:
    r["registration_no"] = r["registration_no"] or regs.get(r["name"], "")
with open(p, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cf.BODY_COLS); w.writeheader(); w.writerows(rows)
