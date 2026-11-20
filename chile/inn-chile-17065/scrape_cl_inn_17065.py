"""INN Chile scraper - Product Certification Bodies (ISO/IEC 17065).

Same register as the MS scraper (database/chile/scrape_cl_inn.py): directorio.inn.cl is reachable only
from a browser session (DataTables POST /Directorio/retorna_lista_acreditados). Run in the browser console
on https://directorio.inn.cl/:
  T=$('#tabla_directorio_acreditados').DataTable(); T.page.len(5000).draw();
  rows=T.rows().data().toArray().filter(x=>/Certificaci.n de Productos/.test(x.NOMBRE_TIPO_OEC))
(filter value: NOMBRE_TIPO_OEC = "Organismos de Certificación de Productos"; the MS one is "...de Sistemas")
and export CODIGO_ACREDITACION, NOMBRE_FANTASIA, COMUNA, NOMBRE_AREA_ACREDITACION, TELEFONO,
FECHA_VIGENCIA_DESDE, FECHA_VIGENCIA_HASTA, NOMBRE_ESTADO_ACREDITACION, DOCUMENTO_ENCRYPT
as TSV to inn_17065_raw.tsv. Column 9 (DOCUMENTO_ENCRYPT) may be empty; when filled, the certificate PDF is
https://directorio.inn.cl/Directorio/DisplayPDF/<token> (downloaded unless --no-files, and only from a host
that can reach the site).

Writes inn_17065_raw.json and scope_lines.csv for prepare_certifind_17065.py.
"""
import argparse, csv, json, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
PDF = "https://directorio.inn.cl/Directorio/DisplayPDF/"

# INN area (NOMBRE_AREA_ACREDITACION) -> (category, sector, CertiFind industry)
AREAS = {
    "Productos para combustibles": ("Fuel products", "Energy / fuels", "energy"),
    "Productos eléctricos": ("Electrical products", "Electrical", "electrical"),
    "Estanques para sustancias peligrosas": ("Hazardous substance tanks", "Pressure & storage equipment", "machinery"),
    "Recipientes e instalaciones industriales": ("Industrial vessels and installations", "Pressure & storage equipment", "machinery"),
    "Materiales de construcción": ("Construction materials", "Construction", "construction"),
    "Materiales para obras e instalaciones sanitarias": ("Sanitary installation materials", "Construction", "construction"),
    "Extintores": ("Fire extinguishers", "Fire safety", "machinery"),
    "Servicios técnico de extintores": ("Fire extinguisher servicing", "Fire safety", "machinery"),
    "Dispositivos de protección contra incendio": ("Fire protection devices", "Fire safety", "machinery"),
    "Pecuaria": ("Livestock / meat", "Agriculture & food", "agriculture"),
    "Agricultura orgánica": ("Organic agriculture", "Agriculture & food", "agriculture"),
    "Forestal": ("Forestry", "Forestry", "wood_paper"),
    "Elementos de protección personal": ("Personal protective equipment", "Safety products", "other_manufacturing"),
    "Artículos para Seguridad de Vehículos de Carretera": ("Road vehicle safety articles", "Safety products", "transport_equipment"),
    "Insumos médicos": ("Medical supplies", "Medical", "health"),
    "Servicios Turísticos": ("Tourism services", "Services", "tourism"),
}


def classify(area: str):
    return AREAS.get(area.strip(), ("", "", ""))


def main():
    ap = argparse.ArgumentParser(description="INN Chile product certification bodies (ISO/IEC 17065)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.reader(open(HERE / "inn_17065_raw.tsv", encoding="utf-8"), delimiter="\t") if r]
    rows = [(r + [""] * 9)[:9] for r in rows]  # token column may be blank/stripped
    assert all(len(r[0]) and len(r[1]) for r in rows), "bad row"
    rows = rows[: a.limit] if a.limit else rows

    recs, lines, ok, fail = [], [], 0, 0
    for code, name, comuna, area, tel, f, t, status, tok in rows:
        url = PDF + tok if tok else ""
        cat, sec, _ = classify(area)
        if not cat:
            print(f"Unmapped area {code}: {area}")
        recs.append(dict(registration_no=code, id=code.replace(" ", ""), name=name, address=comuna, phone=tel,
                         email="", website="", issued=f, expiry=t, status=status, area=area, category=cat,
                         sector=sec, annex_urls=[url] if url else []))
        lines.append(dict(registration_no=code, source="register", row_index=0, product_text_raw=area,
                          category=cat, sector=sec))
        if url and not a.no_files:
            dest = out / "pdf" / f"{code.replace(' ', '')}.pdf"
            if dest.exists():
                ok += 1; continue
            dest.parent.mkdir(exist_ok=True)
            try:
                dest.write_bytes(urllib.request.urlopen(url, timeout=60).read()); ok += 1
            except Exception as e:
                fail += 1; print(f"PDF fail {code}: {e}")

    json.dump(recs, open(out / "inn_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw", "category", "sector"])
        w.writeheader(); w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in recs})}  Accreditations: {len(recs)}  "
          f"Scope lines: {len(lines)}  PDFs ok/failed: {ok}/{fail}")


if __name__ == "__main__":
    main()
