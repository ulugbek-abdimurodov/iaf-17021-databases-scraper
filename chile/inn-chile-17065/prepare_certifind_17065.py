"""Convert the INN (Chile) ISO/IEC 17065 scrape into certifind/data/inn-chile-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_cl_inn_17065.py): inn_17065_raw.json, one entry per INN accreditation (CP xxx / ST xxx). INN's
export carries no annex tokens, so each accreditation gives one product line: the register's accreditation area
(Spanish, verbatim), with the industry from the scraper's AREAS map. A body with several areas keeps one
accreditation (the first number) and one line per area (merged by the common module, uq_cb_ab_standard).
Body rows are reused from data/inn-chile (MS) or any other dataset when the name matches.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import certifind_17065_common as cf  # noqa: E402
from scrape_cl_inn_17065 import classify  # noqa: E402

AB, FOLDER, MS = "INN", "inn-chile-17065", "inn-chile"
URL = "https://directorio.inn.cl/"
# Same spellings as the MS dataset (data/inn-chile); truncated / misspelt register names expanded.
NAMES = {"SGS CHILE LTDA.": "SGS Chile Ltda.",
         "Bureau Veritas Certification Chile S.A": "Bureau Veritas Certification Chile S.A.",
         "SCI CERTIFICACIONES LIMITADA": "SCI Certificaciones Limitada",
         "Centro de estudios medición y certificación de cal":
             "Centro de Estudios, Medición y Certificación de Calidad (CESMEC)",
         "Sociedad de ingenerÍa y certificación de calidad S.A.": "Sociedad de Ingeniería y Certificación de Calidad S.A.",
         "5M SpA.": "5M SpA",
         # Botucatu/SP (area code 14), same body as in data/anab-usa-17065.
         "SBC BRASIL": "SBC - Servico Brasileiro de Certificacoes"}


def iso(s: str) -> str:
    return datetime.strptime(s, "%d-%m-%Y").strftime("%Y-%m-%d") if s else ""


def main():
    scrape, today = cf.cli(HERE)
    raw = json.load(open(scrape / "inn_17065_raw.json", encoding="utf-8"))
    notes, bodies = [], []
    for r in raw:
        name = NAMES.get(r["name"].strip(), r["name"].strip())
        # The register gives a Chilean commune only; bodies without one and with a +55 phone are Brazilian.
        country = "Brazil" if not r["address"] and r["phone"].startswith("+55") else "Chile"
        if not r["address"]:
            notes.append(f"{r['registration_no']} {name}: no commune in the register; country {country} from the phone")
        expiry = iso(r["expiry"])
        active, why = r["status"] == "Vigente", r["status"]
        if active and expiry and expiry < today:
            active, why = False, f"expired {expiry} (register still says Vigente)"
        b = cf.Body(reg=r["registration_no"], name=name, country=country, phone=r["phone"],
                    address=f"{r['address']}, {country}" if r["address"] else "", issued=iso(r["issued"]),
                    expiry=expiry, proof_url=(r["annex_urls"] or [URL])[0], source_url=URL,
                    active=active, status_note=why)
        b.lines.append(cf.Line(product_text=r["area"], scheme="", industry=classify(r["area"])[2] or None))
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "inn_17065_review.md", today,
           sources_extra="INN directory export (no annex PDFs: DOCUMENTO_ENCRYPT tokens missing); one line per "
                         "accreditation = the register's accreditation area.", pre_notes=notes)


if __name__ == "__main__":
    main()
