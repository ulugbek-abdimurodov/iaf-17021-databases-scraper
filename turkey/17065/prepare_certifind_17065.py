"""TURKAK ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py [scrape out (default turkak_17065)] [dataset dir] [--exclude]
                                         [--today YYYY-MM-DD]

Input: turkak_17065_raw.json and scope_lines.csv from scrape_tr_turkak_17065.py. Each scope line is one row of
an annex table of the English certificate (cells joined by " | "). Single-cell rows are section headings
("Pressure Equipment Directive (2014/68/EU) - Additional assessment document ...", "Welding",
"Product Agriculture"): a heading's scheme is carried to the product rows below it until the next heading.
Page banners, address rows and column headers are dropped. Layout follows
../../italy/accredia-italy-17065/prepare_certifind_17065.py.
"""
import collections, csv, json, re, sys, unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent
DATA = DB.parent / "certifind" / "data"

AB_CODE = "TURKAK"
STD = "ISO/IEC 17065"
MS_DATASET = "turkak-turkey"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                         "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
COUNTRY_FIX = {"Côte d'Ivoire": "Côte d’Ivoire", "Türkiye": "Turkey", "Korea": "South Korea",
               "Czech Republic": "Czechia", "UAE": "United Arab Emirates", "Viet Nam": "Vietnam"}
CITY_COUNTRY = {"Lefkoşa": "Cyprus", "Amman": "Jordan", "Bakü": "Azerbaijan", "Taşkent": "Uzbekistan"}

