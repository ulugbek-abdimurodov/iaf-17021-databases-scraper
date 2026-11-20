"""Convert the ESYD (Greece) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_gr_esyd_17065.py): bodies.csv, esyd_17065_raw.json, scope_documents/<id>_<name>/*.doc.
Output: bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv in <dataset dir>,
and esyd_17065_review.md next to this script.

Annex tables are rebuilt from the Word cell marks (\\x07): a row is its cells followed by an empty row mark.
The header row ("Field of certification | Type of certification | Normative ...") names the columns. A row
whose cell count differs from the header (an empty merged cell splits it) is kept with its cells joined in
product_text. A directive / regulation carries its scheme down until the next scheme or table header.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import prepare_certifind as gp  # noqa: E402  (ESYD MS converter: body normalisation)
from worddoc import read_text  # noqa: E402

AB_CODE = "ESYD"
STD = "ISO/IEC 17065"
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url",
                "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
LOOK = gp.LOOKALIKES

EU_SCHEMES = [
    (r"305/2011|2011/305|89/106|Construction products", "Construction Products Regulation (EU) 305/2011"),
    (r"2023/1230", "Machinery Regulation (EU) 2023/1230"),
    (r"2006/42", "Machinery Directive 2006/42/EC"),
    (r"2014/33|95/16", "Lifts Directive 2014/33/EU"),
    (r"2014/68|97/23", "Pressure Equipment Directive 2014/68/EU"),
    (r"2014/29|2009/105|87/404", "Simple Pressure Vessels Directive 2014/29/EU"),
    (r"2014/34|94/9", "ATEX Directive 2014/34/EU"),
    (r"2014/30|2004/108", "EMC Directive 2014/30/EU"),
    (r"2014/53|1999/5/", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/32|2004/22", "Measuring Instruments Directive 2014/32/EU"),
    (r"2014/31|2009/23", "Non-automatic Weighing Instruments Directive 2014/31/EU"),
    (r"2009/48", "Toy Safety Directive 2009/48/EC"),
    (r"2000/14", "Outdoor Noise Directive 2000/14/EC"),
    (r"92/42", "Hot-water Boilers Directive 92/42/EEC"),
    (r"2016/425|89/686", "PPE Regulation (EU) 2016/425"),
    (r"2016/426|2009/142", "Gas Appliances Regulation (EU) 2016/426"),
    (r"2016/424|2000/9/", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2016/797|2008/57", "Rail Interoperability Directive (EU) 2016/797"),
    (r"2014/90|96/98", "Marine Equipment Directive 2014/90/EU"),
    (r"2013/53|94/25", "Recreational Craft Directive 2013/53/EU"),
    (r"2019/779", "ECM Regulation (EU) 2019/779"),
    (r"402/2013", "CSM Risk Assessment Regulation (EU) 402/2013"),
    (r"2024/1143|1151/2012|\b(PDO|PGI|TSG)\b", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2018/848|834/2007|2092/91|organic (product|farming|production)|ORGANIC PRODUCTS", "EU Organic Regulation (EU) 2018/848"),
    (r"517/2014|2024/573|2015/2067|303/2008|304/2008|842/2006|fluorinated", "EU F-gas Regulation"),
]
SCHEMES = EU_SCHEMES + [
    (r"GLOBAL ?G\.?A\.?P\.?.{0,20}Chain of Custody|GLOBAL ?G\.?A\.?P\.?.{0,10}\bCoC\b", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,40}Packaging", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,40}Storage and Distribution", "BRCGS Storage and Distribution"),
    (r"BRC\w*.{0,40}Agents? and Brokers", "BRCGS Agents and Brokers"),
    (r"BRC\w*.{0,40}Consumer Products", "BRCGS Consumer Products"),
    (r"BRC\w*.{0,40}Food", "BRCGS Food Safety"),
    (r"IFS Wholesale", "IFS Wholesale"), (r"IFS Logistics", "IFS Logistics"), (r"IFS Broker", "IFS Broker"),
    (r"IFS (HPC|Household)", "IFS HPC"), (r"IFS PAC ?secure", "IFS PACsecure"), (r"IFS Food", "IFS Food"),
    (r"\bSQF\b", "SQF"), (r"GMP\+", "GMP+ FSA"),
    (r"ISCC[ -]?PLUS", "ISCC PLUS"), (r"ISCC[ -]?EU", "ISCC EU"), (r"\b2BS", "2BSvs"),
    (r"PEFC", "PEFC Chain of Custody"), (r"\bFSC\b", "FSC Chain of Custody"),
    (r"MSC.{0,20}Chain of Custody", "MSC Chain of Custody"),
    (r"Friend of the Sea", "Friend of the Sea"), (r"LEAF Marque", "LEAF Marque"),
    (r"EUROPRIVACY", "Europrivacy"), (r"910/2014|eIDAS|ETSI EN 319 4|Trust Service", "eIDAS"),
    (r"Keymark", "CEN Keymark"),
    (r"22005", "ISO 22005"), (r"15085", "EN 15085-2"), (r"3834", "ISO 3834"), (r"\b15343", "EN 15343"),
    (r"2999[0-4]", "ISO 29993"), (r"13009", "ISO 13009"), (r"GSTC", "GSTC Criteria"),
    (r"18295", "ISO 18295"), (r"22222", "ISO 22222"),
    (r"IEC 61215|IEC 61730", "IEC 61215 / IEC 61730"), (r"IEC 61508", "IEC 61508"), (r"IEC 62443", "IEC 62443"),
    (r"15408|Common Criteria", "Common Criteria (ISO/IEC 15408)"),
]
EU_RX = [(re.compile(p, re.I), c) for p, c in EU_SCHEMES]
SCHEMES = [(re.compile(p, re.I), c) for p, c in SCHEMES]
# Greek national schemes and decisions: text only, no catalogue scheme.
NATIONAL = re.compile(r"AGRO ?[0-9]|\bM\.D\.|J\.M\.D\.|\bG\.G\.|\bL\. ?\d|Law \d|Ministerial|National Legislat|"
                      r"ELGO|DIMITRA|ΥΑ|ΚΥΑ|ΦΕΚ|Hotel classif|ΚΑΤΑΤΑΞΗ", re.I)
FIELD_DEFAULT = [  # register field -> (sticky scheme for the whole annex, fallback industry)
    (r"ORGANIC", "EU Organic Regulation (EU) 2018/848", "agriculture"),
    (r"GLOBALGAP", "GLOBALG.A.P. IFA", "agriculture"),
    (r"AGRO 2|INTEGRATED MANAGEMENT", None, "agriculture"),
    (r"GREENHOUSE", None, "energy"),
    (r"QS-Quality", None, "food"),
    (r"FERTILI", None, "chemicals"),
    (r"ΞΕΝΟΔΟΧ", None, "tourism"),
]
HEADER = re.compile(r"^(Field of (certification|inspection)|Nature of|Αντικείμενο|Type of certification|Cluster of Activities|"
                    r"Activity|Standard|Normative|Products?( / Product categories)?|Product category|Scope|"
                    r"Certification scheme|Πεδίο|Είδος|Κανονιστικ|Scheme|Requirements|Category|Sub-?scope|"
                    r"Certification (Scheme|Type)|Group|Normative document)s?\b", re.I)
BOILER = re.compile(r"^(Address of the Body|Approved signatory|This Scope|The Accreditation Certificate|Athens,|"
                    r"Accreditation is granted|Hellenic Accreditation System|Annex [A-ZΑ-Ω]|SCOPE of|CEO of|"
                    r"Ceo of|\(cont\.?\)|\*+ ?Not|Page \d|.{0,40}CEO of ESYD$|Εθνικό Σύστημα)", re.I)
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"touris|\bhotel|rooms|apartments|restaurant|catering|accommodation|div(e|ing)|snorkel|camps?\b", "tourism"),
    (r"\bBIM\b|Building Information", "construction"),
    (r"fire extinguish|solar", "machinery"),
    (r"playground|sport|skate|basket|gymnast|trampolin|parkour", "other_manufacturing"),
    (r"computer", "electrical"),
    (r"local products", "food"),
    (r"Λέβητ|λέβητ|Θερμαντήρ", "machinery"),
    (r"Ηλεκτρισμ|ΣΗΘΥΑ", "energy"),
    (r"\brail", "transport_equipment"),
    (r"cannabis", "agriculture"),
    (r"hospital|\bhealth|medical device|diagnostic", "health"),
    (r"training|school|educat|public administration|municipal", "public_education"),
    (r"cyber|software|\bICT\b|privacy|digital|information secur", "ict"),
    (r"financial|security services|contact cent|alarm|consult|verification of (reporting|carbon)|carbon footprint|"
     r"greenhouse|GHG", "professional"),
    (r"cosmetic|detergent|chemical|pharma|paint|fertili[sz]", "chemicals"),
    (r"plastic|rubber|polymer|packaging|PVC|polyethyl", "rubber_plastics"),
    (r"railway|rolling stock|vehicle|automotive|aeronaut|marine equip|recreational craft|\bEN 45545", "transport_equipment"),
    (r"welding|brazing|\bISO 3834|\bsteel|alumini|metal|cast iron|galvaniz|reinforc", "metals"),
    (r"machin|tractor|lifting|pressure|\blifts?\b|boiler|crane|vessel|piping|cableway|valve", "machinery"),
    (r"electric|electronic|photovolta|\bIEC 6\d{4}|transformer|switchgear|cables?\b|lamp|luminair|"
     r"low voltage|radio|weighing|measuring", "electrical"),
    (r"concrete|construction|cement|clinker|brick|tiles?\b|pipes?\b|glass|drinking water|windows|doors?\b|"
     r"insulat|aggregat|quarr|lime\b|gypsum|asphalt|bitum|masonry|mortar|road|slabs?|fences?|ceramic|stone|marble", "construction"),
    (r"textile|clothing|footwear|leather", "textiles"),
    (r"biofuel|biogas|\bfuel|pellet|energy|hydrogen|refin|combustion|electricity", "energy"),
    (r"scrap|end-of-waste|recycl|\btoys?\b|furniture|jewel", "other_manufacturing"),
    (r"\bwood|paper|forest|printing", "wood_paper"),
    (r"\bfood|\bfeed|\bwine|\bmeat|dairy|milk|\bfish|seafood|beverage|olive oil|honey|cheese|bakery|feta", "food"),
    (r"agricult|crop|fruit|vegetab|livestock|animal|aquacult|farm|plant|seed|cereal|cotton|olive", "agriculture"),
    (r"logistic|transport|warehous|\btrade\b|distribution|storage", "trade_logistics"),
]]
REF = re.compile(r"\b(?:(?:ELOT|DIN|BS|NF)\s+)*(?:EN\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{2,5})((?:-\d{1,3})?)")
ETSI = re.compile(r"ETSI\s+(EN|TS)\s+(\d{3})\s+(\d{3})((?:-\d+)?)")
WS = re.compile(r"\s+")
VALID = re.compile(r"valid (?:until|up to)\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", re.I)


def clean(t: str) -> str:
    return WS.sub(" ", (t or "").replace("\xa0", " ").replace("\r", " ")).strip()


def probe(t: str) -> str:
    return t.translate(LOOK)


def scheme_of(t: str):
    p = probe(t)
    eu = next((c for rx, c in EU_RX if rx.search(p)), None)
    if eu:
        return eu
    if NATIONAL.search(t) or NATIONAL.search(p):
        return None
    return next((c for rx, c in SCHEMES if rx.search(p)), None)


def industry_of(t: str):
    p = probe(t)
    return next((ind for rx, ind in INDUSTRY_WORDS if rx.search(p)), None)


def refs(t: str) -> str:
    p = probe(t)
    out = [f"ETSI {m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}" for m in ETSI.finditer(p)]
    for m in REF.finditer(ETSI.sub(" ", p)):
        if m.group(1) == "EN" and len(m.group(2)) < 3:
            continue
        r = f"{m.group(1)} {m.group(2)}{m.group(3)}"
        if r not in out:
            out.append(r)
    return ";".join(out)


def table_rows(text: str):
    """[(cells, is_first_of_region)] from Word text with \\x07 cell marks; drops text after the last table."""
    toks = re.sub(r"[\x00-\x06\x08\x0b-\x1f]", "\r", text).split("\x07")
    rows, cur = [], []
    for tok in toks[:-1]:  # the last token is outside any table (footer)
        if tok.strip("\r ") == "" and cur:
            rows.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        rows.append(cur)
    return rows


def col_role(label: str) -> str:
    l = probe(label).lower()
    if re.search(r"type of|cluster|scheme|είδος", l):
        return "scheme_text"
    if re.search(r"normative|standard|regulation|requirement|κανονιστ|method", l):
        return "normative_docs"
    return "product_text"


def parse_annex(text: str, sticky0, audit, reg):
    lines, roles, sticky = [], None, sticky0
    last_prod = ""
    pending = table_rows(text)
    while pending:
        cells = pending.pop(0)
        # an empty middle cell looks like a row mark: rejoin "A" + "" + "B" when it restores the width
        if roles and len(cells) < len(roles) and pending and len(cells) + len(pending[0]) + 1 == len(roles):
            cells = cells + [""] + pending.pop(0)
        paras = [[clean(p) for p in c.split("\r") if clean(p)] for c in cells]
        flat = " ".join(" ".join(p) for p in paras)
        if not flat:
            continue
        # header row: the first cell's last paragraph is a column label (preamble text sits above it)
        first_last = paras[0][-1] if paras[0] else ""
        if len(paras) == 1 and BOILER.match(flat):
            # title block (a one-cell frame or no table at all): content follows the column labels
            ps_ = paras[0]
            hdr = [i for i, x in enumerate(ps_) if HEADER.match(x) and len(x) < 40 and not re.match(r"scope", x, re.I)]
            content = [x for x in ps_[hdr[-1] + 1:] if not BOILER.match(x)] if hdr else []
            if content:
                s = scheme_of(" ".join(content))
                lines.append({"product_text": " ".join(content), "scheme_text": "", "normative_docs": "",
                              "scheme": s or sticky or ""})
                audit["title block (content after the labels kept)"].append((reg, " ".join(ps_[:hdr[-1] + 1])[:120]))
            else:
                audit["boilerplate"].append((reg, flat[:120]))
            continue
        if HEADER.match(first_last) and all(len(" ".join(p)) < 200 for p in paras[1:]) and \
                (len(paras) > 1 or len(flat) < 60):
            roles = [col_role(" ".join(p[-1:] if i == 0 else p)) for i, p in enumerate(paras)]
            s = scheme_of(flat)
            sticky = s if s else sticky0
            audit["table header / annex preamble"].append((reg, flat[:120]))
            continue
        texts = [" ".join(p) for p in paras]
        if BOILER.match(flat) or re.search(r"CEO of ESYD\s*$", flat, re.I):
            audit["boilerplate"].append((reg, flat[:120]))
            continue
        out = {"product_text": [], "scheme_text": [], "normative_docs": []}
        if roles and len(texts) == len(roles):
            for r, t in zip(roles, texts):
                if t:
                    out[r].append(t)
        else:
            out["product_text"] = [t for t in texts if t]
        line = {k: " ".join(v) for k, v in out.items()}
        if not line["product_text"] and last_prod and (line["scheme_text"] or line["normative_docs"]):
            line["product_text"] = last_prod  # vertically merged "Field" cell
        elif line["product_text"]:
            last_prod = line["product_text"]
        if re.fullmatch(r"[\d.\s*]+", flat):
            audit["number only"].append((reg, flat))
            continue
        s = scheme_of(flat)
        if s and s in {c for _, c in EU_SCHEMES}:
            sticky = s
        elif NATIONAL.search(flat) or NATIONAL.search(probe(flat)):
            if sticky and sticky != sticky0 and not s:
                sticky = sticky0  # a national decision row ends the directive block
        line["scheme"] = s or sticky or ""
        lines.append(line)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)

    with open(a.scrape / "bodies.csv", encoding="utf-8-sig", newline="") as fh:
        raw_bodies = {b["body_id"]: b for b in csv.DictReader(fh)}
    raw = json.loads((a.scrape / "esyd_17065_raw.json").read_text(encoding="utf-8"))
    review = collections.defaultdict(list)
    audit = collections.defaultdict(list)

    # existing body rows: ESYD MS dataset by register id, then any dataset by (country, name)
    ms_by_id, by_name = {}, {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent == a.dataset.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            m = re.search(r"esydops.*id=(\d+)", r.get("source_url", ""))
            if m and f.parent.name == "esyd-greece":
                ms_by_id[m.group(1)] = r
            by_name.setdefault((r["country"], gp.key(r["name"]) if hasattr(gp, "key") else r["name"].lower()), (f.parent.name, r))
    ms_certs = {r["certificate_number"] for r in csv.DictReader(open(data_root / "esyd-greece" / "accreditations.csv", encoding="utf-8"))}
    used_certs = set()
    for f in data_root.glob("esyd-*/accreditations.csv"):
        if f.parent != a.dataset.resolve():
            used_certs |= {r["certificate_number"] for r in csv.DictReader(open(f, encoding="utf-8"))}

    regs_by_body = collections.defaultdict(list)
    for rec in raw:
        regs_by_body[rec["id"]].append(rec)

    bodies, accs, ps = [], [], []
    for bid, recs in regs_by_body.items():
        rb = raw_bodies[bid]
        name = gp.clean_name(rb["name"])
        country = gp.country_of(rb)
        if bid in ms_by_id:
            body = dict(ms_by_id[bid])
            review["Bodies reused"].append(f"{bid} `{body['name']}` from esyd-greece (same register id)")
        elif (country, gp.key(name) if hasattr(gp, "key") else name.lower()) in by_name:
            ds, body = by_name[(country, gp.key(name) if hasattr(gp, "key") else name.lower())]
            body = dict(body)
            review["Bodies reused"].append(f"{bid} `{body['name']}` from {ds} (same name)")
        else:
            phone = gp.normalise_phone(rb["telephone"], country)
            if rb["telephone"].strip() and not phone:
                review["Invalid phones"].append(f"{bid} {name}: `{rb['telephone']}` left empty")
            address = rb["address"].strip()
            city = rb["city"].strip()
            if city and re.split(r"[,\s]+", city)[0].lower() not in address.lower():
                address = f"{address}, {city}" if address else city
            body = {"name": name, "country": country, "registration_no": "", "phone": phone,
                    "email": gp.normalise_email(rb["email"]) or gp.normalise_email(rb["fax"]),
                    "website": gp.normalise_website(rb["website"]), "address": address,
                    "source_url": rb["detail_url"], "verified_at": ""}

        # lines, registration by registration in register order
        lines, issued, valid = [], [], []
        for rec in recs:
            field = rec["field"]
            fd = next(((s, i) for p, s, i in FIELD_DEFAULT if re.search(p, field, re.I)), (None, None))
            sticky0 = fd[0] or (scheme_of(field) if not re.search(r"DIRECTIVES|Voluntary", field, re.I) else None)
            if rec["issued"]:
                d, m, y = rec["issued"].split(".")
                issued.append(f"{y}-{int(m):02d}-{int(d):02d}")
            path = None
            for url in rec["annex_urls"]:
                if url.endswith("_en.doc"):
                    hits = list((a.scrape / "scope_documents").glob(f"{bid}_*/{url.rsplit('/', 1)[-1]}"))
                    path = hits[0] if hits else None
            got = []
            if path:
                text = read_text(path)
                for m in VALID.finditer(text):
                    if "GREENHOUSE" not in field:
                        valid.append(f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}")
                got = parse_annex(text, sticky0, audit, rec["registration_no"])
                if not got:
                    review["Annexes without rows"].append(f"{bid} {name}: {path.name} ({field})")
            if not got:
                if not path:
                    review["Annexes missing (register field imported as the line)"].append(
                        f"{bid} {name}: `{field}` ({', '.join(rec['annex_urls'])})")
                got = [{"product_text": field, "scheme_text": "", "normative_docs": "",
                        "scheme": sticky0 or scheme_of(field) or ""}]
            for g in got:
                g["fallback"] = fd[1]
                g["field"] = field
            lines += got
        if not lines:
            review["Bodies dropped (no line)"].append(f"{bid} {name}")
            continue

        # certificate number: base of the most frequent non-GHG registration
        regs = [r["registration_no"] for r in recs if r["registration_no"] != bid and "GREENHOUSE" not in r["field"]] or \
               [r["registration_no"] for r in recs if r["registration_no"] != bid]
        cert = collections.Counter(r.split("-")[0] for r in regs).most_common(1)[0][0] if regs else f"ESYD-{bid}"
        if cert in used_certs:
            cert = f"{cert} (17065)"
        if len({r['registration_no'] for r in recs}) > 1 or len(recs) > 1:
            review["Registrations merged"].append(
                f"{bid} {name}: " + "; ".join(f"{r['registration_no']} {r['field'][:40]}" for r in recs) + f" -> `{cert}`")
        bodies.append({k: body.get(k, "") for k in BODY_COLUMNS})
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": min(issued) if issued else "",
                     "expiry_date": max(valid) if valid else "", "proof_url": rb["detail_url"]})
        for n, g in enumerate(lines, 1):
            full = " ".join([g["product_text"], g["scheme_text"], g["normative_docs"]])
            industry = "" if g["scheme"] else (industry_of(full) or g["fallback"] or industry_of(g["field"]) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": g["scheme"], "industry": industry,
                       "product_text": g["product_text"], "product_text_en": "", "scheme_text": g["scheme_text"],
                       "normative_docs": g["normative_docs"], "standard_refs": refs(full), "status": "ACTIVE"})
            if cert.split(" ")[0] in a.debug:
                print(n, g["scheme"], "|", industry, "|", g["product_text"][:80], "|", g["scheme_text"][:40], "|", g["normative_docs"][:60])

    names = collections.Counter(b["name"] for b in bodies)
    for nme, c in names.items():
        if c > 1:
            review["DUPLICATE body names"].append(nme)

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", BODY_COLUMNS, bodies)
    write(a.dataset / "accreditations.csv", ACC_COLUMNS, accs)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    neither = [p for p in ps if not p["scheme"] and not p["industry"]]
    out = [f"# ESYD 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} ({with_scheme} with a scheme, "
           f"{len(neither)} with neither scheme nor industry).", ""]
    out += ["## Schemes", ""] + [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Lines left out", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v[:400]] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]}" for p in neither] + [""]
    (HERE / "esyd_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} with scheme {with_scheme} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
