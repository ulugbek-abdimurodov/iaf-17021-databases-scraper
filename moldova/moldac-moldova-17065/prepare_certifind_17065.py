"""Convert the MOLDAC (Moldova) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_md_moldac_17065.py): moldac_17065_raw.json and documents/<OCpr-NNN>/*.pdf (certificate + annexes,
one annex per CAEM/NACE division). Output: bodies.csv, accreditations.csv, scopes.csv (header only),
product_scopes.csv in <dataset dir>, and moldac_17065_review.md next to this script.

Annex tables are read with pdfplumber: NR. | NR. CAPITOL NC | POZIŢIA TARIFARĂ NC | DENUMIRE PRODUS / GRUPĂ |
DOCUMENT NORMATIV PRODUS | SCHEMĂ / SISTEM / MODUL DE CERTIFICARE | DOCUMENT CARE DESCRIE SCHEMA. A full-width row
(legal basis, e.g. "Hotărârea Guvernului nr. 913 ...") is a heading carried into scheme_text of the rows below.
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

AB_CODE = "MOLDAC"
STD = "ISO/IEC 17065"
# MS dataset rows of the same companies (moldac-moldova/bodies.csv), matched by a name fragment
MS_MATCH = {"Metrologie Aplicat": "ÎS Centrul de Metrologie Aplicată și Certificare", "CERTMATCON": "Certmatcon SRL"}
# annex title / file name / page-1 division -> industry (first match wins)
TITLE_INDUSTRY = [(re.compile(p, re.I), ind) for p, ind in [
    (r"DOP|IGP|bauturi|băuturi|alimentar|tutun", "food"),
    (r"Agricultur|Pescuit|acvacult", "agriculture"),
    (r"jocuri de noroc|jocuri-de-noroc", "other_manufacturing"),
    (r"textile|imbracaminte|îmbrăcăminte|piele", "textiles"),
    (r"cauciuc", "rubber_plastics"),
    (r"metalurgic|constructiilor-metalice|construcțiilor metalice", "metals"),
    (r"cocserie|carbunelui|cărbunelui|titei|țiței", "energy"),
    (r"chimice", "chemicals"),
    (r"hartie|hârtie", "wood_paper"),
    (r"masinilor|mașinilor|lift", "machinery"),
    (r"minereuri|extractive|minerale nemetalice|minerale-nemetalice", "construction"),
    (r"Alte activit.{1,3}i industriale|Alte-activitati-industriale", "other_manufacturing"),
]]
RO_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"\bvin|bere|apă|ape minerale|lapte|carne|pâine|panific|zahăr|conserve|alimentar|băutur|tutun|țigar", "food"),
    (r"semin|fructe|legume|cereale|cartof|plante|animal", "agriculture"),
    (r"beton|ciment|mortar|zidărie|agregat|cărămid|bitum|var\b|gips|construcți|termoizol", "construction"),
    (r"lift|ascensor|cazan|presiune|mașin|utilaj|macara", "machinery"),
    (r"oțel|otel|metal|aluminiu", "metals"),
    (r"electric|aparat|joc|terminal", "electrical"),
    (r"plastic|polietilen|PVC|polimer|cauciuc|ambalaj", "rubber_plastics"),
    (r"îngrășăm|ingrasam|vopsea|lac\b|chimic|detergent|cosmetic", "chemicals"),
    (r"combustibil|benzin|motorin|gaz|petrol", "energy"),
    (r"textil|îmbrăcăminte|încălțăminte|piele|tricot", "textiles"),
    (r"hârtie|carton|lemn|mobil", "wood_paper"),
]]
TYPE_17067 = re.compile(r"^(?:[1-6][ab]?\s*(?:,|și|si)?\s*)+$")
HEAD_RX = re.compile(r"^(NR\.?|NR\.? CAPITO)", re.I)
BOILER = re.compile(r"^(\d\s*Document normativ|\d\s*Schem|Aprobat|Șef|Sef|Semnătura|Director|Pagina|ANEXA)", re.I)
NC_ROLES = {"no": r"^NR\.?$", "product_text": r"DENUMIRE|CATEGORIE DE PRODUSE", "nc": r"CAPITO|TARIF|CATEGORIE", "normative_docs": r"NORMATIV",
            "module": r"SCHEM|SISTEM|MODUL", "procedure": r"DESCRIE"}


def clean(t):
    return gr.clean((t or "").replace("\n", " "))


def scheme_of(t: str):
    p = gr.probe(t)
    cites_eu = re.search(r"\((UE|EU|CE|CEE|EC)\)|\b(Regulamentul|Directiva|Regulation|Directive)\b", t)
    eu = next((c for rx, c in gr.EU_RX if rx.search(p)), None) if cites_eu else None
    if eu:
        return eu
    if re.search(r"Hotărâr|Hotarar|\bHG\b|Lege|Ordin|Reglementar", t):
        return None
    return next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def roles_of(row):
    roles, last = [], "skip"
    for c in row:
        c = clean(c).upper()
        for role, rx in NC_ROLES.items():
            if c and re.search(rx, c):
                last = role
                break
        roles.append(last)
    return roles


def title_industry(*texts):
    for t in texts:
        hit = next((ind for rx, ind in TITLE_INDUSTRY if rx.search(t or "")), None)
        if hit:
            return hit
    return None


def parse_pdf(path: Path, title: str, audit, reg):
    lines, roles, heading = [], None, ""
    with pdfplumber.open(path) as pdf:
        first = pdf.pages[0].extract_text() or ""
        m = re.search(r"Diviziune[^:]*:\s*(.+)", first)
        division = m.group(1).strip() if m else ""
        industry = title_industry(title, path.name, division)
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [clean(c) for c in row]
                    filled = [c for c in cells if c]
                    if not filled:
                        continue
                    if any(re.search(r"DENUMIRE|CATEGORIE DE PRODUSE", c, re.I) for c in cells):
                        roles = roles_of(row)
                        continue
                    if HEAD_RX.match(filled[0]) and len(filled[0]) < 25 and not roles:
                        continue
                    if BOILER.match(filled[0]):
                        audit["boilerplate"].append((reg, filled[0][:100]))
                        continue
                    if len(filled) == 1 and (len(filled[0]) > 60 or re.search(r"^DOMENIUL|Hotăr|HG|Lege|Ordin|Regulament|Reglement", filled[0])) \
                            and (not roles or roles[cells.index(filled[0])] != "product_text" or len(cells) > 1 and cells[0] == filled[0]):
                        heading = filled[0]  # legal basis of the rows below
                        audit["legal-basis heading (carried into scheme_text)"].append((reg, heading[:100]))
                        continue
                    if not roles or len(roles) != len(cells):
                        audit["row outside a recognised table"].append((reg, " | ".join(filled)[:150]))
                        continue
                    f = collections.defaultdict(list)
                    for r, c in zip(roles, cells):
                        if c:
                            f[r].append(c)
                    f = {k: " ".join(v) for k, v in f.items()}
                    prod, norm = f.get("product_text", ""), f.get("normative_docs", "")
                    module = f.get("module", "")
                    m17 = re.match(r"^((?:[1-6][ab]?(?![+\d])\s*(?:,|și|si)?\s*)+)\s(.*)$", module)
                    if m17:  # "1b, 2, 3 PC-04 Procedura ..." -> drop the ISO/IEC 17067 type
                        audit["ISO/IEC 17067 scheme type"].append((reg, m17.group(1).strip()))
                        module = m17.group(2).strip()
                    if re.match(r"^(P\s?C|PC|P CP|PO|Procedur|Reguli generale)", module, re.I):
                        audit["internal procedure name (dropped from scheme_text)"].append((reg, module[:80]))
                        module = ""
                    else:
                        module = re.split(r"\s(?=P\s?C[-\s]|PC[-\s„\"]|P CP-|Procedur|Reguli generale)", module)[0].strip()
                    if module and TYPE_17067.match(module):
                        audit["ISO/IEC 17067 scheme type"].append((reg, module))
                        module = ""
                    if not prod and not f.get("no") and lines and (norm or module):
                        prev = lines[-1]  # continuation of the row above
                        if norm:
                            prev["normative_docs"] = (prev["normative_docs"] + " " + norm).strip()
                        if module:
                            prev["module"] = (prev["module"] + "; " + module).strip("; ")
                        continue
                    if not prod and not norm:
                        if f.get("procedure") or f.get("nc") or f.get("no"):
                            audit["procedure / NC / number only"].append((reg, " | ".join(filled)[:100]))
                        continue
                    if not prod and lines:
                        prod = ""
                    lines.append({"product_text": prod, "normative_docs": norm, "module": module,
                                  "heading": heading, "industry": industry, "nc": f.get("nc", "")})
    for ln in lines:
        ln["scheme_text"] = "; ".join(x for x in (ln["heading"], ln["module"]) if x)
    return lines, industry, division


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "moldac_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)
    ms = {r["name"]: r for r in csv.DictReader(open(data_root / "moldac-moldova" / "bodies.csv", encoding="utf-8"))}
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "moldac-moldova" / "accreditations.csv", encoding="utf-8"))}

    bodies, accs, ps = [], [], []
    for rec in raw:
        reg = rec["registration_no"]
        if rec["status"] != "Activ":
            review["Skipped (not accredited)"].append(f"{reg} {rec['name']}: {rec['status']} {rec['remark']}")
            continue
        # "OC produse din cadrul SRL „X”" -> the company "SRL „X”"
        name = re.sub(r"^OC produse\s+(din cadrul\s+)?", "", gr.clean(rec["name"]))
        name = re.sub(r"[„“”\"]|,,", "\"", name)
        name = re.sub(r"\"\s*([^\"]+?)\s*\"", r"„\1”", name).strip()
        name = re.sub(r"”(?=\w)", "” ", name)
        ms_name = next((v for k, v in MS_MATCH.items() if k.lower() in name.lower()), None)
        if ms_name:
            body = dict(ms[ms_name])
            review["Bodies reused"].append(f"{reg} `{body['name']}` from moldac-moldova (same company)")
        else:
            ph = rec["phone"].split(",")[0]
            d = re.sub(r"\D", "", ph)
            if d.startswith("373"):
                d = d[3:]
            d = d.lstrip("0")
            if len(d) == 7 and ph.startswith("(+373 231)"):
                d = d  # Bălţi area code already inside
            phone = f"+373 {d[:2]} {d[2:5]} {d[5:]}" if len(d) == 8 else ""
            if not phone and ph:
                review["Invalid phones"].append(f"{reg} {name}: `{ph}` left empty")
            if len(d) == 8 and d.startswith("231"):
                phone = f"+373 231 {d[3:]}"
            web = rec["website"].strip()
            if web and not web.startswith("http"):
                web = "https://" + web
            body = {"name": name, "country": "Moldova", "registration_no": "", "phone": phone,
                    "email": rec["email"].strip().lower(), "website": web.rstrip("/"),
                    "address": gr.clean(rec["address"]), "source_url": "https://acreditare.md/en/register_category/organisme-de-certificare-a-produselor/",
                    "verified_at": ""}
        lines = []
        folder = a.scrape / "documents" / reg
        titles = dict(zip([u.rsplit("/", 1)[-1] for u in rec["annex_urls"]], rec.get("annex_titles") or []))
        for url in rec["annex_urls"]:
            fn = url.rsplit("/", 1)[-1]
            path = folder / fn
            if not path.exists():
                review["Annexes missing"].append(f"{reg}: {fn}")
                continue
            got, ind, division = parse_pdf(path, titles.get(fn, ""), audit, reg)
            if not ind:
                review["Annexes without a division industry (line words used)"].append(f"{reg} {fn} `{division}`")
            if not got:
                review["Annexes without rows"].append(f"{reg} {fn}")
            lines += got
        if not lines:
            review["Bodies dropped (no line)"].append(f"{reg} {name}")
            continue
        cert = reg if reg not in used else f"{reg} (17065)"
        issued = rec["certificate_file_date"] or ""
        if not issued:  # the annex header: "Nr. OCpr - 054 din 02.04.2026"
            for url in rec["annex_urls"]:
                path = folder / url.rsplit("/", 1)[-1]
                if path.exists():
                    with pdfplumber.open(path) as pdf:
                        m = re.search(r"OCpr\s*[-–]\s*\d+\s*din\s*(\d\d)\.(\d\d)\.(\d{4})", pdf.pages[0].extract_text() or "")
                    if m:
                        issued = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                        review["Issue date from the annex"].append(f"{reg}: {issued}")
                        break
        bodies.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": issued, "expiry_date": "",
                     "proof_url": rec.get("certificate_url") or body["source_url"]})
        for n, ln in enumerate(lines, 1):
            full = " ".join([ln["product_text"], ln["scheme_text"], ln["normative_docs"]])
            s = scheme_of(full) or ""
            ind = "" if s else (ln["industry"] or next((i for rx, i in RO_WORDS if rx.search(full)), None)
                                or gr.industry_of(full) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": s, "industry": ind,
                       "product_text": ln["product_text"], "product_text_en": "", "scheme_text": ln["scheme_text"],
                       "normative_docs": ln["normative_docs"], "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if reg in a.debug:
                print(n, s, "|", ind, "|", ln["product_text"][:60], "|", ln["scheme_text"][:50], "|", ln["normative_docs"][:50])

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
    out = [f"# MOLDAC 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Lines per body", ""] + [f"- {c}: {n}" for c, n in collections.Counter(p['certificate_number'] for p in ps).items()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Rows not imported", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]}" for p in neither]
    (HERE / "moldac_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