EU_SCHEMES = [
    (r"305/2011|2011/305|Construction products|Yapı Malzemeleri Yönetmeliği|\b9\d/\d{2,3}/EC\b|\b(0[0-9]|1\d)/\d{2,3}/EC\b|AVCP", "Construction Products Regulation (EU) 305/2011"),
    (r"2023/1230", "Machinery Regulation (EU) 2023/1230"),
    (r"2006/42|Machinery Directive|Makine Emniyeti", "Machinery Directive 2006/42/EC"),
    (r"2014/33|\bLifts\b|Asansör", "Lifts Directive 2014/33/EU"),
    (r"2014/68|97/23|Pressure Equipment Directive|Basınçlı Ekipman", "Pressure Equipment Directive 2014/68/EU"),
    (r"2014/29|Simple Pressure Vessels", "Simple Pressure Vessels Directive 2014/29/EU"),
    (r"2014/34|Potentially Explosive Atmospheres", "ATEX Directive 2014/34/EU"),
    (r"2014/30|Electromagnetic Compatibility", "EMC Directive 2014/30/EU"),
    (r"2014/53|Radio Equipment", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/32|Measuring Instruments Directive", "Measuring Instruments Directive 2014/32/EU"),
    (r"2014/31|Non-automatic Weighing", "Non-automatic Weighing Instruments Directive 2014/31/EU"),
    (r"2009/48|Toy Safety", "Toy Safety Directive 2009/48/EC"),
    (r"2000/14|Noise emission in the environment", "Outdoor Noise Directive 2000/14/EC"),
    (r"92/42|Hot-Water Boilers", "Hot-water Boilers Directive 92/42/EEC"),
    (r"2013/53|Recreational Craft", "Recreational Craft Directive 2013/53/EU"),
    (r"2016/425|Personal Protective Equipment|Kişisel Koruyucu", "PPE Regulation (EU) 2016/425"),
    (r"2016/426|Appliances Burning Gaseous Fuels", "Gas Appliances Regulation (EU) 2016/426"),
    (r"2016/424", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2016/797", "Rail Interoperability Directive (EU) 2016/797"),
    (r"2019/779", "ECM Regulation (EU) 2019/779"),
    (r"402/2013", "CSM Risk Assessment Regulation (EU) 402/2013"),
    (r"2024/1143|1151/2012|\b(PDO|PGI|TSG)\b", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2018/848|834/2007", "EU Organic Regulation (EU) 2018/848"),
    (r"517/2014|2024/573|2015/2067|304/2008|842/2006|fluorinated", "EU F-gas Regulation"),
]
EU_CODES = {c for _, c in EU_SCHEMES}
SCHEMES = [
] + EU_SCHEMES + [
    (r"GLOBAL ?G\.?A\.?P\.?,? *Chain of Custody", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,40}Packaging", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,40}Storage and Distribution", "BRCGS Storage and Distribution"),
    (r"BRC\w*.{0,40}Agents? and Brokers", "BRCGS Agents and Brokers"),
    (r"BRC\w*.{0,40}Consumer Products", "BRCGS Consumer Products"),
    (r"BRC\w*.{0,40}Food Safety", "BRCGS Food Safety"),
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
    (r"910/2014|eIDAS|ETSI EN 319 4|Trust Service", "eIDAS"),
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
}

# (regex, reason) on whole rows
DROPS = [
    (r"^Activity \| Standard$", "column header"),
    (r"^(Product|Ürün) TS EN ISO/IEC 17065 AB-|^TS EN( I\w*)? \| (Product|Ürün) |^AB-\d{4}-U$|"
     r"^(Product Certification Body|Ürün Belgelendirme Kuruluşu)$",
     "page banner"),
    (r"^Adres(s|i)?\s*:|(Phone|Telefon)\s*:.*(Email|E-Posta)", "address / contact row"),
    (r"^(Decision|Karar|Product[ /,\w]*|Product Group|Product Family[^|]*|Scope|Product family[^|]*|Ürün[^|]*)\s*\|\s*"
     r"(Product|Body Function|Standard|Module|Annex|AVCP|Technical|Certification|National|Conformity|"
     r"Ürün|Kuruluş|Standart|Modül|Ek\b|PDDD|Teknik|Belgelendirme|Uygunluk)",
     "column header"),
    (r"^Annex of the Certificate|^Accreditation Scope$|This certificate shall remain|is accredited in accordance",
     "annex boilerplate"),
]
DROPS = [(re.compile(p, re.I), r) for p, r in DROPS]
NATIONAL = re.compile(r"\bNational Regulation\b|Official Journal|Resmi Gazete|Yönetmelik|Tebliğ", re.I)
KEEP_NATIONAL = re.compile(r"Organic Farming|Good Agricultur", re.I)
EXCLUDE = "--exclude" in sys.argv

# sector headings (single-cell rows without a scheme): give an industry to the rows below
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"organi[ck]|iyi tar|good agricultur", "agriculture"),
    (r"touris|hotel|restaurant|catering", "tourism"),
    (r"health|medical|hospital", "health"),
    (r"software|yazılım|bilişim|\bICT\b|information|cyber|digital|12207", "ict"),
    (r"cosmetic|detergent|chemical|pharma|paint|fertili[sz]er", "chemicals"),
    (r"plastic|rubber|polymer|packaging|trash can|pipe", "rubber_plastics"),
    (r"railway|rail|vehicle|automotive|aircraft|wheel", "transport_equipment"),
    (r"welding|kaynak|steel|alumin|metal", "metals"),
    (r"machine|lifting|pressure|crane|playground|carousel|sports equipment", "machinery"),
    (r"electric|electronic|photovolta|\bIEC 6\d{4}|wind energy|lamp|cable", "electrical"),
    (r"concrete|beton|yapı malzeme|construction|cement|aggregate|stone|brick|insulation|roof|glass|door|window|floor|paving",
     "construction"),
    (r"textile|clothing|footwear|leather", "textiles"),
    (r"fuel|energy|hydrogen|biogas", "energy"),
    (r"recycl|toy|furniture|jewel", "other_manufacturing"),
    (r"\bwood|paper|forest|printing", "wood_paper"),
    (r"food|feed|beverage|meat|milk|dairy|fish|halal|bread|honey|olive|gıda|hellim|zivaniya", "food"),
    (r"agricultur|plant production|crop|fruit|vegetable|livestock|animal|aquaculture|farm|tarım|bitkisel|hayvansal", "agriculture"),
    (r"logistic|transport|warehous|trade", "trade_logistics"),
    (r"services", "professional"),
]]
REF = re.compile(r"\b((?:TS|BS|DIN|NF)\s+)*(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{3,5})((?:-\d{1,3})?)")
ETSI = re.compile(r"ETSI\s+(EN|TS)\s+(\d{3})\s+(\d{3})((?:-\d+)?)")
WS = re.compile(r"\s+")
STD_CELL = re.compile(r"\b(EN|ISO|IEC|TS|EAD|Module|Annex|System \d|Regulation|Law|GLOBALG|Standard)\b", re.I)


