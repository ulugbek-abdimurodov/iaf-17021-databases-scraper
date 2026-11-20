"""Convert the ECA (Costa Rica) ISO/IEC 17065 scrape into certifind/data/eca-costa-rica-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Bodies: eca_17065/eca_17065_raw.json (scrape_cr_eca_17065.py, register detail pages; accreditation has no expiry).
Lines: annex_transcription.csv (make_annex_transcription.py, hand transcription of the 12 scope PDFs).
Body rows are reused from data/eca-costa-rica (MS) or any other dataset through ALIASES / the common module.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "ECA", "eca-costa-rica-17065", "eca-costa-rica"
URL = "https://eca.or.cr/organismos-de-certificacion-de-productos/"
# Register name -> (name, country). Names of bodies already in another dataset are copied from there.
ALIASES = {
    "OCP-002": ("Asociación Instituto de Normas Técnicas de Costa Rica (INTECO)", "Costa Rica"),   # eca-costa-rica
    "OCP-008": ("Eco-LÓGICA", "Costa Rica"),                                                      # caeq-canada-17065
    "OCP-010": ("Primus Auditing Operations de Costa Rica S.A.", "Costa Rica"),
    "OCP-011": ("ASOCIACIÓN DE NORMALIZACIÓN Y CERTIFICACIÓN, S.A. DE C.V.", "Mexico"),          # ema-mexico
    "OCP-012": ("UL de México, S.A. de C.V.", "Mexico"),                                          # ema-mexico-17065
    "OCP-013": ("Kiwa BCS Costa Rica Limitada", "Costa Rica"),
    "OCP-014": ("ACI Auditoría y Consultoría Integral S.A.", "Costa Rica"),
    "OCP-015": ("CSA Group Korea Ltd.", "South Korea"),   # register "CSA Group."; annex: Sede CSA Group Korea Ltd.
    "OCP-018": ("Mina Lu Certification S. de R.L.", "Honduras"),
    "OCP-021": ("BIOMATEC", "Costa Rica"),
    "OCP-022": ("Cámara de Industrias de Costa Rica – Área de Evaluación de la Conformidad (CICR-AEC)", "Costa Rica"),
    "OCP-023": ("Kire Certifications S.A.", "Costa Rica"),
}


def main():
    scrape, today = cf.cli(HERE / "eca_17065")
    raw = json.load(open(scrape / "eca_17065_raw.json", encoding="utf-8"))
    lines: dict[str, list[dict]] = {}
    with open(HERE / "annex_transcription.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lines.setdefault(r["registration_no"], []).append(r)
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        name, country = ALIASES[reg]
        if name != r["name"]:
            notes.append(f"{reg}: register name '{r['name']}' recorded as '{name}' ({country})")
        site = "" if r["website"].lower().startswith("no ind") else r["website"]
        b = cf.Body(reg=reg, name=name, country=country, phone=r["phone"], email=r["email"], website=site,
                    address=r["address"], issued=r["issued"], expiry=r.get("expiry") or "",
                    proof_url=(r.get("annex_urls") or [URL])[0], source_url=URL)
        for ln in lines.get(reg, []):
            b.lines.append(cf.Line(product_text=ln["product_text"], normative_docs=ln["normative_docs"],
                                   scheme=ln["scheme"] or "", industry=ln["industry"] or None))
        if not b.lines:
            notes.append(f"{reg} {name}: no transcribed line")
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "eca_17065_review.md", today,
           sources_extra="Scope lines are a hand transcription of the 12 annex PDFs (annex_transcription.csv, "
                         "make_annex_transcription.py): one line per product entry, normative documents of the entry "
                         "in normative_docs; internal procedures and the ISO/IEC 17067 scheme type column left out. "
                         "Accreditation has no expiry (ECA: indefinite, subject to surveillance).", pre_notes=notes)


if __name__ == "__main__":
    main()
