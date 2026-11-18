"""BELAC ISO/IEC 17065 scrape (PROD, product certification bodies) -> CertiFind dataset.

Usage: python prepare_certifind_17065.py [scrape folder] [dataset dir] [--today YYYY-MM-DD]
Input: belac_prod_data/ written by belac_prod_scraper.py (bodies.csv, annex_scope.csv).
Product lines come from the annex tables (annex_scope.csv): one line per table row, with the section
heading above it as context. Rules: .claude/skills/add-country-17065/SKILL.md in the certifind repo.
"""
import argparse, collections, csv, importlib.util, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent  # .../CertiFind/database
DATA = DB.parent / "certifind" / "data"


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


it = _load("accredia_17065", DB / "italy" / "accredia-italy-17065" / "prepare_certifind_17065.py")
de = _load("dakks_17065", DB / "germany" / "prepare_certifind_17065.py")
clean = it.clean

AB_CODE = "BELAC"
STD = "ISO/IEC 17065"
COUNTRY = {"België": "Belgium", "Belgique": "Belgium", "Nederland": "Netherlands", "Pays-Bas": "Netherlands",
           "Deutschland": "Germany", "Frankrijk": "France"}

# rows that are not scope: annex header, column headers, footnotes
SKIP_ROW = re.compile(
    r"^(Version|Versie|Validit|Geldigheid)|Fassung|Gültigkeitsdauer|"
    r"^(Domaine d.application|Toepassingsdomein|Scope of application|Application|Toepassing|Produits?|Producten|"
    r"Products?|Référentiel|Referentieel|Standard|Norme?|Document|AVCP|Système AVCP|Systeem|Beschikking|Décision|"
    r"Catégories|Pays|Land|Description|Beschrijving|Secteur)\s*(\(|/|$|\|\|)|^\(\*\)|^\*|^Scope (fixe|flexible)$|"
    r"^Flexibele scope$|^Vaste scope$|^Portée (fixe|flexible)$", re.I)
SKIP_CELL = re.compile(r"^[\d+&\s,;/]+$|^(TRA|ARCP|BRCP|CERT|PROC|PR|IP|P)\b[\w .-]*\d|^(Annexe|Bijlage) [IVX]+$|"
                       r"^-$|^n\.?a\.?$", re.I)
REF_CELL = re.compile(r"\b(EN|ISO|IEC|NBN|CEN|ETAG|EAD|PTV|STS|TR)\s?[\d/-]|\b\d{2,4}/\d{2,4}/(EC|EG|CE|EU|UE|EEC)\b|"
                      r"R(è|e)glement|Verordening|Regulation|Richtlijn|Directive|Arrêté|Besluit|\bModule\b", re.I)
REGION = re.compile(r"^(En Belgique|In België|Pays europ|Europese landen|European countries|Hors|Buiten|Outside)\b",
                    re.I)
CPR_DECISION = re.compile(r"\b(9\d|19\d\d|20\d\d)/\d{2,3}/(EC|EG|CE)\b")
# Belgian / French national schemes: kept as text with a sector
NATIONAL = [(re.compile(p, re.I), ind) for p, ind in [
    (r"Vegaplan|BELPLUME|CODIPLAN|BEPORK|FEBEV|Belbeef|QFL|IKM|Certus|Meritus", "agriculture"),
    (r"autocontr[oô]l|AFSCA|FAVV|FASFC|G-0\d\d", "food"),
    (r"Feed Chain Alliance|OVOCOM|\bFCA\b|RCNA|OQUALIM|alimentation animale|diervoeder", "food"),
    (r"BENOR|\bATG\b|CEBEC|KOMO", "construction"),
]]
EU_EXTRA = [(re.compile(p, re.I), c) for p, c in [  # at two or more BELAC bodies (V73)
    (r"2013/53|bateaux de plaisance|pleziervaartuigen|recreational craft", "Recreational Craft Directive 2013/53/EU"),
    (r"2014/90|équipements marins|uitrusting van zeeschepen|marine equipment", "Marine Equipment Directive 2014/90/EU"),
]]


def read(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))


def scheme_of(t):
    return (next((c for rx, c in EU_EXTRA if rx.search(t)), None) or de.scheme_of(t)
            or ("Construction Products Regulation (EU) 305/2011" if CPR_DECISION.search(t) else None))