def clean(t):
    return WS.sub(" ", (t or "").replace("<BR>", " ").replace("<br>", " ")).strip()


def key(s):
    s = (s or "").replace("İ", "I").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


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
        if "17065" not in r and "17067" not in r:
            out.append(r)
    out += [f"ETSI {m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}" for m in ETSI.finditer(t)]
    return ";".join(dict.fromkeys(out))


def industry_of(*texts):
    for t in texts:
        for rx, ind in INDUSTRY_WORDS:
            if t and rx.search(t):
                return ind
    return ""


def phone(raw):
    d = re.sub(r"\D", "", (raw or "").split("/")[0])
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    elif d.startswith("0"):
        d = "90" + d[1:]
    elif not d.startswith("90") and len(d) == 10:
        d = "90" + d
    return "+" + d


def website(w):
    w = (w or "").strip()
    return w if not w or w.startswith("http") else "https://" + w


def status_of(s):
    if s.startswith("Active"):
        return "ACTIVE"
    return "SUSPENDED" if s.startswith("Suspend") else "WITHDRAWN"


def load_bodies(out_dir):
    by_name = {}
    for f in sorted(DATA.glob("*/bodies.csv")):
        if f.parent.resolve() == out_dir.resolve():
            continue
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                by_name.setdefault((key(row["name"]), row["country"]), (row, f.parent.name))
    return by_name


TR_BODIES = set()


