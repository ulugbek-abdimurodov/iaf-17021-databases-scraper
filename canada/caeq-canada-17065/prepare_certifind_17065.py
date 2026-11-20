"""Convert the CAEQ (Québec) register scrape into the CertiFind ISO/IEC 17065 dataset.

Usage: python prepare_certifind_17065.py <scrape dir> <dataset dir>
<scrape dir> holds caeq_17065_raw.json + scope_lines.csv from scrape_ca_caeq_17065.py.

CAEQ (Conseil des appellations réservées et des termes valorisants) accredits organic and Québec
reserved-designation certification bodies. Its register has no annex tables: each body card lists its
appellations (Organic, Québec designations), product categories (Canada Organic Regime categories, or
EU 2018/848 Art. 35(7) categories (a)-(g) for bodies with EU-equivalence scope) and a geographic scope.
Lines = appellations + product categories. Geographic-scope entries are countries, not products; they are
logged as dropped and listed per accreditation in the review.
"""
import collections, csv, datetime, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_ROOT = HERE.parents[2] / "certifind" / "data"
AB_CODE = "CAEQ"
STD = "ISO/IEC 17065"
REGISTER = "https://caeq.ca/accredited-organizations/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
COUNTRY_FIX = {"Türkiye": "Turkey", "Czech Republic": "Czechia", "Viet Nam": "Vietnam", "Korea": "South Korea",
               "Argentine": "Argentina", "Mexique": "Mexico", "Inde": "India", "États-Unis": "United States",
               "Etats-Unis": "United States", "Brésil": "Brazil", "USA": "United States"}
DIAL = {"Canada": "1", "United States": "1", "Mexico": "52", "India": "91", "Brazil": "55", "Argentina": "54",
        "Costa Rica": "506"}
_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
       "november", "december"]
_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
       "novembre", "décembre"]
MONTHS = {**{m: i for i, m in enumerate(_EN, 1)}, **{m: i for i, m in enumerate(_FR, 1)}}

COR = "Canada Organic Regime (COR)"
EU_ORG = "EU Organic Regulation (EU) 2018/848"
QC = "Québec Reserved Designations (CARTV)"
# new scheme code -> (owner, kind, industry)
NEW_SCHEMES = {COR: ("Canadian Food Inspection Agency", "STANDARD", "agriculture"),
               QC: ("CARTV (Gouvernement du Québec)", "PRIVATE", "food")}
QC_RX = re.compile(r"Quebec|Québec|Charlevoix|Neuville|Canadienne|Farmstead|fermier|Acerum", re.I)
EU_CAT = re.compile(r"^\([a-g]\)|2018/848")
DROP_GEO = "Geographic scope entry (country where the body may certify, not a product)"
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"alcohol|wine|cider|processed|food|maple|cheese", "food"),
    (r"feed|livestock|animal|crop|plant|seed|wild harvest|fungi|aquaculture|algae|grower|production", "agriculture"),
    (r"trad", "trade_logistics"),
]]
REF = re.compile(r"CAN/CGSB[- ]32\.31[01]|\b20\d\d/\d{3,4}\b")
WS = re.compile(r"\s+")


def key(s):
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"\b(inc|ltd|llc|s\.? ?a|co-operative|co|limited|s de rl de cv|s\. de r\.l\. de c\.v)\b\.?", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def iso(d):
    m = re.match(r"(\d{1,2})\s+(\S+)\s+(\d{4})", d or "")
    if not m or m.group(2).lower() not in MONTHS:
        return ""
    return datetime.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()


def phone(raw, country):
    p = re.split(r"\||/|,|;|\bext\b", raw or "")[0]
    d = re.sub(r"\D", "", p)
    if not d:
        return ""
    cc = DIAL.get(country, "")
    if p.strip().lstrip("(").startswith("+") or d.startswith("00"):
        d = d[2:] if d.startswith("00") else d
        return "+" + (cc + d[len(cc) + 1:] if cc and d.startswith(cc + "0") else d)
    if cc == "1" and len(d) == 11 and d.startswith("1"):
        return "+" + d
    if cc and d.startswith(cc) and len(d) > 10:
        return "+" + d
    return f"+{cc}{d.lstrip('0')}" if cc else d


def write(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)


def load_bodies(out):
    by_name = {}
    for f in sorted(DATA_ROOT.glob("*/bodies.csv")):
        if f.parent.resolve() == out.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig", newline="")):
            by_name.setdefault((key(r["name"]), r["country"]), (f.parent.name, r))
    return by_name


def classify(src, text):
    """-> (scheme, industry, scheme_text), or None when the line is dropped."""
    if src == "geographic_scope":
        return None
    if src == "appellation":
        if re.fullmatch(r"organic|biologique", text, re.I):
            return COR, "", "Organic (Canada Organic Regime, SFCR Part 13 / CAN/CGSB-32.310)"
        if QC_RX.search(text):
            return QC, "", "Québec reserved designation (Act respecting reserved designations and added-value claims)"
        return "", "food", ""
    if EU_CAT.search(text):
        return EU_ORG, "", "EU 2018/848 Art. 35(7) product category (equivalence)"
    return COR, "", "Organic product category"


