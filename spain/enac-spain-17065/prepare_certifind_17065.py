"""Convert the ENAC (Spain) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_es_enac_17065.py): enac_17065_raw.json (one record per accreditation NN/C-PRNNN) and
annexes/<uuid>.pdf (the Technical Annex). Output: bodies.csv, accreditations.csv, scopes.csv (header only),
product_scopes.csv in <dataset dir>, and enac_17065_review.md next to this script.

Annexes are read with pdfplumber, page by page in reading order:
- text lines outside tables that look like section titles (PARTE I: ORGANISMO NOTIFICADO..., REGLAMENTO (UE) 305/2011,
  BLOQUE I, CERTIFICACIÓN DE ...) set the context, carried into scheme_text and used for the scheme;
- tables with 2+ columns are data tables (one-cell tables are nested header fragments). Header rows name the columns
  (product / scheme / normative), a table without a header continues the previous one when the width matches;
- one data row = one line; an empty product cell repeats the product above (vertically merged cell).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "greece" / "esyd-greece-17065"))
import prepare_certifind_17065 as gr  # noqa: E402  (scheme regexes, refs, English industry words)

AB_CODE = "ENAC"
STD = "ISO/IEC 17065"
REGISTER = "https://www.enac.es/web/english/accredited-bodies/products-and-services-searchs"

EU_EXTRA = [
    (re.compile(r"ecol[oó]gic|agricultura ecol|producci[oó]n ecol|biol[oó]gic", re.I), "EU Organic Regulation (EU) 2018/848"),
    (re.compile(r"Denominaci[oó]n(es)? de Origen|Indicaci[oó]n(es)? Geogr[aá]fica|\b(DOP|IGP|ETG|DOCa?)\b|"
                r"Especialidad(es)? Tradicional", re.I), "EU Geographical Indications (DOP/IGP/STG)"),
]
EU_RX = [(re.compile(r"305/2011|2011/305|89/106", re.I), c) if c.startswith("Construction Products") else (rx, c)
         for rx, c in gr.EU_RX]
NATIONAL = re.compile(r"Real Decreto|\bR\.?D\.? \d|Esquema Nacional|\bENS\b|Orden [A-Z]{2,4}/|Ley \d|"
                      r"Decreto \d|Comunidad Aut[oó]noma|Junta de|Generalitat|Producci[oó]n Integrada|"
                      r"Marca de Garant[ií]a|Reglamentos? Nacional|REGLAMENTOS NACIONALES", re.I)
PRIVATE_EXTRA = [
    (re.compile(r"ENplus", re.I), "ENplus"),  # V80
    (re.compile(r"GLOBAL ?G\.?A\.?P\.?.{0,40}(Cadena de Custodia|Chain of Custody|CoC)", re.I), "GLOBALG.A.P. Chain of Custody"),
    (re.compile(r"IFS Br[oó]ker", re.I), "IFS Broker"),
    (re.compile(r"BRC\w*.{0,40}(Almacenamiento|Storage)", re.I), "BRCGS Storage and Distribution"),
    (re.compile(r"BRC\w*.{0,40}(Envases|Packaging|Embalaje)", re.I), "BRCGS Packaging Materials"),
    (re.compile(r"BRC\w*.{0,40}(Alimentaria|Food)", re.I), "BRCGS Food Safety"),
    (re.compile(r"BRC\w*.{0,40}(Agentes|Agents)", re.I), "BRCGS Agents and Brokers"),
    (re.compile(r"Cadena de Custodia.{0,40}PEFC|PEFC", re.I), "PEFC Chain of Custody"),
    (re.compile(r"Cadena de Custodia.{0,40}FSC|\bFSC\b", re.I), "FSC Chain of Custody"),
]
HEAD_ROLE = [
    ("scheme_text", r"ESQUEMA|PROCEDIMIENTO|PROCESO DE EVALU|SEVCP|AVCP|SISTEMA|M[OÓ]DULO|DECISI|SCHEME|PROCEDURE|MODULE"),
    ("normative_docs", r"DOCUMENTO|ESPECIFICACI|NORMA|REQUISITO|REFERENCIA|STANDARD|REQUIREMENT"),
    ("product_text", r"DISCIPLINA|PRODUCTO|OBJET|CATEGOR|[AÁ]REA|ACTIVIDAD|ALCANCE|SERVICIO|PROCESO|FAMILIA|TIPO|GRUPO|PRODUCT|SERVICE|CERTIFY|SCOPE|FIELD"),
]
BOILER = re.compile(r"^(Anexo T[eé]cnico|N[ºo°] ?\d|P[aá]g\.?|ENAC es firmante|internacionales de organismos|C[oó]digo Validaci|"
                    r"La acreditaci[oó]n mantiene|Su vigencia|Direcci[oó]n|Norma de referencia|Actividad|Acreditaci[oó]n|"
                    r"Fecha de entrada|ALCANCE DE LA ACREDITACI|SCHEDULE OF ACCRED|\(Rev|Índice|\(\d\)|\d\)|Nota|Note|\*)", re.I)
SECTION = re.compile(r"^(PARTE|BLOQUE|REGLAMENTO|DIRECTIVA|CERTIFICACI[OÓ]N|ESQUEMA|SECTOR|[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ,.;:()/–\-ºª]{10,}$)")
ES_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"I\+D|Investigaci[oó]n,? Desarrollo|innovaci[oó]n tecnol|proyectos? de (I|investig)|c[oó]digo UNESCO|"
     r"deducci[oó]n|disciplinas? tecnol|novedad|ex.?ante|CNAE", "professional"),
    (r"fire resist|resistencia al fuego|smoke|humo|reaction to fire|cladding|motoristas", "construction"),
    (r"Tecnolog[ií]a|Certificaci[oó]n del contenido|Ingenier[ií]a", "professional"),
    (r"video ?vigilancia|surveillance", "electrical"),
    (r"funcionamiento en isla|resincroniz", "energy"),
    (r"gimnasia|tobog[aá]n", "other_manufacturing"),
    (r"Producto (Natural|Artesanal)", "food"),
    (r"contaminantes|Reglamento \(CE\)", "chemicals"),
    (r"conducci[oó]n segura|cursos?", "public_education"),
    (r"juego|playground|parque infantil|deport", "other_manufacturing"),
    (r"sustancias|REACH|etiquetado y envasado|disruptor", "chemicals"),
    (r"telas?|hilado|fieltro|tejid|guata", "textiles"),
    (r"saneamiento|sewerage|tubos?|canalizaci", "construction"),
    (r"turis|hotel|restaura|alojamiento|playa|hosteler", "tourism"),
    (r"sanitari|hospital|cl[ií]nic|salud|productos? sanitarios|m[eé]dic", "health"),
    (r"formaci[oó]n|educa|escuela|administraci[oó]n p[uú]blica|ayuntamiento", "public_education"),
    (r"seguridad de la informaci[oó]n|ciberseg|software|inform[aá]tic|tecnolog[ií]as de la informaci|datos personales|"
     r"privacidad|electr[oó]nic[ao]s? de confianza|firma electr|identidad digital|nube|cloud", "ict"),
    (r"huella de carbono|gases de efecto|emisiones|sostenib|medioambient|ecodise|etiqueta ecol", "professional"),
    (r"cosm[eé]tic|detergent|qu[ií]mic|fertiliz|abono|pintura|biocida|fitosanit", "chemicals"),
    (r"pl[aá]stic|caucho|pol[ií]mer|envase|embalaje|PVC|polietileno", "rubber_plastics"),
    (r"ferrocarril|ferroviari|veh[ií]culo|autom[oó]vil|aeron|naval|buque|embarcaci", "transport_equipment"),
    (r"soldadura|acero|alumini|metal|fundici|galvaniz|tornill", "metals"),
    (r"m[aá]quina|ascensor|presi[oó]n|gr[uú]a|elevaci|calder|extintor|incendio|equipos? de protecci", "machinery"),
    (r"el[eé]ctric|electr[oó]nic|fotovolt|solar|cable|l[aá]mpara|luminari|bater[ií]", "electrical"),
    (r"hormig[oó]n|cemento|construcci[oó]n|edific|ladrillo|cer[aá]mic|vidrio|ventana|puerta|aislam|"
     r"[aá]rido|mortero|yeso|betún|bitum|asfalt|carretera|tuber|madera estructural|teja|piedra", "construction"),
    (r"textil|ropa|prenda|calzado|cuero|piel", "textiles"),
    (r"biocombust|biomasa|combustible|energ[ií]a|hidr[oó]geno|biog[aá]s|pellet|biometano", "energy"),
    (r"juguete|mueble|joya|reciclad|residuo", "other_manufacturing"),
    (r"madera|papel|cart[oó]n|forest|corcho", "wood_paper"),
    (r"aliment|vino|aceite|jam[oó]n|queso|carne|leche|l[aá]cte|pescado|miel|cerveza|bebida|conserva|pan\b|"
     r"embutid|piens|agroaliment", "food"),
    (r"agr[ií]col|agricult|fruta|hortaliza|vegetal|cultivo|ganad|animal|semilla|planta|acuicult|pesca|"
     r"bienestar animal|cereal|ceb[oa]", "agriculture"),
    (r"log[ií]stic|transporte|almac[eé]n|distribuci[oó]n|comercializaci[oó]n", "trade_logistics"),
    (r"servicio|auditor", "professional"),
]]


EU_CODES = {c for _, c in gr.EU_SCHEMES}


def clean(t):
    return gr.clean((t or "").replace("\n", " "))


def scheme_of(t: str):
    p = gr.probe(t)
    eu = next((c for rx, c in EU_RX if rx.search(p)), None) or next((c for rx, c in EU_EXTRA if rx.search(t)), None)
    if eu:
        return eu
    if NATIONAL.search(t):
        return None
    return next((c for rx, c in PRIVATE_EXTRA if rx.search(t)), None) or \
        next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def industry_of(t: str):
    return next((i for rx, i in ES_WORDS if rx.search(t)), None) or gr.industry_of(t)


def is_label(c: str) -> bool:
    if not c or len(c) > 90 or re.search(r"\d{3,}|Versi[oó]n|\(UE\)|/\d{4}", c):
        return False
    up = c.upper()
    if not any(re.search(rx, up) for _, rx in HEAD_ROLE + [("x", r"\bNORMA\b|EVALUACI|CERTIFICA")]):
        return False
    letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", c)
    caps = sum(1 for ch in letters if ch.isupper()) / max(1, len(letters))
    return caps > 0.8 or (len(c) < 45 and re.match(r"(Categor|Procedimiento|Requisitos|Producto|Norma|Documento|Esquema|M[oó]dulo|Sistema)", c))


def is_header(cells):
    filled = [c for c in cells if c]
    return bool(filled) and all(is_label(c) for c in filled)


def role_of_label(lab: str):
    up = lab.upper()
    if re.search(r"GRUPO DE PRODUCTO|PRODUCT GROUP|CATEGOR[IÍ]A DE PRODUCTO|PRODUCTOS, PROCESOS|OBJETO", up):
        return "product_text"
    return next((r for r, rx in HEAD_ROLE if re.search(rx, up)), None)


def parse_pdf(path: Path, audit, reg):
    lines = []
    context, spans, last_prod = "", None, ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            items = []
            for ln in page.extract_text_lines():
                x0, top, x1, bottom = ln["x0"], ln["top"], ln["x1"], ln["bottom"]
                if any(b[0] - 2 <= x0 and x1 <= b[2] + 2 and b[1] - 2 <= top and bottom <= b[3] + 2 for b in boxes):
                    continue
                items.append((top, "text", clean(ln["text"])))
            for t in tables:
                items.append((t.bbox[1], "table", t))
            items.sort(key=lambda x: (x[0], x[1] == "table"))
            for _, kind, obj in items:
                if kind == "text":
                    if BOILER.match(obj) or len(obj) < 6:
                        continue
                    if SECTION.match(obj) and not re.search(r"\.{5,}", obj):
                        s_new = scheme_of(obj)
                        if re.match(r"PARTE|BLOQUE|REGLAMENTO|DIRECTIVA|CERTIFICACI|ESQUEMA", obj, re.I) or s_new:
                            context = obj if (s_new or re.match(r"PARTE|BLOQUE", obj, re.I)) else context + " " + obj
                            context = context[-300:]
                            audit["section title (carried into scheme_text)"].append((reg, obj[:100]))
                    continue
                texts = [[clean(c) for c in r] for r in obj.extract()]
                cells = [r.cells for r in obj.rows]
                if not texts or len(texts[0]) < 2:
                    audit["one-cell table (header fragment)"].append((reg, " ".join(c for r in texts for c in r if c)[:80]))
                    continue
                flat_all = " ".join(c for r in texts[:3] for c in r if c)
                if re.search(r"COMUNIDAD AUT|PROVINCIA|MUNICIPIO|EMPLAZAMIENTO|LOCALIZACI|SEDES?|SITES?|ADDRESS", flat_all, re.I)                         and not re.search(r"PRODUCTO|DOCUMENTO", flat_all):
                    audit["site / location table"].append((reg, flat_all[:100]))
                    continue
                tx0, tx1 = obj.bbox[0], obj.bbox[2]
                i, new_spans = 0, []
                while i < len(texts) and (is_header(texts[i]) or (new_spans and not any(texts[i]))):
                    for c, bb in zip(texts[i], cells[i]):
                        role = role_of_label(c) if c else None
                        if role and bb:
                            new_spans.append((bb[0], bb[2], role))
                    i += 1
                if new_spans:
                    spans, last_prod = new_spans, ""
                    if not any(r == "product_text" for _, _, r in spans):
                        spans.append((tx0, min(s[0] for s in spans), "product_text"))
                elif spans is None:
                    audit["table without a header (positional columns)"].append((reg, " | ".join(c for c in texts[0] if c)[:100]))

                def role_at(bb, j, w):
                    if spans:
                        cx = (bb[0] + bb[2]) / 2
                        inside = [r for x0, x1, r in spans if x0 - 1 <= cx <= x1 + 1]
                        if inside:
                            return inside[0]
                        return min(spans, key=lambda s: min(abs(cx - s[0]), abs(cx - s[1])))[2]
                    return "product_text" if j == 0 else "normative_docs"

                for r, rc in zip(texts[i:], cells[i:]):
                    filled = [(c, bb) for c, bb in zip(r, rc) if c and bb]
                    if not filled:
                        continue
                    if is_header(r):
                        continue
                    joined = "".join(c for c, _ in filled[:2])
                    if re.match(r"^P\s?ARTE\s+[IVX]+", joined, re.I) or re.match(r"^P$", filled[0][0]) and len(filled) > 1 and re.match(r"ARTE [IVX]+", filled[1][0]):
                        context = " ".join(c for c, _ in filled)
                        audit["section title (carried into scheme_text)"].append((reg, context[:100]))
                        continue
                    if len(filled) == 1 and len(r) > 2 and filled[0][1][0] <= tx0 + 3 and filled[0][1][2] >= tx1 - 3 \
                            and len(filled[0][0]) < 200:
                        lines.append({"heading": filled[0][0]})  # full-width group heading row
                        continue
                    f = collections.defaultdict(list)
                    for j, (c, bb) in enumerate(filled):
                        f[role_at(bb, j, len(r))].append(c)
                    f = {k: " ".join(v) for k, v in f.items()}
                    prod = f.get("product_text", "")
                    if prod:
                        last_prod = prod
                    elif rc and rc[0] is None:
                        prod = last_prod  # vertically merged product cell
                    lines.append({"product_text": prod, "scheme_text_col": f.get("scheme_text", ""),
                                  "normative_docs": f.get("normative_docs", ""), "context": context})
    # group headings: kept as the product prefix context of the rows below, not as lines
    # continuation fragments: a product-only line starting in lower case continues the line above
    merged = []
    for ln in lines:
        if "heading" not in ln and merged and "heading" not in merged[-1] and not ln["normative_docs"]                 and not ln["scheme_text_col"] and re.match(r"^[a-záéíóúñ(]", ln["product_text"] or "")                 and ln["product_text"] != merged[-1]["product_text"]:
            merged[-1]["product_text"] = (merged[-1]["product_text"] + " " + ln["product_text"]).strip()
            audit["continuation fragment (joined to the line above)"].append((reg, ln["product_text"][:80]))
            continue
        merged.append(ln)
    lines = merged
    out, group, sticky, last_ctx = [], "", None, None
    for ln in lines:
        if "heading" not in ln and (re.fullmatch(r"[A-Z]", ln["product_text"] or "") or BOILER.match(ln["product_text"] or "") or is_header([ln["product_text"]]) and not ln["normative_docs"]):
            audit["boilerplate / header row"].append((reg, (ln["product_text"] or "")[:80]))
            continue
        if "heading" in ln:
            group = ln["heading"]
            audit["group heading row (carried into scheme_text)"].append((reg, group[:100]))
            continue
        if ln["context"] != last_ctx:
            sticky, last_ctx = None, ln["context"]
        own = " ".join([ln["product_text"], ln["normative_docs"], ln["scheme_text_col"]])
        s_own = scheme_of(own)
        if s_own in EU_CODES:
            sticky = s_own
        st = "; ".join(x for x in (ln["context"], group, ln["scheme_text_col"]) if x)
        if not (ln["product_text"] or ln["normative_docs"]) and re.fullmatch(r"[\s()*]*|(SEVCP|AVCP)?[\s/()*]*", ln["scheme_text_col"] or ""):
            audit["header leftover (**)"].append((reg, ln["scheme_text_col"]))
            continue
        out.append({"product_text": ln["product_text"], "scheme_text": st, "normative_docs": ln["normative_docs"],
                    "scheme_basis": " ".join([ln["context"], group]), "sticky": sticky})
    return out


def phone_es(raw: str):
    ph = re.split(r"[/,;]| y ", raw or "")[0]
    d = re.sub(r"\D", "", ph)
    if d.startswith("0034"):
        d = d[4:]
    elif d.startswith("34") and len(d) == 11:
        d = d[2:]
    if len(d) > 9 and d[0] in "6789":
        d = d[:9]
    if len(d) == 9:
        return f"+34 {d[:3]} {d[3:6]} {d[6:]}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "enac_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)

    ms_by_no, by_name = {}, {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent == a.dataset.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if f.parent.name == "enac-spain" and r["registration_no"]:
                ms_by_no[r["registration_no"].split("/")[0].strip().lstrip("0")] = r
            by_name.setdefault((r["country"], gr.key(r["name"]) if hasattr(gr, "key") else r["name"].lower()), (f.parent.name, r))
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "enac-spain" / "accreditations.csv", encoding="utf-8"))}

    per_body = collections.OrderedDict()
    for rec in raw:
        no = rec["registration_no"].split("/")[0].strip().lstrip("0")
        per_body.setdefault(no, []).append(rec)

    bodies, accs, ps = [], [], []
    for no, recs in per_body.items():
        rec0 = recs[0]
        name = gr.clean(rec0["name"])
        # ENAC numbers differ between the MS (C-SC) and product (C-PR) registers, so match by name only
        if ("Spain", name.lower()) in by_name:
            ds, body = by_name[("Spain", name.lower())]
            body = dict(body)
            review["Bodies reused"].append(f"{no} `{body['name']}` from {ds} (same name)")
        else:
            phone = phone_es(rec0["phone"])
            if rec0["phone"].strip() and not phone:
                review["Invalid phones"].append(f"{no} {name}: `{rec0['phone']}` left empty")
            web = (rec0.get("website") or "").strip()
            if web and not web.startswith("http"):
                web = "https://" + web
            body = {"name": name, "country": "Spain", "registration_no": rec0["registration_no"], "phone": phone,
                    "email": (rec0["email"] or "").split(";")[0].split(",")[0].strip().lower(), "website": web,
                    "address": gr.clean(rec0["address"]), "source_url": REGISTER, "verified_at": ""}
        lines = []
        for rec in recs:
            for url in rec["annex_urls"]:
                path = a.scrape / "annexes" / (url.rsplit("/", 1)[-1] + ".pdf")
                if not path.exists():
                    review["Annexes missing"].append(f"{rec['registration_no']}: {url}")
                    continue
                got = parse_pdf(path, audit, rec["registration_no"])
                if not got:
                    review["Annexes without lines (register scope title imported)"].append(f"{rec['registration_no']} {path.name}")
                    got = [{"product_text": rec["scope_title"], "scheme_text": "", "normative_docs": "", "scheme_basis": rec["scope_title"]}]
                for g in got:
                    g["title"] = rec["scope_title"]
                lines += got
        if not lines:
            review["Bodies dropped (no line)"].append(f"{no} {name}")
            continue
        cert = rec0["registration_no"].replace("/ ", "/")
        if cert in used:
            cert += " (17065)"
        if len(recs) > 1:
            review["Accreditations merged"].append(f"{no} {name}: " + ", ".join(r["registration_no"] for r in recs) + f" -> `{cert}`")
        issued = min((r["issued"] for r in recs if r["issued"]), default="")
        if not issued:  # the annex header: "Fecha de entrada en vigor: 11/11/2013"
            for rec in recs:
                for url in rec["annex_urls"]:
                    path = a.scrape / "annexes" / (url.rsplit("/", 1)[-1] + ".pdf")
                    if path.exists() and not issued:
                        with pdfplumber.open(path) as pdf:
                            m = re.search(r"entrada en vigor[^:]*:\s*(\d{1,2})/(\d{1,2})/(\d{4})", pdf.pages[0].extract_text() or "")
                        if m:
                            issued = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
                            review["Issue date from the annex"].append(f"{rec['registration_no']}: {issued}")
        bodies.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE",
                     "issue_date": issued,
                     "expiry_date": "", "proof_url": rec0["annex_urls"][0] if rec0["annex_urls"] else REGISTER})
        for n, ln in enumerate(lines, 1):
            own = " ".join([ln["product_text"], ln["normative_docs"]])
            s = scheme_of(own)
            if not s and not NATIONAL.search(own):
                s = scheme_of(ln["scheme_text"]) or ln.get("sticky")
            s = s or ""
            full = " ".join([ln["product_text"], ln["scheme_text"], ln["normative_docs"]])
            ind = "" if s else (industry_of(full) or industry_of(ln["title"]) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": s, "industry": ind,
                       "product_text": ln["product_text"], "product_text_en": "", "scheme_text": ln["scheme_text"],
                       "normative_docs": ln["normative_docs"], "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if no in a.debug or cert in a.debug:
                print(n, s, "|", ind, "|", ln["product_text"][:60], "|", ln["scheme_text"][-50:], "|", ln["normative_docs"][:50])

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", gr.BODY_COLUMNS, bodies)
    write(a.dataset / "accreditations.csv", gr.ACC_COLUMNS, accs)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", gr.PS_COLUMNS, ps)

    neither = [p for p in ps if not p["scheme"] and not p["industry"]]
    names = collections.Counter(b["name"] for b in bodies)
    for nme, c in names.items():
        if c > 1:
            review["DUPLICATE body names"].append(nme)
    out = [f"# ENAC 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Rows not imported / context", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v[:300]] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]} || {p['normative_docs'][:60]}" for p in neither]
    (HERE / "enac_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} "
          f"with scheme {sum(1 for p in ps if p['scheme'])} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
