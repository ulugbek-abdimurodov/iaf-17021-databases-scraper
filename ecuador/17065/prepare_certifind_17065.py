"""Convert the SAE (Ecuador) ISO/IEC 17065 scrape into certifind/data/sae-ecuador-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_ec_sae_17065.py): sae_17065/sae_17065_raw.json (one record per accreditation) and
sae_17065/raw/sae_17065_raw.json (register scope rows, levels l4/l5/l6). Lines are the register scope rows: the
resolution PDFs only say the scope "consta en la herramienta informática" (the register), so their text is not used.
Body rows are reused from data/sae-ecuador (MS) or any other dataset through ALIASES / the common module.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "SAE", "sae-ecuador-17065", "sae-ecuador"
URL = "https://sistema.acreditacion.gob.ec/"
# SAE register name -> existing row (name, country) in another dataset.
ALIASES = {
    "ASIAM": ("ASIAMBUSINESS DEL ECUADOR S.A", "Ecuador"),                       # onac-colombia-17065, same address
    "Lenor Ecuador Cia. Ltda.": ("LENOR ECUADOR Cía. Ltda.", "Ecuador"),        # sae-ecuador
    "Control Union Services S.A.C.": ("CONTROL UNION SERVICES S.A.C.", "Peru"),  # dakks-germany-17065
    "FUNDACIÓN NATURACERTIFICACIÓN": ("Fundacion Natura Certificacion (NaturaCert)", "Colombia"),  # anab-usa-17065
    "SERVICIO DE CERTIFICACIÓN CAAE S.L.U.": ("SERVICIO DE CERTIFICACIÓN CAAE, S.L. (Unipersonal)", "Spain"),  # enac
}
COUNTRY = {"Peru": "Peru", "Colombia": "Colombia", "España": "Spain"}
# Spanish product words -> V70 industry, checked before the common keyword table.
INDUSTRY = [(re.compile(p, re.I), ind) for p, ind in [
    (r"orgánic|agrícola|cultivo|flor|banano|cacao|café|ganad|acuícol|acuicult|camar", "agriculture"),
    (r"aliment|bebida|lácte|leche|carne|azúcar|harina|aceite(s)? (comestible|vegetal)|helado|margarina|salsa|"
     r"gelatina|postre|sal para consumo|agua para consumo", "food"),
    (r"juguete|calzado|protección individual", "other_manufacturing"),
    (r"alfombra|textil", "textiles"),
    (r"neumátic|automo|vehícul|frenos|casco", "transport_equipment"),
    (r"tub(o|ería)s? .*(PVC|plástic)|plástic|caucho|PVC", "rubber_plastics"),
    (r"cosmétic|pintura|tensoactiv|tensión superficial|detergente", "chemicals"),
    (r"baldosa|cerámic|cemento|hormig|construcci|acristalamiento|vidrio|vitrocerám|sanitari", "construction"),
    (r"alambre|acero|metál|fundici|hierro|olla|válvula|llave", "metals"),
    (r"eléctric|electrodom|televis|refrigera|producción de frío|lavadora|lavavajillas|microondas|aspiradora|"
     r"ventilador|acondicionador|plancha|cortadora|afeitar|cabello|lámpara|luminar|alumbrado|guirnalda|"
     r"transformador|motor|herramienta|cocción|calentar|RETIQ|etiquetado", "electrical"),
    (r"gas\b|gaseos|gasodom|combustible|lubricante|encendedor", "energy"),
    (r"uso doméstico", "electrical"),
    (r"producción más limpia|punto verde|ambiental", "professional"),
]]


def industry(text: str) -> str:
    return next((ind for rx, ind in INDUSTRY if rx.search(text)), "") or cf.industry_of(text)


def main():
    scrape, today = cf.cli(HERE / "sae_17065")
    raw = json.load(open(scrape / "sae_17065_raw.json", encoding="utf-8"))
    scopes = json.load(open(scrape / "raw" / "sae_17065_raw.json", encoding="utf-8"))["scopes"]
    by_acc: dict[str, list[str]] = {}
    for s in scopes:  # keep register order
        text = " - ".join(cf.clean(s[k]) for k in ("l4", "l5", "l6") if s.get(k))
        if text:
            by_acc.setdefault(s["acc"], []).append(text)
    notes, bodies = [], []
    for r in raw:
        reg, name = r["registration_no"], cf.clean(r["name"])
        tail = r["address"].rsplit(",", 1)[-1].strip()
        country = COUNTRY.get(tail, "Ecuador")
        if name in ALIASES:
            name, country = ALIASES[name]
        b = cf.Body(reg=reg, name=name, country=country, phone=r["phone"] or "", email=r["email"] or "",
                    website=r["website"] or "", address=r["address"], issued=r["issued"], expiry=r["expiry"] or "",
                    proof_url=(r["annex_urls"] or [URL])[0].replace(" ", "%20"), source_url=URL,
                    active=r["status"] == "Activo", status_note=r["status"])
        for text in by_acc.get(reg, []):
            sch = cf.scheme_of(text)
            b.lines.append(cf.Line(product_text=text, scheme=sch, industry=None if sch else (industry(text) or None)))
        if not b.lines:
            notes.append(f"{reg} {name}: no scope row in the register")
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "sae_17065_review.md", today,
           sources_extra="SAE register, area CERTIFICACIÓN, activity 6 (products, ISO/IEC 17065). Lines are the "
                         "register scope rows (levels 4-6 joined with ' - '); the accreditation resolution PDFs carry "
                         "no scope (they refer to the register) and are only kept as proof_url.", pre_notes=notes)


if __name__ == "__main__":
    main()