def main(scrape_dir, out_dir):
    src, out = Path(scrape_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = json.load(open(src / "caeq_17065_raw.json", encoding="utf-8"))
    lines = list(csv.DictReader(open(src / "scope_lines.csv", encoding="utf-8", newline="")))
    known = load_bodies(out)
    review = collections.defaultdict(list)
    regs = collections.Counter(r["registration_no"] for r in raw)
    # Cards sharing one CAEQ number are one accreditation: a card without a date takes its sibling's.
    reg_dates = {r["registration_no"]: r["issued"] for r in raw if r["issued"]}
    for r in raw:
        if not r["issued"] and reg_dates.get(r["registration_no"]):
            r["issued"] = reg_dates[r["registration_no"]]
            review.setdefault("dates", []).append(
                f"{r['name']}: no accreditation date; used '{r['issued']}' from the other {r['registration_no']} card")
    bodies, accs, ps, cert_of = {}, [], [], {}
    for r in raw:
        country = COUNTRY_FIX.get(r["country"], r["country"])
        reg = r["registration_no"]
        cert = reg if regs[reg] == 1 else f"{reg} ({country})"
        if regs[reg] > 1:
            review["certs"].append(f"{r['name']}: CAEQ no. {reg} is shared by {regs[reg]} cards -> `{cert}`")
        if not reg.startswith("AC-"):
            review["certs"].append(f"{r['name']}: no CAEQ certificate no. on the register; CFIA no. `{reg}` used")
        cert_of[r["id"]] = cert
        hit = known.get((key(r["name"]), country))
        if hit:
            name = hit[1]["name"]
            bodies[(name, country)] = {c: hit[1].get(c, "") for c in BODY_COLUMNS}
            review["reused"].append(f"{r['name']} ({country}) -> existing row '{name}' from data/{hit[0]}")
        else:
            name = WS.sub(" ", r["name"]).strip()
            bodies[(name, country)] = {
                "name": name, "country": country, "registration_no": reg, "phone": phone(r["phone"], country),
                "email": r["email"].split()[0] if r["email"] else "", "website": r["website"],
                "address": r["address"], "source_url": REGISTER, "verified_at": ""}
        if r["issued"] and not iso(r["issued"]):
            review["dates"].append(f"{r['name']}: '{r['issued']}'")
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": name, "accreditation_standard": STD,
                     "status": "ACTIVE", "issue_date": iso(r["issued"]), "expiry_date": "",
                     "proof_url": (r["annex_urls"] or [REGISTER])[0]})

    n, geo = collections.Counter(), collections.defaultdict(list)
    dropped, drop_bodies = collections.Counter(), collections.defaultdict(set)
    for l in lines:
        cert, text = cert_of[l["id"]], WS.sub(" ", l["product_text_raw"]).strip()
        c = classify(l["source"], text)
        if c is None:
            dropped[DROP_GEO] += 1
            drop_bodies[DROP_GEO].add(cert)
            geo[cert].append(text)
            continue
        scheme, industry, stext = c
        if not scheme:
            industry = next((i for rx, i in INDUSTRY_WORDS if rx.search(text)), industry)
        n[cert] += 1
        ps.append({"certificate_number": cert, "line_no": n[cert], "scheme": scheme, "industry": industry,
                   "product_text": text, "product_text_en": "", "scheme_text": stext, "normative_docs": "",
                   "standard_refs": ";".join(dict.fromkeys(REF.findall(text))), "status": "ACTIVE"})

    write(out / "bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda b: b["name"]))
    write(out / "accreditations.csv", ACC_COLUMNS, accs)
    write(out / "scopes.csv", SCOPE_COLUMNS, [])
    write(out / "product_scopes.csv", PS_COLUMNS, ps)

    used = collections.Counter(p["scheme"] for p in ps)
    no_scheme = collections.Counter(x for p in ps if not p["scheme"] for x in p["standard_refs"].split(";") if x)
    rv = ["# CAEQ 17065 review", "",
          f"Register: {REGISTER} (server-rendered HTML; no annex tables - scope = appellations + product "
          "categories on each body card; proof_url = the card's attestation PDF).", "",
          "## Lines left out", ""]
    rv += [f"- {k}: {v} lines, {len(drop_bodies[k])} bodies" for k, v in dropped.items()] or ["- none"]
    rv += ["", "Geographic scope per accreditation:", ""] + [f"- {c}: {', '.join(g)}" for c, g in geo.items()]
    rv += ["", "## Bodies dropped", "", "- none (every CAEQ accreditation is product certification)", "",
           "## Body rows reused", ""] + ([f"- {x}" for x in review["reused"]] or ["- none"])
    rv += ["", "## Certificate numbers", ""] + ([f"- {x}" for x in review["certs"]] or ["- none"])
    if review["dates"]:
        rv += ["", "## Dates", ""] + [f"- {x}" for x in review["dates"]]
    rv += ["", "## Bilingual pairing failures", "", "- n/a (English register, no bilingual annexes)", "",
           "## New scheme codes (V82__caeq_17065_reference_data.sql)", ""]
    rv += [f"- `{c}` ({k}, owner {o}): {used[c]} lines" for c, (o, k, _) in NEW_SCHEMES.items()]
    rv += ["", "## Scheme usage", ""] + [f"- {c or '(none)'}: {v}" for c, v in used.most_common()]
    rv += ["", "## Most frequent standard_refs on lines without a scheme", ""]
    rv += [f"- {x}: {v}" for x, v in no_scheme.most_common(10)] or ["- none"]
    (HERE / "caeq_17065_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\n"
          f"Product lines (with scheme): {len(ps)} ({sum(1 for p in ps if p['scheme'])})\n"
          f"Dropped lines: {sum(dropped.values())}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