def classify(rows):
    """Annex table rows -> (product lines, dropped Counter)."""
    lines, dropped = [], collections.Counter()
    heading, h_scheme = "", ""
    for t in rows:
        t = clean(t)
        reason = next((r for rx, r in DROPS if rx.search(t)), "")
        if reason:
            dropped[reason] += 1
            continue
        cells = [c.strip() for c in t.split(" | ") if c.strip()]
        if len(cells) == 1:                       # section heading: sticky until the next one
            heading, h_scheme = cells[0], scheme_of(cells[0])
            continue
        if re.match(r"^\d{2}/\d{2,3}/EC$", cells[0]):   # CPR Commission decision column
            cells = cells[1:] + [cells[0]]
        docs = [c for c in cells[1:] if STD_CELL.search(c)]
        product = " | ".join(c for c in cells if c not in docs) or cells[0]
        normative = "; ".join(docs)
        scheme = scheme_of(t) if not h_scheme else h_scheme
        if h_scheme and scheme_of(t) and scheme_of(t) not in EU_CODES and h_scheme in EU_CODES:
            scheme = h_scheme                     # directive heading wins over a standard in the row
        nat = NATIONAL.search(t) and not KEEP_NATIONAL.search(t + heading)
        if EXCLUDE and (scheme in EU_CODES or scheme in NEW_SCHEMES or nat):
            dropped["EU / national scheme (--exclude)"] += 1
            continue
        lines.append({"scheme": scheme, "industry": "" if scheme else industry_of(product, heading),
                      "product_text": product, "scheme_text": heading, "normative_docs": normative,
                      "standard_refs": refs(t)})
    return lines, dropped


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    today = date.today().isoformat()
    if "--today" in sys.argv:
        today = sys.argv[sys.argv.index("--today") + 1]
        args = [a for a in args if a != today]
    src = Path(args[0]) if args else HERE / "turkak_17065"
    out = Path(args[1]) if len(args) > 1 else DATA / "turkak-turkey-17065"
    out.mkdir(parents=True, exist_ok=True)
    recs = json.loads((src / "turkak_17065_raw.json").read_text(encoding="utf-8"))
    by_reg = collections.defaultdict(list)
    with open(src / "scope_lines.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            by_reg[r["registration_no"]].append(r["product_text_raw"])
    ms_regs = set()
    with open(DATA / MS_DATASET / "accreditations.csv", encoding="utf-8") as fh:
        ms_regs = {r["certificate_number"] for r in csv.DictReader(fh)}
    by_name = load_bodies(out)

    bodies, accs, ps = {}, [], []
    dropped, dropped_bodies = collections.Counter(), collections.defaultdict(set)
    bodies_dropped, reused, no_scheme_refs = [], [], collections.Counter()
    for rec in sorted(recs, key=lambda r: r["registration_no"]):
        reg, name = rec["registration_no"], clean(rec["name"])
        st = status_of(rec["status"] or "")
        if not rec.get("issued"):
            bodies_dropped.append(f"{reg} {name}: register detail unavailable (API error), no dates or annex"); continue
        if st != "ACTIVE":
            bodies_dropped.append(f"{reg} {name}: {rec['status']}"); continue
        if rec["expiry"] and rec["expiry"] < today:
            bodies_dropped.append(f"{reg} {name}: expired {rec['expiry']}"); continue
        c0 = CITY_COUNTRY.get(rec["city"], "Turkey")
        country = COUNTRY_FIX.get(c0, c0)
        hit = by_name.get((key(name), country))
        if hit:
            row, ds = hit
            reused.append(f"{reg} -> `{row['name']}` ({ds})")
            bodies.setdefault(row["name"], row)
            body_name = row["name"]
        else:
            address = clean(rec["address"])
            bodies.setdefault(name, {"name": name, "country": country, "registration_no": "",
                                     "phone": phone(rec["phone"]), "email": rec["email"],
                                     "website": website(rec["website"]), "address": address,
                                     "source_url": rec["detail_url"], "verified_at": ""})
            body_name = name
        cert = f"{reg} (17065)" if reg in ms_regs else reg
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body_name,
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": rec["issued"],
                     "expiry_date": rec["expiry"], "proof_url": rec["detail_url"] or (rec["annex_urls"] or [""])[0]})
        lines, d = classify(by_reg.get(reg, []))
        if rec.get("annex_lang") == "tr" or any("Ürün Belgelendirme Kuruluşu" in t for t in by_reg.get(reg, [])):
            TR_BODIES.add(reg)
        for k, v in d.items():
            dropped[k] += v; dropped_bodies[k].add(reg)
        if not by_reg.get(reg):
            bodies_dropped.append(f"{reg} {name}: kept, but no certificate annex published (no product lines)")
        for n, ln in enumerate(lines, 1):
            ps.append({"certificate_number": cert, "line_no": n, **ln, "product_text_en": "", "status": "ACTIVE"})
            if not ln["scheme"]:
                no_scheme_refs.update(r for r in ln["standard_refs"].split(";") if r)

    def write(fname, cols, rows):
        with open(out / fname, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    write("bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda b: b["name"]))
    write("accreditations.csv", ACCREDITATION_COLUMNS, accs)
    write("scopes.csv", SCOPE_COLUMNS, [])
    write("product_scopes.csv", PS_COLUMNS, ps)

    sch = collections.Counter(p["scheme"] for p in ps if p["scheme"])
    ind = collections.Counter(p["industry"] or "(none)" for p in ps if not p["scheme"])
    rv = ["# TURKAK ISO/IEC 17065 - review", "",
          f"Generated by `prepare_certifind_17065.py`{' --exclude' if EXCLUDE else ''} on {today}.", "",
          "## Lines left out", "", "| Reason | Lines | Bodies |", "| --- | --- | --- |"]
    rv += [f"| {r} | {c} | {len(dropped_bodies[r])} |" for r, c in dropped.most_common()]
    rv += ["", "## Bodies dropped", ""] + [f"- {b}" for b in bodies_dropped]
    rv += ["", "## Body rows reused", ""] + ([f"- {r}" for r in reused] or ["None."])
    rv += ["", "## Bilingual pairing failures", "",
           "The English certificate annex is used, so `product_text_en` stays empty (`product_text` is already "
           "English). Bodies without an English certificate use the Turkish one, with no English half to pair: "
           + (", ".join(sorted(TR_BODIES)) or "none") + "."]
    rv += ["", "## Schemes", ""] + [f"- {c}{''}: {n}" for c, n in sch.most_common()]
    rv += ["", "## Lines without a scheme by industry", ""] + [f"- {k}: {v}" for k, v in ind.most_common()]
    rv += ["", "## Most frequent standard_refs on lines without a scheme", ""] + \
          [f"- {r}: {c}" for r, c in no_scheme_refs.most_common(25)]
    (HERE / "turkak_17065_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\n"
          f"Product lines (with scheme): {len(ps)} ({sum(sch.values())})\nDropped lines: {sum(dropped.values())}")


if __name__ == "__main__":
    main()
