"""TUNAC ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py [scrape out (default tunac_17065)] [dataset dir] [--exclude]

Input: tunac_17065_raw.json and scope_lines.csv from scrape_tn_tunac_17065.py. TUNAC annexes (F.C.48B) are
French tables: "Programme (spécifique) de certification : <scheme>" heading, the ISO/IEC 17067 type, then rows
"family | product | requirements | remarks". The heading decides the scheme and is carried to the rows below it
(sticky); the requirements column goes to normative_docs. Annexes are French only, so product_text_en is empty.
Layout follows ../../italy/accredia-italy-17065/prepare_certifind_17065.py.
"""
import collections, csv, json, re, sys, unicodedata, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent                      # .../CertiFind/database
DATA = DB.parent / "certifind" / "data"

AB_CODE = "TUNAC"
STD = "ISO/IEC 17065"
REGISTER_URL = "https://www.tunac.tn/webtunac.nsf/rechercheroec.html"
MS_DATASET = "tunac-tunisia"                 # the AB's 17021 dataset
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                         "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
COUNTRY_FIX = {"Côte d'Ivoire": "Côte d’Ivoire", "Cote d'Ivoire": "Côte d’Ivoire", "Türkiye": "Turkey", "Korea": "South Korea",
               "Republic of Korea": "South Korea", "Czech Republic": "Czechia", "UAE": "United Arab Emirates",
               "Viet Nam": "Vietnam", "Tunisie": "Tunisia", "Maroc": "Morocco"}
DIAL = {"Tunisia": "216", "Morocco": "212", "Côte d’Ivoire": "225"}

# Per accreditation: the annex's "Nom de l'organisme" (the register gives an acronym) and the country of the
# main site. SAME_AS names a row of another dataset that is the same legal entity under a different spelling.
BODY_INFO = {
    "3-0014": ("INNORPI", "Tunisia"),
    "3-0020": ("CERMED SARL", "Tunisia"),
    "3-0021": ("APAVE CI", "Côte d'Ivoire"),
    "3-0023": ("Ecocert Tunisie", "Tunisia"),
    "3-0025": ("CTPC – Centre Technique de Plasturgie et de Caoutchouc", "Morocco"),
}
SAME_AS = {
    "3-0014": "Institut National de la Normalisation et de la Propriété Industrielle (INNORPI)",  # tunac-tunisia 3-0001
    "3-0021": "APAVE CÔTE D’IVOIRE",                                                              # soac-cote-divoire
}
EMAIL_FIX = {"3-0023": "imen.jaouadi@ecocert.com"}  # annex contact; the register lists a group address
ADDRESS_FIX = {"3-0025": "Complexe des Centres Techniques, Boulevard Abdelmalek Essaâdi, Sidi Maârouf, Casablanca, Morocco"}

