#!/usr/bin/env python3
"""OUA (Uruguay) 17065 scrape (raw_oua_17065.json) -> certifind/data/oua-uruguay-17065.

One OUAIMP034 scope PDF per body. Header: body name (line 2), address (line with 'Uruguay'), accreditation
cycle ("Ciclo de Acreditación dd.mm.yyyy al dd.mm.yyyy"). Scope: the PDF text lines after "DETALLE DEL ALCANCE"
and its revision lines, without repeated table headers and page footers. The register publishes no certificate
number for product bodies, so the certificate number is "OCP <acronym>" (from the PDF file name).
Usage: python prepare_certifind_17065.py [raw_json] [--today YYYY-MM-DD]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

RAW, TODAY = c.cli(HERE / "raw_oua_17065.json")
PAGE = "https://www.organismouruguayodeacreditacion.org/organismos-de-certificacion-de-productos-ocp/"
# names used by the existing oua-uruguay dataset, so the body row is reused
NAMES = {"UNIT": "Instituto Uruguayo de Normas Técnicas (UNIT)"}
SKIP = re.compile(r"^(OUAIMP034|Nº REVISI|N° REVISI|FECHA DE REVISI|DETALLE DEL ALCANCE|Producto / Proceso|Servicio\b|"
                  r"Esquema / Sistema de Certificaci|Norma de Certificaci|Ing\. |Directora Ejecutiva|Página|\d+ de \d+$)", re.I)
bodies = []
for doc in json.loads(RAW.read_text(encoding="utf-8")):
    if doc["kind"] != "scope":
        continue
    L = [c.clean(x) for x in doc["lines"]]
    acr = re.match(r"OUAIMP034-(.+?)-(?:OCP-)?[Aa]lcance", doc["file"]).group(1).replace("-", " ")
    name = NAMES.get(acr, L[1].title() if L[1].isupper() else L[1])
    addr = next((x for x in L[2:5] if "Uruguay" in x), "")
    cyc = next((x for x in L if x.startswith("Ciclo de Acreditaci")), "")
    d = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", cyc)
    b = c.Body(reg=f"OCP {acr}", name=name, country="Uruguay", address=re.sub(r"\s*[,–-]\s*Uruguay$", "", addr),
               issued=f"{d[0][2]}-{d[0][1]}-{d[0][0]}" if d else "", expiry=f"{d[1][2]}-{d[1][1]}-{d[1][0]}" if len(d) > 1 else "",
               proof_url=doc["url"], source_url=PAGE)
    start = next((i for i, x in enumerate(L) if x.startswith("DETALLE DEL ALCANCE")), len(L))
    for x in L[start + 1:]:
        if not SKIP.match(x):
            b.lines.append(c.Line(product_text=x))
    bodies.append(b)
c.run("OUA", "oua-uruguay-17065", "oua-uruguay", PAGE, bodies, HERE / "oua_17065_review.md", TODAY,
      "OUA page 'Organismos de Certificación de Productos (OCP)' and each body's scope PDF (OUAIMP034, text layer). "
      "Scraper `database/uruguay/17065/scrape_uy_oua_17065.py`; converter `prepare_certifind_17065.py`. Scope lines "
      "are PDF text lines (table rows may be split over several lines).")