def industry_of(t):
    return next((i for rx, i in NATIONAL if rx.search(t)), None) or de.industry_of(t) or ""


def make(prod, sch_t, norm, ctx):
    own = " ".join([prod, sch_t, norm])
    sc = scheme_of(own) or scheme_of(ctx)
    ind = "" if sc else (industry_of(own) or industry_of(ctx))
    return {"scheme": sc or "", "industry": ind, "product_text": prod, "product_text_en": "", "scheme_text": sch_t,
            "normative_docs": norm, "standard_refs": it.refs(own), "status": "ACTIVE"}


def lines_of(rows, dropped, number):
    out, section, children, sec_line, last_prod = [], "", 0, None, ""
    for r in rows:
        cells = [clean(r[f"col{i}"]) for i in range(1, 9) if clean(r[f"col{i}"])]
        if not cells:
            continue
        joined = " || ".join(cells)
        if (int(r["page"]) <= 5 and re.search(r"Version|Validit|Geldigheid", joined, re.I)) or SKIP_ROW.search(joined):
            dropped["annex header, column header or footnote"].append(number)
            continue
        if len(cells) == 1:  # a section heading, or a reference continuing the row above
            c = cells[0]
            if REGION.match(c) or SKIP_CELL.match(c):
                dropped["region / system code only"].append(number)
                continue
            if REF_CELL.search(c) and out and children and len(c) < 120:
                out[-1]["normative_docs"] = (out[-1]["normative_docs"] + "; " + c).strip("; ")
                out[-1]["standard_refs"] = it.refs(out[-1]["normative_docs"] + " " + out[-1]["product_text"])
                continue
            if sec_line is not None and children == 0 and len(sec_line["product_text"]) >= 25:
                out.append(sec_line)
            section, children, last_prod = c, 0, ""
            sec_line = make(c, "", "", "")
            continue
        prod, norm = [], []
        for i, c in enumerate(cells):
            if SKIP_CELL.match(c) or REGION.match(c):
                continue
            (norm if i > 0 and REF_CELL.search(c) else prod).append(c)
        if prod:
            last_prod = prod[0]
        elif last_prod:
            prod = [last_prod]
        if not prod and not norm:
            dropped["region / system code only"].append(number)
            continue
        out.append(make(" — ".join(prod), section, "; ".join(norm), section))
        children += 1
    if sec_line is not None and children == 0:
        out.append(sec_line)
    return out