# (regex, scheme code). First match wins, specific before general. Copied from the ACCREDIA table, plus the
# TUNAC-only codes added in V75__tunac_17065_reference_data.sql (marked NEW).
EU_SCHEMES = [
    (r"305/2011|2011/305|Prodotti da costruzione|Produits de construction|Construction products", "Construction Products Regulation (EU) 305/2011"),
    (r"2023/1230", "Machinery Regulation (EU) 2023/1230"),
    (r"2006/42", "Machinery Directive 2006/42/EC"),
    (r"2014/33", "Lifts Directive 2014/33/EU"),
    (r"2014/68|97/23", "Pressure Equipment Directive 2014/68/EU"),
    (r"2014/29", "Simple Pressure Vessels Directive 2014/29/EU"),
    (r"2014/34", "ATEX Directive 2014/34/EU"),
    (r"2014/30", "EMC Directive 2014/30/EU"),
    (r"2014/53", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/32", "Measuring Instruments Directive 2014/32/EU"),
    (r"2014/31", "Non-automatic Weighing Instruments Directive 2014/31/EU"),
    (r"2009/48", "Toy Safety Directive 2009/48/EC"),
    (r"2000/14", "Outdoor Noise Directive 2000/14/EC"),
    (r"92/42", "Hot-water Boilers Directive 92/42/EEC"),
    (r"2016/425", "PPE Regulation (EU) 2016/425"),
    (r"2016/426", "Gas Appliances Regulation (EU) 2016/426"),
    (r"2016/424", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2016/797", "Rail Interoperability Directive (EU) 2016/797"),
    (r"2019/779", "ECM Regulation (EU) 2019/779"),
    (r"402/2013", "CSM Risk Assessment Regulation (EU) 402/2013"),
    (r"2024/1143|1151/2012|\b(AOP|IGP|STG|PDO|PGI)\b", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2018/848|834/2007|production biologique|Organic certification", "EU Organic Regulation (EU) 2018/848"),
    (r"517/2014|2024/573|2015/2067|304/2008|842/2006|gaz fluorés|fluorinated", "EU F-gas Regulation"),
]
EU_CODES = {c for _, c in EU_SCHEMES}
SCHEMES = [
    (r"15343", "EN 15343"),                                                                             # NEW
] + EU_SCHEMES + [
    (r"GLOBAL ?G\.?A\.?P\.?,? *(Cha[iî]ne de (contr[ôo]le|tra[çc]abilit[ée])|Chain of Custody)", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,40}(Packaging|emballage)", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,40}(Storage and Distribution|Stockage)", "BRCGS Storage and Distribution"),
    (r"BRC\w*.{0,40}Agents? and Brokers", "BRCGS Agents and Brokers"),
    (r"BRC\w*.{0,40}Consumer Products", "BRCGS Consumer Products"),
    (r"BRC\w*.{0,40}(Food Safety|s[ée]curit[ée] des denr[ée]es)", "BRCGS Food Safety"),
    (r"IFS Wholesale", "IFS Wholesale"),
    (r"IFS Logistics", "IFS Logistics"),
    (r"IFS Broker", "IFS Broker"),
    (r"IFS (HPC|Household)", "IFS HPC"),
    (r"IFS PAC ?secure", "IFS PACsecure"),
    (r"IFS Food", "IFS Food"),
    (r"\bSQF\b", "SQF"),
    (r"GMP\+", "GMP+ FSA"),
    (r"ISCC[ -]?PLUS", "ISCC PLUS"),
    (r"ISCC[ -]?EU", "ISCC EU"),
    (r"\b2BS", "2BSvs"),
    (r"PEFC", "PEFC Chain of Custody"),
    (r"Friend of the Sea|\bFOS-", "Friend of the Sea"),
    (r"LEAF Marque", "LEAF Marque"),
    (r"EUROPRIVACY", "Europrivacy"),
    (r"910/2014|eIDAS|ETSI EN 319 4|Services? de confiance|Trust Service", "eIDAS"),
    (r"22005", "ISO 22005"),
    (r"15085", "EN 15085-2"),
    (r"3834", "ISO 3834"),
    (r"2999[0-4]", "ISO 29993"),
    (r"13009", "ISO 13009"),
    (r"GSTC", "GSTC Criteria"),
    (r"18295", "ISO 18295"),
    (r"22222", "ISO 22222"),
]
SCHEMES = [(re.compile(p, re.I), c) for p, c in SCHEMES]
NEW_SCHEMES = {
    "EN 15343": ("CEN", "STANDARD", ["rubber_plastics"]),
}

# (regex, reason). Checked on every line that is not a product row.
DROPS = [
    (r"^Type de programme selon ISO/IEC 17067", "ISO/IEC 17067 scheme type"),
    (r"^Sites? (non )?critiques?|^Site principal|^Adresse", "site / address note"),
    (r"^Pays couverts", "countries covered note"),
    (r"^\*?Port[ée]e flexible", "flexible-scope note"),
    (r"annexe technique peut faire l.objet|Chef de section|Date d.effet|Directeur G[ée]n[ée]ral", "annex boilerplate"),
]
DROPS = [(re.compile(p, re.I), r) for p, r in DROPS]
NATIONAL = re.compile(r"\bLoi\b|D[ée]cret|Arr[êe]t[ée] du minist", re.I)
KEEP_NATIONAL = re.compile(r"Loi Tunisienne n°\s?99-30|Label qualit. tunisien", re.I)  # recognized product schemes
EXCLUDE = "--exclude" in sys.argv     # drop EU organic and national lines
HEADING = re.compile(r"^Programme( sp[ée]cifique)? de certification\s*:\s*", re.I)

INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"touris|h[ôo]tel|restaura", "tourism"),
    (r"sant[ée]|health|dispositifs? m[ée]dica", "health"),
    (r"cosm[ée]ti|d[ée]tergent|chimi|pharma|peinture", "chemicals"),
    (r"plasti|caoutchouc|polym[eè]r|emballage", "rubber_plastics"),
    (r"ferroviaire|v[ée]hicule|automobile|a[ée]ronaut", "transport_equipment"),
    (r"soudage|welding|acier|alumin|m[ée]tal", "metals"),
    (r"machine|levage|pression", "machinery"),
    (r"[ée]lectri|[ée]lectroni|photovolta", "electrical"),
    (r"b[ée]ton|construction|ciment|verre|isolant", "construction"),
    (r"textile|v[êe]tement|chaussure|cuir", "textiles"),
    (r"biocarburant|combustible|[ée]nergie|hydrog[eè]ne", "energy"),
    (r"recycl|jouet|meuble|bijou", "other_manufacturing"),
    (r"\bbois\b|papier|for[êe]t|impression", "wood_paper"),
    (r"aliment|denr[ée]e|conserve|viande|lait|poisson|crustac|mollusque|boisson|harissa", "food"),
    (r"agricol|aquaculture|[ée]levage|p[êe]che", "agriculture"),
    (r"logisti|transport|entreposage|commerce", "trade_logistics"),
    (r"services", "professional"),
    (r"v[ée]g[ée]taux|agricult|biologique", "agriculture"),
]]
REF = re.compile(r"\b((?:UNI|CEI|BS|DIN|NF)\s+)*(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{3,5})((?:-\d{1,3})?)")
ETSI = re.compile(r"ETSI\s+(EN|TS)\s+(\d{3})\s+(\d{3})((?:-\d+)?)")
WS = re.compile(r"\s+")


