"""Hand transcription of the 12 ECA ISO/IEC 17065 scope annexes (eca_17065/pdfs/, read 2026-11-19).

The annex tables wrap every cell over many rows and interleave three columns, so they are transcribed here instead
of parsed. One line per product entry (NACE level II row); normative_docs lists that entry's normative and regulatory
documents (internal procedures and the ISO/IEC 17067 scheme type column left out). CSA's Korea and China sites have
the same scope and are transcribed once. Writes annex_transcription.csv next to this file.
"""
import csv
from pathlib import Path

ORG = ("Proceso de producción orgánica, el cual incluye: - Tipo de producción: Producción a nivel individual o producción "
       "en Grupos de Productores Organizados (GPO) - Actividades del proceso de producción: Producción, Procesamiento, "
       "Empaque y envasado, Etiquetado, Comercialización, Exportación, Importación")
MAG = ("Decreto Ejecutivo N° 29782-MAG Reglamento de agricultura orgánica; Decreto Ejecutivo N° 9621-MAG Esquema de "
       "Certificación para la Producción de Producto Orgánico Versión I-2018 SFE")
EU = "Reglamento (UE) 2018/848: normas sobre producción ecológica y etiquetado de los productos ecológicos"
EUS = "EU Organic Regulation (EU) 2018/848"
MP_P = ("Evaluación de indicadores de excelencia, sostenibilidad, progreso social, innovación y vínculo costarricense, "
        "aplicado a empresas relacionadas con atracción de inversiones, exportaciones, PYMES exportadoras o con "
        "potencial exportador y el comercio exterior en general")
MP_N = ("Reglamento para el uso de la Marca País Costa Rica, PRO-NOR-044, versión vigente; Anexo 1 del Reglamento para "
        "el uso de la Marca País Costa Rica, PRO-NOR-044: Protocolo de evaluación para uso corporativo Marca País "
        "Esencial Costa Rica")
EA = ("Acuerdo 009-2022 - MINAE - Programa Nacional de Etiquetado Ambiental y Eficiencia Energética de Costa Rica; "
      "INTE B8:2017 Requisitos Generales del Programa Nacional de Etiquetado Ambiental Tipo I")
B13 = ("INTE B13:2020/COR 1:2024 Etiquetado Ambiental Tipo I. Criterios ambientales para productos de limpieza de uso "
       "general y productos de limpieza de cocinas y baños")
SOAP = ("20.41 – Fabricación de jabones y detergentes, productos de limpieza y abrillantamiento, sujetos a certificación "
        "de Etiquetado Ambiental Tipo I")
D37662 = ("Decreto Ejecutivo N° 37662-MEIC-H-MICIT. Procedimiento para la demostración de la evaluación de la "
          "conformidad de los Reglamentos Técnicos, con su modificación en enero 2017")
FRIDGE = "27.5 Fabricación de aparatos domésticos – refrigeradores y congeladores electrodomésticos"
RTCA_F = ("RTCA 97.01.81:22 - Productos eléctricos. Refrigeradores y congeladores electrodomésticos. "
          "Especificaciones de eficiencia energética")
E11 = ("Norma INTE E11-1:2021 Eficiencia energética. Refrigeradores y congeladores electrodomésticos. Parte 1: "
       "Requisitos; Norma INTE E11-2:2021 Parte 2: Etiquetado; Norma INTE E11-3:2021 Parte 3: Métodos de ensayo")
R78 = ("RTCA 23.01.78:20 Productos eléctricos. Acondicionadores de aire tipo dividido inverter, con flujo de "
       "refrigerante variable, descarga libre y sin ductos de aire. Especificaciones de eficiencia energética")
R80 = ("RTCA 23.01.80:21 Productos eléctricos. Acondicionadores de aire tipo dividido de velocidad fija, descarga libre "
       "y sin ductos de aire. Especificaciones de eficiencia energética")
AC_ND = "28.25 Fabricación de maquinaria de ventilación y refrigeración no doméstica – Aires acondicionados"
E17_24 = ("INTE E17-1:2024 Eficiencia energética. Cocinas eléctricas, plantillas, plantillas de inducción y hornos "
          "eléctricos de uso doméstico. Parte 1: Requisitos; INTE E17-2:2024 Parte 2: Etiquetado; INTE E17-3:2024 "
          "Parte 3: Métodos de ensayo")
R503 = ("RTCR 503:2021 Productos eléctricos. Cocinas, plantillas, encimeras, plantillas de inducción y hornos "
        "eléctricos de uso doméstico. Requisitos de eficiencia energética")