def phone(raw):
    """First number in international form: '(0476)87 44 34 (Name)' -> '+32 476 87 44 34' (from 17021 converter)."""
    first = re.split(r"\s+/|/\s*\(|\s+-\s+", raw or "")[0]
    first = re.sub(r"\([A-Za-z][^)]*\)", "", first).strip().replace(".", " ")
    if m := re.match(r"\((0\d+)\)\s*(.*)", first):
        first = f"+32 {m.group(1)[1:]} {m.group(2)}"
    elif first.startswith("00"):
        first = "+" + first[2:].lstrip()
    elif first.startswith("0"):
        first = "+32 " + first[1:]
    first = re.sub(r"\s+", " ", first).strip()
    return first if first.startswith("+") else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path, nargs="?", default=HERE / "belac_prod_data")
    ap.add_argument("out", type=Path, nargs="?", default=DATA / "belac-belgium-17065")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # 17021 bodies: enterprise number -> certificationNumber (raw 17021 scrape) -> row of data/belac-belgium
    ms_rows = {r["registration_no"]: r for r in read(DATA / "belac-belgium" / "bodies.csv")}
    by_ent = {}
    for r in read(HERE.parent / "17021" / "belac_qms_data" / "bodies.csv"):
        if r.get("enterpriseNumber", "").strip() and r["certificationNumber"] in ms_rows:
            by_ent[r["enterpriseNumber"].strip()] = ms_rows[r["certificationNumber"]]
    by_name = {}
    for f in sorted(DATA.glob("*/bodies.csv")):
        if f.parent.name == "belac-belgium-17065":
            continue
        for r in read(f):
            by_name.setdefault((it.key(r["name"]), r["country"]), (f.parent.name, r))

    annex = collections.defaultdict(list)
    for r in read(args.scrape / "annex_scope.csv"):
        annex[r["certificationNumber"]].append(r)

    review, reused, dropped = [], [], collections.defaultdict(list)
    bodies, accs, ps = [], [], []
    for b in sorted(read(args.scrape / "bodies.csv"), key=lambda r: r["certificationNumber"]):
        number = b["certificationNumber"].strip()
        name = clean(b["name"])
        country = COUNTRY.get(b["country"].strip(), b["country"].strip()) or "Belgium"
        website = b["url"].strip().rstrip("/").split(" ")[0]
        if website and not website.startswith("http"):
            website = "https://" + website
        street = " ".join(p for p in (clean(b["street"]), b["streetNumber"].strip()) if p)
        if b.get("postBox", "").strip():
            street += f" bus {b['postBox'].strip()}"
        body = {"name": name, "country": country, "registration_no": number, "phone": phone(b["telephone"]),
                "email": b["email"].split(",")[0].strip(), "website": website,
                "address": ", ".join(p for p in (street, f"{b['postCode']} {b['municipality']}".strip()) if p),
                "source_url": b.get("detail_page") or f"https://weblist.economie.fgov.be/en/belac/prodCert/{number}",
                "verified_at": ""}
        ent = (b.get("enterpriseNumber") or "").strip()
        if ent in by_ent:
            body = dict(by_ent[ent])
            reused.append(f"{name} ({number}): enterprise number {ent} -> belac-belgium row '{body['name']}'")
        elif (it.key(name), country) in by_name:
            ds, row = by_name[(it.key(name), country)]
            body = dict(row)
            reused.append(f"{name} ({number}) -> '{row['name']}' from {ds}")
        elif not body["phone"] and b["telephone"].strip() not in ("", "/"):
            review.append(f"{number} {name}: phone '{b['telephone']}' not made international; left empty")

        rows = sorted(annex.get(number, []), key=lambda r: (int(r["page"]), int(r["table"]), int(r["row"])))
        seen, lines = set(), []
        for g in lines_of(rows, dropped, number):
            k = (g["product_text"], g["scheme_text"], g["normative_docs"])
            if k in seen:
                dropped["duplicate line (same product in several regions or rows)"].append(number)
                continue
            seen.add(k)
            lines.append(g)
        if not lines:
            review.append(f"{name} ({number}): no annex line; left out")
            continue
        valid_from, valid_to = b.get("valid_from", ""), b.get("valid_to", "")
        if not valid_from:  # the scraper wants "from - to"; some annexes print the dates without the dash
            for r in rows:
                if m := re.search(r"(\d{4}-\d{2}-\d{2})\s*[-–]?\s*(\d{4}-\d{2}-\d{2})", r["col1"]):
                    valid_from, valid_to = m.groups()
                    break
        bodies.append(body)
        accs.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": valid_from,
                     "expiry_date": valid_to, "proof_url": b.get("pdf_url") or body["source_url"]})
        for n, l in enumerate(lines, 1):
            ps.append({"certificate_number": number, "line_no": n, **l})

    for nm, c in collections.Counter(b["name"] for b in bodies).items():
        if c > 1:
            review.append(f"DUPLICATE body name {nm} x{c}")
    it.write(args.out / "bodies.csv", it.ms.BODY_COLUMNS, sorted(bodies, key=lambda r: r["name"].casefold()))
    it.write(args.out / "accreditations.csv", it.ms.ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    it.write(args.out / "scopes.csv", it.ms.SCOPE_COLUMNS, [])
    it.write(args.out / "product_scopes.csv", it.PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    with open(HERE / "belac_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# BELAC ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, "
                 f"{len(accs)} accreditations, {len(ps)} product lines ({with_scheme} with a scheme).\n\n")
        fh.write("## Lines left out (reason: lines)\n\n")
        fh.writelines(f"- {k}: {len(v)}\n" for k, v in sorted(dropped.items(), key=lambda kv: -len(kv[1])))
        fh.write("\n## Body rows reused from other datasets\n\n" + "".join(f"- {l}\n" for l in reused))
        fh.write("\n## Notes\n\n" + "".join(f"- {l}\n" for l in dict.fromkeys(review)))
    print(f"bodies {len(bodies)}, accreditations {len(accs)}, product lines {len(ps)} ({with_scheme} with scheme)")


if __name__ == "__main__":
    main()