def clean(t):
    return WS.sub(" ", t or "").strip()


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def iso(d):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def scheme_of(t):
    for rx, code in SCHEMES:
        if rx.search(t):
            return code
    return ""


def refs(t):
    out = []
    for m in REF.finditer(t):
        org = m.group(3)
        r = f"{'EN ' if m.group(2) and org != 'EN' else ''}{org} {m.group(4)}{m.group(5)}"
        if "17067" in r or "17065" in r:
            continue
        out.append(r)
    out += [f"ETSI {m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}" for m in ETSI.finditer(t)]
    return ";".join(dict.fromkeys(out))


def industry_of(*texts):
    for t in texts:
        for rx, ind in INDUSTRY_WORDS:
            if t and rx.search(t):
                return ind
    return ""


def phone(raw, country):
    digits = re.sub(r"\(0\)", "", raw or "")
    digits = re.sub(r"\D", "", digits.split("/")[0])
    if not digits:
        return ""
    cc = DIAL.get(country, "")
    if digits.startswith("00"):
        digits = digits[2:]
    if cc and not digits.startswith(cc):
        digits = cc + digits
    if cc and digits.startswith(cc):
        rest = digits[len(cc):]
        if cc == "216":
            groups = [rest[:2]] + [rest[i:i + 3] for i in range(2, len(rest), 3)]
        elif cc == "212":
            groups = [rest[:3]] + [rest[i:i + 2] for i in range(3, len(rest), 2)]
        else:
            groups = [rest[i:i + 2] for i in range(0, len(rest), 2)]
        return f"+{cc} " + " ".join(groups)
    return "+" + digits