# (registration_no, product_text, scheme, normative_docs, industry)
ROWS = [
    ("OCP-002", "22.1 Fabricación de neumáticos y cámaras de caucho, reconstrucción y recauchado", "",
     "ASTM C 443; NTE INEN 2 099; RTE INEN 011 (4R); INTE-ISO 10191-2015; INTE-ISO 4000-1:2015; NTE INEN 2 099:2013; "
     "NTE INEN 2097:2012; NTE INEN 2101:98; RTE INEN 011 (1R); IRAM 113320:2001; NM250:2001; COVENIN 663:1996; "
     "Regulation NR.5:2000 (Brasil); Decreto 019-2005 (Perú); NOM-086-SCFI-2011; JS 244:2006; ISO 4000-1:2013; "
     "ISO 10191:2010; INTE-ISO 4209-1:2002; NTE INEN 2 098:98; NTE INEN 2 100:2013; NTC 1303:2013; "
     "IRAM 113321:2001; NM 251:2001; COVENIN 1352:1997; NOM-086/1-SCFI-2011; JS 269:2006; ISO 4209-1:2001; "
     "ISO 10454:1993; TTS 266:2002; TTS 536:1997; FMVSS 571.139; FMVSS 571.1093; FMVSS 571.119; "
     "RTCR 486:2016 Reglamento Técnico para Llantas Neumáticas", "rubber_plastics"),
    ("OCP-002", "22.2 Fabricación de productos de plástico: Empaques", "",
     "IRAM 113035; ASTM F 477; AWWA C 901; INTE C-180:2018 Especificación de los sellos elastoméricos (empaques) "
     "para juntas en tuberías plásticas", "rubber_plastics"),
    ("OCP-002", "22.2 Fabricación de productos de plástico: tubos, tubería plástica", "",
     "ASTM D 1785; ASTM D 2241-20; AWWA C 900; INTE C173:2021; INTE C175:2021; INTE C201:2011; INTE C191-1:2005; "
     "INTE C191-2:2006; INTE C174:2020; INTE C189:2018; ASTM D 2466-21; INTE C178:2022; ASTM D2665-20; "
     "AASTHO M304-11; INTE C224:2021; ASTM F 949-20; ASTM D3034-24; INTE C202:2020; AASHTO M 294-18; "
     "INTE C203:2019; AASHTO M 252-18; INTE C206:2021; ASTM F2947/F2947M-25", "rubber_plastics"),
    ("OCP-002", "23.5 Fabricación de cemento, cal y yeso: Cemento y Láminas de Fibrocemento", "",
     "ASTM C 1157 C1157M-20A; RTCR 491:2017 Materiales de Construcción. Láminas de Fibrocemento; ISO 8336:2017; "
     "INTE-ISO 8336:2018; RTCR 479:2015 Materiales de Construcción. Cementos Hidráulicos; INTE C147:2026; "
     "RTCR 476:2015; NCR 193; INTE C500:2021", "construction"),
    ("OCP-002", "24.1 Fabricación de productos básicos de hierro, acero y ferroaleaciones: Barras de acero lisas y "
     "corrugadas; Alambre electrosoldado", "",
     "RTCR 452:2011 Barras y Alambres de Acero de Refuerzo para concreto; INTE C 400:2023; ASTM A615/A615M; "
     "INTE C 401:2025; ASTM A706/A706M-24; INTE C402:2025; ASTM A1064/A1064M-24", "metals"),
    ("OCP-002", MP_P, "", MP_N, "professional"),
    ("OCP-008", ORG, "", MAG, "agriculture"),
    ("OCP-010", ORG, "", MAG, "agriculture"),
    ("OCP-011", "27.3 Fabricación de cables y dispositivos de cableado: extensiones eléctricas; cables conductores de "
     "cobre o aluminio, conductores eléctricos aislados; cables, trenzas y similares de cobre o aluminio, sin aislar "
     "para electricidad", "",
     "RTCR 475:2015. Productos eléctricos. Conductores y Extensiones Eléctricas. Especificaciones, Nº 39377-MEIC; "
     + D37662, "electrical"),
    ("OCP-011", FRIDGE, "", RTCA_F + "; NOM-015-ENER-2018; " + E11 + "; " + D37662, "electrical"),
    ("OCP-011", "27.4 Fabricación de lámparas y aparatos eléctricos de iluminación – lámparas fluorescentes "
     "compactas y circulares", "",
     "INTE E12-1:2019 Eficiencia energética. Lámparas fluorescentes compactas y circulares. Parte 1. Requisitos",
     "electrical"),
    ("OCP-011", "27.4 Fabricación de lámparas y aparatos eléctricos de iluminación – lámparas fluorescentes "
     "lineales (LFL)", "",
     "INTE E22-1:2020 Eficiencia energética. Lámparas fluorescentes lineales (LFL) Parte 1. Requisitos", "electrical"),
    ("OCP-011", "27.4 Fabricación de lámparas y aparatos eléctricos de iluminación – lámparas LED para iluminación "
     "general", "",
     "INTE E16-1:2019 Eficiencia energética. Lámparas de diodos emisores de luz (LED) para iluminación general. "
     "Parte 1. Requisitos", "electrical"),
    ("OCP-011", "27.9 Fabricación de otro material eléctrico: disyuntores termomagnéticos (incl. GFCI), interruptores "
     "unipolares, reguladores de intensidad (dimmers), tomacorrientes, enchufes y conectores de uso general, "
     "tomacorrientes GFCI", "",
     "RTCR 497:2018 Materiales eléctricos. Tableros y disyuntores termomagnéticos, interruptores de uso general, "
     "tomacorrientes, enchufes y conectores de cordón, para ser usados con tensiones de hasta 1000 V. N° 41925-MEIC",
     "electrical"),
    ("OCP-011", "27.51 Fabricación de electrodomésticos – cocinas, plantillas, encimeras, plantillas de inducción y "
     "hornos eléctricos", "",
     R503 + "; INTE E17-1 2017, INTE E17-2 2017, INTE E17-3 2017, INTE E17-4 2017, INTE E17-5 2017; " + E17_24
     + "; INTE E17-4:2017/Enm 1:2024; INTE E17-5:2017/ENM 1:2024", "electrical"),
    ("OCP-011", AC_ND + " (tipo dividido inverter)", "", R78 + "; NOM-026-ENER-2015", "machinery"),
    ("OCP-011", AC_ND + " (tipo dividido de velocidad fija)", "", R80 + "; NOM-023-ENER-2018", "machinery"),
    ("OCP-012", FRIDGE, "", RTCA_F + "; Decreto No. 44855 Reglamento Complemento para la Aplicación del RTCA "
     "97.01.81:22; " + E11 + "; " + D37662, "electrical"),
    ("OCP-012", "27.51 Fabricación de aparatos domésticos – Aires acondicionados", "", R78 + "; " + R80, "electrical"),
    ("OCP-012", AC_ND, "", R80, "machinery"),
    ("OCP-013", ORG, "", MAG, "agriculture"),
    ("OCP-013", ORG, EUS, EU, ""),
    ("OCP-014", MP_P, "", MP_N, "professional"),
    ("OCP-014", SOAP, "", EA + "; " + B13, "chemicals"),
    ("OCP-014", "28.25 – Fabricación de equipos de refrigeración y ventilación, sujetos a certificación de "
     "Etiquetado Ambiental Tipo I", "",
     EA + "; INTE B50:2021 Etiquetado Ambiental Tipo I. Criterios ambientales para aires acondicionados", "machinery"),
    ("OCP-015", FRIDGE, "", RTCA_F + "; Decreto Ejecutivo N.° 44855-MINAE; " + E11 + "; " + D37662
     + "; NOM-015-ENER-2018 Eficiencia energética de refrigeradores y congeladores electrodomésticos", "electrical"),
    ("OCP-015", "27.5 Fabricación de aparatos domésticos – cocinas, plantillas, encimeras, plantillas de inducción y "
     "hornos eléctricos", "",
     R503 + "; " + E17_24 + "; INTE E17-4:2017/Enm 1:2024; INTE E17-5:2017/ENM 1:2024; " + D37662, "electrical"),
    ("OCP-015", AC_ND + " (tipo dividido inverter)", "", R78 + "; Decreto Ejecutivo Nº 44037-MINAE; " + D37662,
     "machinery"),
    ("OCP-015", AC_ND + " (tipo dividido de velocidad fija)", "", R80 + "; Decreto Ejecutivo N° 44964-MINAE; " + D37662,
     "machinery"),
    ("OCP-018", "Proceso de producción orgánica que incluye: -Productor individual o grupo organizado de productores. "
     "- Procesamiento - Empaque, envasado, etiquetado -Comercialización -Exportación -Importación", "",
     "Reglamento Técnico Centroamericano RTCA 67.06.74:16 Productos Agropecuarios Orgánicos Requisitos para la "
     "producción, el procesamiento, la comercialización, la certificación y el etiquetado; Reglamento Técnico "
     "Centroamericano RTCA 67.01.33.06 Industria de alimentos y bebidas procesados. Buenas prácticas de manufactura. "
     "Principios generales", "agriculture"),
    ("OCP-018", "-Producción de plantas incluyendo recolección silvestre y grupo de productores -Animales vivos o "
     "productos animales sin procesar -Productos acuícolas sin procesar y algas -Productos agrícolas procesados "
     "-Productos agrícolas procesados para su uso como alimento -Material de propagación vegetativa y semillas para "
     "cultivo", "",
     "Reglamento Técnico Centroamericano RTCA 67.06.74:16 Productos Agropecuarios Orgánicos; Reglamento Técnico "
     "Centroamericano RTCA 67.01.33.06 Industria de alimentos y bebidas procesadas. Buenas prácticas de manufactura",
     "agriculture"),
    ("OCP-021", SOAP, "", EA + "; " + B13, "chemicals"),
    ("OCP-021", "23.61 – Fabricación de productos de concreto para construcción, sujetos a certificación de "
     "Etiquetado Ambiental Tipo I", "",
     EA + "; INTE B26:2020 Etiquetado Ambiental Tipo I. Criterios ambientales para productos de concreto",
     "construction"),
    ("OCP-022", MP_P, "", MP_N, "professional"),
    ("OCP-023", ORG, "", MAG, "agriculture"),
    ("OCP-023", ORG, EUS, EU, ""),
]

if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "annex_transcription.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "product_text", "scheme", "normative_docs", "industry"])
        w.writerows(ROWS)
    print(f"{len(ROWS)} lines -> {out}")