def safe(u):
    return urllib.parse.quote(u, safe="%/:$?=&!()+,;@~*")


def load_bodies(out_dir):
    """All body rows of other datasets: by (AB 17021) registration number and by (name key, country)."""
    by_reg, by_name, by_exact = {}, {}, {}
    for f in sorted(DATA.glob("*/bodies.csv")):
        if f.parent.resolve() == out_dir.resolve():
            continue
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if f.parent.name == MS_DATASET and row["registration_no"]:
                    by_reg.setdefault(row["registration_no"], (row, f.parent.name))
                by_name.setdefault((key(row["name"]), row["country"]), (row, f.parent.name))
                by_exact.setdefault(row["name"], (row, f.parent.name))
    return by_reg, by_name, by_exact


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0]) if args else HERE / "tunac_17065"
    out = Path(args[1]) if len(args) > 1 else DATA / "tunac-tunisia-17065"
    out.mkdir(parents=True, exist_ok=True)
    recs = json.loads((src / "tunac_17065_raw.json").read_text(encoding="utf-8"))
    with open(src / "scope_lines.csv", encoding="utf-8") as fh:
        lines = collections.defaultdict(list)
        for r in csv.DictReader(fh):
            lines[r["registration_no"]].append(r)
    ms_regs = set()
    ms_acc = DATA / MS_DATASET / "accreditations.csv"
    if ms_acc.exists():
        with open(ms_acc, encoding="utf-8") as fh:
            ms_regs = {r["certificate_number"] for r in csv.DictReader(fh)}
    by_reg, by_name, by_exact = load_bodies(out)

    bodies, accs, ps = {}, [], []
    dropped = collections.Counter()
    dropped_bodies = collections.defaultdict(set)
    reused, no_scheme_refs = [], collections.Counter()
    for rec in recs:
        reg = rec["registration_no"]
        name, country = BODY_INFO.get(reg, (rec["name"], ""))
        country = COUNTRY_FIX.get(country, country)
        hit = by_reg.get(reg) or (by_exact.get(SAME_AS[reg]) if reg in SAME_AS else None) \
            or by_name.get((key(name), country))
        if hit:
            row, ds = hit
            reused.append(f"{reg} {name} -> `{row['name']}` ({ds})")
            bodies.setdefault(row["name"], row)
            body_name = row["name"]
        else:
            address = ADDRESS_FIX.get(reg) or clean(rec["address"])
            if address and country and country.lower() not in address.lower():
                address = f"{address}, {country}"
            bodies.setdefault(name, {"name": name, "country": country, "registration_no": reg,
                                     "phone": phone(rec["phone"], country), "email": EMAIL_FIX.get(reg, rec["email"]),
                                     "website": rec.get("website", ""), "address": address,
                                     "source_url": REGISTER_URL, "verified_at": ""})
            body_name = name
        cert = f"{reg} (17065)" if reg in ms_regs else reg
        proof = safe(rec["annex_urls"][0]) if rec["annex_urls"] else REGISTER_URL
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body_name,
                     "accreditation_standard": STD, "status": "ACTIVE" if rec["status"].startswith("Accr") else "SUSPENDED",
                     "issue_date": iso(rec["issued"]), "expiry_date": iso(rec["expiry"]), "proof_url": proof})

        heading, h_scheme, n = "", "", 0
        prev_heading = False
        for ln in lines.get(reg, []):
            t = clean(ln["product_text_raw"])
            if HEADING.search(t):
                heading = HEADING.sub("", t)
                h_scheme = scheme_of(heading)
                prev_heading = True
                continue
            reason = next((r for rx, r in DROPS if rx.search(t)), "")
            if reason:
                dropped[reason] += 1; dropped_bodies[reason].add(reg)
                prev_heading = prev_heading and reason == "ISO/IEC 17067 scheme type"
                continue
            if " | " not in t:
                if prev_heading:            # heading wrapped onto a second row
                    heading = f"{heading} - {t}"
                    h_scheme = h_scheme or scheme_of(heading)
                    continue
                dropped["unrecognized free text"] += 1; dropped_bodies["unrecognized free text"].add(reg)
                continue
            prev_heading = False
            family, product, reqs, remark = (clean(x) for x in (t.split(" | ") + ["", "", ""])[:4])
            scheme = h_scheme or scheme_of(reqs) or scheme_of(product)
            if EXCLUDE and (scheme in EU_CODES or (NATIONAL.search(reqs) and not KEEP_NATIONAL.search(heading + reqs))):
                dropped["EU / national scheme (--exclude)"] += 1; dropped_bodies["EU / national scheme (--exclude)"].add(reg)
                continue
            if not scheme and NATIONAL.search(heading + " " + reqs) and not KEEP_NATIONAL.search(heading + reqs):
                dropped["national scheme without catalogue entry"] += 1
                dropped_bodies["national scheme without catalogue entry"].add(reg)
                continue
            text = f"{family}: {product}" if family and family != product else product
            if remark:
                text += f" ({remark})"
            sr = refs(f"{product} {reqs}")
            n += 1
            ps.append({"certificate_number": cert, "line_no": n, "scheme": scheme,
                       "industry": "" if scheme else industry_of(product, family, heading),
                       "product_text": text, "product_text_en": "", "scheme_text": heading,
                       "normative_docs": reqs, "standard_refs": sr, "status": "ACTIVE"})
            if not scheme:
                for r in sr.split(";"):
                    if r:
                        no_scheme_refs[r] += 1

    def write(name, cols, rows):
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    write("bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda b: b["name"]))
    write("accreditations.csv", ACCREDITATION_COLUMNS, accs)
    write("scopes.csv", SCOPE_COLUMNS, [])
    write("product_scopes.csv", PS_COLUMNS, ps)

    used = sorted({p["scheme"] for p in ps if p["scheme"]})
    rv = ["# TUNAC ISO/IEC 17065 - review", "",
          f"Generated by `prepare_certifind_17065.py`{' --exclude' if EXCLUDE else ''}. Annexes are scanned; lines come "
          "from `annex_transcription.csv` (read from the scans).", "",
          "## Lines left out", "", "| Reason | Lines | Bodies |", "| --- | --- | --- |"]
    rv += [f"| {r} | {c} | {', '.join(sorted(dropped_bodies[r]))} |" for r, c in dropped.most_common()] or ["| none | 0 | |"]
    rv += ["", "## Bodies dropped", "", "None: every Cert.Produit accreditation in the register is imported.",
           "", "## Body rows reused", ""] + [f"- {r}" for r in reused] + [
           "", "## Bilingual pairing failures", "", "None: TUNAC annexes are French only (`product_text_en` empty).",
           "", "## Schemes", ""] + [f"- {c}{' (NEW, V75)' if c in NEW_SCHEMES else ''}: "
                                     f"{sum(p['scheme'] == c for p in ps)} lines" for c in used] + [
           "", "## Most frequent standard_refs on lines without a scheme", ""] + (
           [f"- {r}: {c}" for r, c in no_scheme_refs.most_common(20)] or ["None."]) + [
           "", "Lines without a scheme: " + "; ".join(f"{p['certificate_number']} `{p['product_text']}` "
                                                    f"({p['industry'] or 'no industry'})" for p in ps if not p["scheme"])]
    (HERE / "tunac_17065_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    with_scheme = sum(1 for p in ps if p["scheme"])
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\n"
          f"Product lines (with scheme): {len(ps)} ({with_scheme})\nDropped lines: {sum(dropped.values())}")


if __name__ == "__main__":
    main()
