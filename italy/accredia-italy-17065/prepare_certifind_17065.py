"""ACCREDIA ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py <scrape out (accredia_17065)> <dataset dir> [--today YYYY-MM-DD] [--debug REG,...]

Input: accredia_17065_raw.json (register detail per accreditation) and scope_lines.csv (verbatim annex lines)
from scrape_it_accredia_17065.py. Rules: .claude/skills/add-country-17065/SKILL.md in the certifind repo.

Annexes: CSAAR (EU directives / notified-body modules) and CSACPR (Construction Products Regulation) are left
out whole. CSAAG (agri-food) and CSACI (other voluntary schemes) are read as blocks: a heading line decides the
scheme or the reason to drop, enumerated lines below it ("-", "1.", "a)") or lines after a heading ending in ":"
are its children and carry the heading as scheme_text. Each annex is Italian then English; the English half is
paired line by line into product_text_en when both halves classify to the same number of lines.
"""
import argparse, collections, csv, json, re, sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent  # .../CertiFind/database


class _MS:  # helpers copied from ../17021 - Management systems/prepare_certifind.py (not importable: its DB path)
    pass


ms = _MS()
ms.DETAIL_URL = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG={}"
ms.BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ms.ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                            "issue_date", "expiry_date", "proof_url"]
ms.SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ms.DIAL = {"Italy": "39", "Switzerland": "41", "Bosnia and Herzegovina": "387", "Kosovo": "383", "Ukraine": "380",
           "India": "91", "Israel": "972", "Liechtenstein": "423", "Indonesia": "62"}
DIAL = ms.DIAL


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def key(s: str) -> str:
    s = " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())
    return " ".join(re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|pvt|private|the|sa|de|cv|a s|as|"
                           r"s r l|srl|s p a|spa|s c a r l|scarl|s a s|sas|s n c|snc|s c|sc|ag|unipersonale)\b",
                           " ", s).split())


def iso(d: str) -> str:
    try:
        return datetime.strptime(d.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def phone(raw: str, country: str, review: list, name: str) -> str:
    p = raw.strip()
    if not p:
        return ""
    first = p
    for sep in (r"/\s+", r"\s+-\s+"):  # "0108341/ 0108353111", "027015081 - 02747601": two numbers
        parts = re.split(sep, first)
        if len(parts) > 1 and all(len(re.sub(r"\D", "", x)) >= 7 for x in parts):
            first = parts[0]
    # "0267479254 0267479241", "0835-259593 331-8055238": second number after a space
    m = re.match(r"^(.*?\d{3,}.*?)\s+(?=\+?\d[\d\-./]{6,}$)", first)
    if m and len(re.sub(r"\D", "", m.group(1))) >= 9:
        first = m.group(1)
    digits = re.sub(r"\D", "", first)
    if first.lstrip().startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif country == "Italy":
        digits = "39" + digits
    else:
        review.append(f"{name}: phone '{raw}' has no country code; left empty")
        return ""
    cc = next((c for c in sorted(DIAL.values(), key=len, reverse=True) if digits.startswith(c)), "")
    nsn = digits[len(cc):]
    if not cc or not 6 <= len(nsn) <= 11:
        review.append(f"{name}: phone '{raw}' invalid; left empty")
        return ""
    if cc == "39":
        if not nsn.startswith(("0", "3", "8")):
            review.append(f"{name}: phone '{raw}' is not a valid Italian number; left empty")
            return ""
        return f"+39 {nsn}"  # Italian numbers keep their leading 0
    return f"+{cc} {nsn.lstrip('0')}"


ms.phone = phone


ms.DIAL.update({"Côte d’Ivoire": "225", "Poland": "48", "Morocco": "212", "Lebanon": "961", "Egypt": "20", "Turkey": "90", "Tunisia": "216",
                "Romania": "40", "Germany": "49", "Denmark": "45", "Brazil": "55", "Bulgaria": "359", "Albania": "355",
                "Thailand": "66", "Mexico": "52", "South Korea": "82", "China": "86", "Spain": "34", "France": "33",
                "Greece": "30", "Serbia": "381", "Slovenia": "386", "Croatia": "385", "Austria": "43",
                "United Kingdom": "44", "Netherlands": "31", "Portugal": "351", "Malta": "356", "San Marino": "378",
                "Vietnam": "84", "Indonesia": "62", "Pakistan": "92", "Bangladesh": "880", "Sri Lanka": "94",
                "United Arab Emirates": "971", "Saudi Arabia": "966", "Jordan": "962", "Iran": "98",
                "Argentina": "54", "Chile": "56", "Peru": "51", "Colombia": "57", "Ecuador": "593", "Kenya": "254",
                "Hungary": "36", "Czechia": "420", "Slovakia": "421", "Belgium": "32", "Ireland": "353",
                "Japan": "81", "Taiwan": "886", "Hong Kong": "852", "Singapore": "65", "Malaysia": "60",
                "Philippines": "63", "Australia": "61", "Ethiopia": "251", "Ghana": "233", "Nigeria": "234",
                "Algeria": "213", "Georgia": "995", "Armenia": "374", "Azerbaijan": "994", "Kazakhstan": "7",
                "Uzbekistan": "998", "Moldova": "373", "North Macedonia": "389", "Montenegro": "382",
                "Cyprus": "357", "Israel": "972", "Ukraine": "380", "Lithuania": "370", "Latvia": "371",
                "Estonia": "372", "Finland": "358", "Sweden": "46", "Norway": "47", "Luxembourg": "352"})

AB_CODE = "ACCREDIA"
STD = "ISO/IEC 17065"
DETAIL_URL = ms.DETAIL_URL
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
DROP_ANNEX = {"CSAAR": "EU directive / notified-body conformity assessment (CE marking modules)",
              "CSACPR": "Construction Products Regulation (EU) 305/2011 AVCP (notified body)"}
COUNTRY_FIX = {"Côte d'Ivoire": "Côte d’Ivoire", "Cote d'Ivoire": "Côte d’Ivoire", "Türkiye": "Turkey", "Korea": "South Korea", "Republic of Korea": "South Korea",
               "Czech Republic": "Czechia", "UAE": "United Arab Emirates", "Viet Nam": "Vietnam"}

# (regex, scheme code). First match wins, so specific before general. Only codes present in `schemes`
# (V66 + V67__accredia_17065_schemes.sql).
# EU directives / regulations (catalogued as EU_REGULATION in V69). A heading with one of these
# carries its scheme down to every following line until the next scheme heading ("sticky" block).
EU_SCHEMES = [
    (r"305/2011|2011/305|Prodotti da costruzione|Construction products", "Construction Products Regulation (EU) 305/2011"),
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
    (r"2024/1143|1151/2012|Categorie di prodotti coperte dagli Allegati|Product categories covered by Annex",
     "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2018/848|834/2007|Certificazione biologica|Organic certification", "EU Organic Regulation (EU) 2018/848"),
    (r"517/2014|2024/573|2015/2067|304/2008|842/2006|gas fluorurati|fluorinated", "EU F-gas Regulation"),
]
EU_CODES = {c for _, c in EU_SCHEMES}
SCHEMES = EU_SCHEMES + [
    (r"GLOBAL ?G\.?A\.?P\.?,? *(Catena di Custodia|Chain of Custody)", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,40}Packaging", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,40}(Storage and Distribution|Stoccaggio)", "BRCGS Storage and Distribution"),
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
    (r"910/2014|eIDAS|ETSI EN 319 4|Servizi Fiduciari|Trust Service", "eIDAS"),
    (r"22005", "ISO 22005"),
    (r"11352", "UNI CEI 11352"),
    (r"15085", "EN 15085-2"),
    (r"3834", "ISO 3834"),
]
SCHEMES = [(re.compile(p, re.I), c) for p, c in SCHEMES]

# (regex, reason). Checked on headings and on every line's own text.
DROPS = [
    (r"2024/1143|1151/2012|\b(DOP|IGP|STG|DOCG|IGT|PDO|PGI|TSG)\b|\bDOC\b",
     "DOP/IGP/STG control (Reg. (EU) 2024/1143), designated by the national authority"),
    (r"2018/848|834/2007|Certificazione biologica|Organic certification",
     "organic control (Reg. (EU) 2018/848), designated by the national authority"),
    (r"517/2014|2024/573|2015/2067|304/2008|842/2006|gas fluorurati|fluorinated",
     "F-gas certification (EU F-gas regulations via DPR 146/2018), national designation"),
    (r"305/2011|2011/305|^[-\s]*(Direttiva|Directive) |2006/42|2023/1230|2016/42[56]|2019/779|402/2013",
     "EU directive / regulation conformity assessment (notified or assessment body)"),
    (r"UNI/PdR|\bPdR \d|SQNPI|Produzione Integrata|Integrated Production|Benessere Animale|Animal Welfare|"
     r"Sistema di Qualit. Nazionale|National Quality System|Sistema nazionale di certificazione della sostenib|"
     r"National (sustainability )?certification system|ANSFISA|REMADE|Plastica Seconda Vita|Made in Italy|"
     r"\bSPID\b|tecniche nazionali danesi|Danish national|vigilanza|security institutes|balneari|bathing|UNI 11926|UNI 10891|Decreto|Decree|D\.\s?Lgs|"
     r"D\.\s?M\.|D\.?P\.?R\b|Legge |Ministero|Ministry",
     "Italian national scheme"),
]
DROPS = [(re.compile(p, re.I), r) for p, r in DROPS]
NATIONAL = DROPS[-1][0]
EXCLUDE = False  # --exclude: old rules (drop notified-body, DOP, organic, F-gas and national lines)
BOILER = re.compile(r"^(Certificazione di prodotti (nei|nell.ambito dei) seguenti|Certification of products (in the scope|within the scope)|Certification of products (within|in) the following|"
                    r"La validit. degli allegati|The validity of the annexes|Moduli? / Procedur|Prodotti:?$|Products:?$|"
                    r"(Specifiche Tecniche Private|Private Technical Specifications):?$|Modulo? / Procedura di Valutazione|"
                    r"Modules? / Conformity Assessment)", re.I)
GLUED = re.compile(r"(Categorie di prodotti coperte dagli Allegati|Product categories covered by Annex)", re.I)
EN_HEADER = re.compile(r"^Certification of products", re.I)
# sector headings: not imported, reset the block and give an industry to scheme-less lines below
SECTORS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"^(Prodotti agricoli|Prodotti alimentari|Agricultural products|Food products|Agro-food)", "food"),
    (r"^(Imballaggi|Packaging and packaging materials)", "packaging"),
    (r"^(Prodotti di consumo|Consumer products in)", "chemicals"),
    (r"^(Trasporti e logistica|Transport and logistics)", "transport"),
]]
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"cosmetic|detergent|chimic|chemical", "chemicals"),
    (r"ferroviar|railway|rolling stock|\bEN 5012[689]\b|\bEN 15085", "transport"),
    (r"saldatura|welding|brasatura|brazing|\bISO 3834|\bISO 15614|\bISO 9606", "machinery"),
    (r"\bmacchin|\bmachine|trattori|tractor|motozappatric|tiller|\bISO 4254|\bISO 11684|\bISO 5395|\bISO 1168[01]|"
     r"sollevamento|lifting|pressione|pressure", "machinery"),
    (r"cyber|informatic|software|\bICT\b|dati personali|privacy|IEC 62443|IEC 27\d\d\d|\bOT\b", "ict"),
    (r"elettric|electric|elettronic|electronic|fotovolta|photovolta|\bIEC 6\d{4}|trasformator|transformer|"
     r"switchgear|quadri|cavi\b|cables?\b|lampad|luminair", "electrical"),
    (r"calcestruzz|concrete|edil|costruzion|construction|cemento|cement|laterizi|ghisa|cast iron|tubi|pipes?\b|"
     r"acque destinate al consumo umano|drinking water|serramenti|windows", "construction"),
    (r"tessil|textile|abbigliament|clothing|calzatur|footwear|pelle\b|leather|concia|tanning", "textiles"),
    (r"biocarbur|biocombust|biofuel|biometano|biogas|energia|energy|rottami|scrap|end-of-waste|cessano di essere", "energy"),
    (r"legno|\bwood|\bcarta\b|paper|forest", "forestry"),
    (r"imballag|packaging", "packaging"),
    (r"alimentar|\bfood|mangim|\bfeed|\bvino\b|\bwine|\bcarne|\bmeat|\blatte\b|dairy|ittic|\bfish|seafood|pesce", "food"),
    (r"agricol|agricultur|acquacoltura|aquaculture|zootecn|livestock", "agriculture"),
    (r"servizi|services|formazione|training|centri di contatto|contact cent|turism|touris|sanitari|health|"
     r"finanziari|financial|breast", "services"),
]]
CHILD = re.compile(r"^([-–•·]|\d{1,2}(\.\d{1,2})*[.)]?\s|[a-zA-Z]\)\s|[ivx]+\)\s)")
REF = re.compile(r"\b((?:UNI|CEI|BS|DIN|NF)\s+)*(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{3,5})((?:-\d{1,3})?)")
ETSI = re.compile(r"ETSI\s+(EN|TS)\s+(\d{3})\s+(\d{3})((?:-\d+)?)")
WS = re.compile(r"\s+")


def clean(t: str) -> str:
    return WS.sub(" ", (t or "").replace("\xa0", " ")).strip()


def scheme_of(t: str):
    eu = next((c for rx, c in SCHEMES[:len(EU_SCHEMES)] if rx.search(t)), None)
    if eu:  # EU regulations often cite the Italian implementing decree; the EU scheme wins
        return eu
    if NATIONAL.search(t) and not KEEP_NATIONAL.search(t):  # Italian national scheme: no catalogue scheme
        return None
    return next((c for rx, c in SCHEMES if rx.search(t)), None)


# Italian schemes kept on request: searchable although they cite national decrees.
KEEP_NATIONAL = re.compile(r"11352", re.I)


def drop_of(t: str):
    if not EXCLUDE:
        return None
    if KEEP_NATIONAL.search(t) and not re.search(r"PdR|gas fluorurati|fluorinated", t, re.I):
        return None
    return next((r for rx, r in DROPS if rx.search(t)), None)


def refs(t: str) -> str:
    out = []
    for m in ETSI.finditer(t):
        out.append(f"ETSI {m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}")
    t2 = ETSI.sub(" ", t)
    for m in REF.finditer(t2):
        body = m.group(3)
        if body == "EN" or (body == "CEN/TS"):
            r = f"{body} {m.group(4)}{m.group(5)}"
        else:
            r = f"{body} {m.group(4)}{m.group(5)}"
        if r not in out:
            out.append(r)
    return ";".join(out)


# ------------------------------------------------------------------ bodies
def sites(head: str) -> tuple[str, list[list[str]]]:
    t = head[head.rfind("Organismi accreditati"):]
    lines = [clean(l) for l in t.split("\n") if clean(l)]
    name = clean(" ".join(lines[1:lines.index("Organismo Accreditato")]))
    web = ""
    if "Sito Web:" in lines:
        i = lines.index("Sito Web:")
        web = lines[i + 1] if lines[i + 1] != "Sedi Accreditate" else ""
    body = lines[lines.index("Sedi Accreditate") + 1:]
    out, cur = [], []
    for l in body:
        if l == "Accreditamenti":
            break
        cur.append(l)
        if l == "Schema:":
            continue
        if len(cur) >= 2 and cur[-2] == "Schema:":
            out.append(cur)
            cur = []
    return name, web, out


def norm_tel(tel: str, country: str) -> str:
    """Pre-clean before ms.phone: '(+39) 049..' / '(86) 21..' -> '+39 049..'; first of several numbers;
    country code without '+'; national trunk 0 abroad."""
    t = re.split(r"\s*[;]\s*|-(?=0\d)", tel.strip())[0]
    t = re.sub(r"^\(\+?(\d{1,3})\)\s*", r"+\1 ", t)
    cc = ms.DIAL.get(country)
    digits = re.sub(r"\D", "", t)
    if cc and not t.startswith("+") and country != "Italy":
        if digits.startswith(cc) and len(digits) - len(cc) >= 7:
            t = "+" + digits
        elif re.match(r"^0[1-9]", digits):
            t = f"+{cc} {digits[1:]}"
    return t


def parse_body(rec, review):
    name, web, ss = sites(rec["text_head"])
    main = next((s for s in ss if any(l.startswith(("Tel:", "Email:")) for l in s)), ss[0] if ss else [])
    addr, tel, email = [], "", ""
    for i, l in enumerate(main):
        if l.startswith("Tel:"):
            tel = l[4:].strip()
        elif l.startswith(("Fax:", "Schema:")) or (i and main[i - 1] == "Schema:"):
            pass
        elif l == "Email:":
            email = main[i + 1] if i + 1 < len(main) else ""
        elif i and main[i - 1] == "Email:":
            pass
        else:
            addr.append(l)
    country = ""
    if addr:
        last = addr[-1]
        m = re.search(r"(?:^|\s)([A-Z][A-Za-z' .-]+)$", last)
        if " " in last and last.split(" ")[-1] == "Italy":
            country, addr[-1] = "Italy", last[:-len("Italy")].strip()
        else:
            country = last
            addr = addr[:-1]
    country = COUNTRY_FIX.get(country, country)
    names = KNOWN_COUNTRIES | set(ms.DIAL)
    known = next((c for c in sorted(names, key=len, reverse=True) if country.endswith(" " + c)), None)
    if known and country not in names:  # "Thessaly Greece": region before the country
        addr.append(country[: -len(known)].strip())
        country = known
    a = ", ".join(x.rstrip(" -") for x in addr if x.strip(" -"))
    a = re.sub(r", \((\w\w)\)", r" (\1)", a)
    w = re.sub(r"\s+", "", web)
    w = re.sub(r"^(https?)/*:/*", r"\1://", w)  # "https//:x", "http:/x"
    if w and not re.fullmatch(r"(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?", w, re.I):
        review.append(f"{name}: website '{web}' invalid; left empty")
        w = ""
    return {"name": name, "country": country, "registration_no": rec["registration_no"],
            "phone": ms.phone(norm_tel(tel, country), country, review, name) if tel else "",
            "email": re.split(r"[;,\s]+", email.strip())[0] if email else "",
            "website": ("https://" + w if w and not w.startswith("http") else w), "address": a,
            "source_url": DETAIL_URL.format(rec["id"]), "verified_at": ""}


KNOWN_COUNTRIES: set[str] = set()


def load_bodies(data_root: Path, out: Path):
    by_name, by_reg, certs = {}, {}, set()
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent.resolve() == out.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig", newline="")):
            by_name.setdefault((key(r["name"]), r["country"]), (f.parent.name, r))
            KNOWN_COUNTRIES.add(r["country"])
            if f.parent.name == "accredia-italy":
                by_reg[r["registration_no"]] = (f.parent.name, r)
        acc = f.parent / "accreditations.csv"
        for r in csv.DictReader(open(acc, encoding="utf-8-sig", newline="")):
            if r["ab_code"] == AB_CODE:
                certs.add(r["certificate_number"])
    return by_name, by_reg, certs


# ------------------------------------------------------------------ lines
AUDIT = collections.defaultdict(list)  # reason -> [(reg, text)] for the review file


class Scratch(collections.defaultdict):
    """Drop counter for the English half: counted once, on the Italian half."""


def drop(dropped, reason, reg, text):
    dropped[reason].append(reg)
    if not isinstance(dropped, Scratch):
        AUDIT[reason].append((reg, text))


def classify(rows, dropped, reg):
    """rows of one language half -> list of out-lines (dicts) in order; dropped lines counted by reason."""
    out = []
    block = {"scheme": None, "drop": None, "head": "", "industry": None, "colon": False, "children": 0, "head_line": None}

    def close():
        # a heading with no children is imported as a line of its own
        hl = block["head_line"]
        if hl is not None and block["children"] == 0 and (len(hl["product_text"]) >= 15 or hl["standard_refs"]):
            out.append(hl)

    split = []
    for r in rows:  # the scraper sometimes glues the next heading onto a line
        t = r["product_text_raw"]
        m = GLUED.search(t)
        if m and m.start() > 0 and not (r["scheme_text_raw"] or r["normative_docs_raw"]):
            split += [dict(r, product_text_raw=t[:m.start()]), dict(r, product_text_raw=t[m.start():])]
        else:
            split.append(r)
    for r in split:
        prod = clean(r["product_text_raw"])
        sch_t = clean(r["scheme_text_raw"])
        norm = clean(r["normative_docs_raw"])
        own = " ".join([prod, sch_t, norm])
        if not own.strip():
            continue
        is_row = bool(sch_t or norm)
        if not prod and norm and not sch_t:  # continuation row of normative docs
            if drop_of(norm) or not out:
                drop(dropped, drop_of(norm) or "orphan continuation row", reg, own)
                continue
            out[-1]["normative_docs"] = (out[-1]["normative_docs"] + " " + norm).strip()
            out[-1]["standard_refs"] = refs(out[-1]["normative_docs"] + " " + out[-1]["product_text"])
            continue
        if BOILER.search(prod) or re.fullmatch(r"[\d\s/.,:-]*", prod) and not is_row:
            drop(dropped, "annex boilerplate", reg, own)
            continue
        sec = next((ind for rx, ind in SECTORS if rx.search(prod)), None)
        if sec and not is_row:
            close()
            block = {"scheme": None, "drop": None, "head": "", "industry": sec, "colon": False, "children": 0,
                     "head_line": None, "sector": sec}
            drop(dropped, "sector heading (kept as industry)", reg, own)
            continue
        own_drop, own_scheme = drop_of(own), scheme_of(own)
        sticky = block["scheme"] in EU_CODES
        child = (CHILD.match(prod) is not None or block["colon"] or sticky) and not is_row and block["head"] != ""
        if child and not own_scheme and not (own_drop and not block["drop"] and own_drop != "Italian national scheme"):
            # inherits the heading
            block["children"] += 1
            if block["drop"]:
                drop(dropped, block["drop"], reg, "(under) " + block["head"])
                continue
            if own_drop:
                drop(dropped, own_drop, reg, own)
                continue
            sc = None if NATIONAL.search(own) and not KEEP_NATIONAL.search(own) else block["scheme"]
            out.append(line(prod, block["head"], norm, sc,
                             industry_of(own) or industry_of(block["head"]) or block["industry"]))
            if block["head_line"] is not None:
                block["head_line"] = None if block["children"] else block["head_line"]
            continue
        if is_row:
            # table rows are self-contained
            if own_drop:
                drop(dropped, own_drop or block["drop"], reg, own)
                continue
            sc = own_scheme or (None if NATIONAL.search(own) and not KEEP_NATIONAL.search(own) else block["scheme"])
            out.append(line(prod, sch_t or block["head"], norm, sc, None if sc else (industry_of(own) or block["industry"])))
            block["children"] += 1
            continue
        # a new heading
        close()
        sector = block.get("sector")
        if own_drop and not own_scheme:
            block = {"scheme": None, "drop": own_drop, "head": prod, "industry": None, "colon": prod.endswith(":"),
                     "children": 0, "head_line": None, "sector": sector}
            drop(dropped, own_drop, reg, own)
            continue
        ind = None if own_scheme else (industry_of(own) or sector)
        hl = line(prod, "", "", own_scheme, ind)
        block = {"scheme": own_scheme, "drop": None, "head": prod, "industry": ind, "colon": prod.endswith(":"),
                 "children": 0, "head_line": hl, "sector": sector}
    close()
    return out


def industry_of(t):
    return next((ind for rx, ind in INDUSTRY_WORDS if rx.search(t)), None)


def line(prod, sch_t, norm, scheme, industry):
    return {"scheme": scheme or "", "industry": "" if scheme else (industry or ""), "product_text": prod,
            "product_text_en": "", "scheme_text": sch_t, "normative_docs": norm,
            "standard_refs": refs(" ".join([prod, sch_t, norm])), "status": "ACTIVE"}


def halves(rows):
    """Split an annex into (italian, english) segments at each 'Certification of products' header."""
    segs, cur, lang = [], [], "it"
    for r in rows:
        p = clean(r["product_text_raw"])
        if EN_HEADER.search(p):
            if cur:
                segs.append((lang, cur))
            cur, lang = [], "en"
        elif lang == "en" and re.match(r"^Certificazione di prodotti nei seguenti", p):
            segs.append((lang, cur))
            cur, lang = [], "it"
        cur.append(r)
    if cur:
        segs.append((lang, cur))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", default="")
    ap.add_argument("--exclude", action="store_true",
                    help="drop notified-body, DOP/IGP, organic, F-gas and national lines (rules before 2026-11-13)")
    args = ap.parse_args()
    global EXCLUDE
    EXCLUDE = args.exclude
    args.out.mkdir(parents=True, exist_ok=True)
    debug = set(filter(None, args.debug.split(",")))
    by_name, by_reg, ab_certs = load_bodies(args.out.parent, args.out)
    raw = json.loads((args.scrape / "accredia_17065_raw.json").read_text(encoding="utf-8"))
    lines_by_reg = collections.defaultdict(list)
    for r in csv.DictReader(open(args.scrape / "scope_lines.csv", encoding="utf-8", newline="")):
        lines_by_reg[r["registration_no"]].append(r)

    review, reused, unpaired, no_lines = [], [], [], []
    dropped = collections.defaultdict(list)
    bodies, accs, ps = {}, [], []
    for rec in raw:
        reg = rec["registration_no"]
        parsed = parse_body(rec, review)
        if reg in by_reg:
            ds, row = by_reg[reg]
            body = dict(row)
            reused.append(f"{body['name']} ({reg}) from {ds} (same registration number)")
        elif (key(parsed["name"]), parsed["country"]) in by_name and not (
                # another ACCREDIA registration with a similar name is a different company
                # (CERTIFICA S.r.l. 01502 Bacoli vs CERTIFICA.SRL S.r.l. 02061 Gorizia)
                re.fullmatch(r"\d{5}", by_name[(key(parsed["name"]), parsed["country"])][1]["registration_no"])
                and by_name[(key(parsed["name"]), parsed["country"])][1]["registration_no"] != reg):
            ds, row = by_name[(key(parsed["name"]), parsed["country"])]
            body = dict(row)
            reused.append(f"{parsed['name']} ({reg}) -> '{row['name']}' from {ds}")
        else:
            body = parsed
            if not body["country"]:
                review.append(f"{body['name']} ({reg}): no country found in the register address")

        # scope lines, per annex in stable order (annex type, file name, row)
        out_lines = []
        by_src = collections.defaultdict(list)
        for r in lines_by_reg.get(reg, []):
            by_src[r["source"]].append(r)
        for src in sorted(by_src, key=lambda s: (s.split("_ALL_")[1], s)):
            kind = src.split("_ALL_")[1]
            src_rows = sorted(by_src[src], key=lambda r: int(r["row_index"]))
            if EXCLUDE and kind in DROP_ANNEX:
                dropped[DROP_ANNEX[kind]].extend([reg] * len(src_rows))
                continue
            segs = halves(src_rows)
            i = 0
            while i < len(segs):
                lang, seg = segs[i]
                it = classify(seg, dropped, reg)
                if lang == "it" and i + 1 < len(segs) and segs[i + 1][0] == "en":
                    en = classify(segs[i + 1][1], Scratch(list), reg)
                    if len(en) == len(it):
                        for x, y in zip(it, en):
                            if y["product_text"] != x["product_text"]:
                                x["product_text_en"] = y["product_text"]
                    else:
                        unpaired.append(f"{reg} {src}: {len(it)} Italian vs {len(en)} English lines; English not used")
                    i += 2
                else:
                    if lang == "en":
                        unpaired.append(f"{reg} {src}: English text without an Italian half; imported as product_text")
                    i += 1
                out_lines += it
        if reg in debug:
            for l in out_lines:
                print(reg, l)
        if not out_lines:
            no_lines.append(f"{body['name']} ({reg}): no importable line; dropped")
            continue
        if body["name"] in bodies and bodies[body["name"]] != body:
            raise SystemExit(f"duplicate body name with different rows: {body['name']}")
        if body["name"] in bodies:
            review.append(f"{body['name']}: second 17065 accreditation {reg}; lines merged into the first")
            cert = next(a["certificate_number"] for a in accs if a["body_name"] == body["name"])
        else:
            bodies[body["name"]] = body
            cert = f"{reg} (17065)" if reg in ab_certs else reg
            accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                         "accreditation_standard": STD, "status": "ACTIVE", "issue_date": iso(rec["issued"]),
                         "expiry_date": "", "proof_url": DETAIL_URL.format(rec["id"])})
        start = sum(1 for p in ps if p["certificate_number"] == cert)
        for n, l in enumerate(out_lines, start + 1):
            ps.append({"certificate_number": cert, "line_no": n, **l})

    write(args.out / "bodies.csv", ms.BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ms.ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", ms.SCOPE_COLUMNS, [])
    write(args.out / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    unmatched = collections.Counter(r for p in ps if not p["scheme"] for r in p["standard_refs"].split(";") if r)
    with open(HERE / "accredia_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# ACCREDIA ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, "
                 f"{len(accs)} accreditations, {len(ps)} product lines ({with_scheme} with a scheme).\n\n")
        fh.write("## Lines left out (reason: lines, bodies)\n\n")
        for reason, regs in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            fh.write(f"- {reason}: {len(regs)} lines, {len(set(regs))} bodies\n")
        fh.write("\n## Bodies dropped\n\n")
        fh.writelines(f"- {l}\n" for l in no_lines)
        fh.write("\n## Body rows reused from other datasets\n\n")
        fh.writelines(f"- {l}\n" for l in reused)
        fh.write("\n## Notes\n\n")
        fh.writelines(f"- {l}\n" for l in review)
        fh.write("\n## Bilingual pairing failures\n\n")
        fh.writelines(f"- {l}\n" for l in unpaired)
        fh.write("\n## Dropped text in CSAAG/CSACI annexes (reason / text: bodies)\n")
        for reason, items in sorted(AUDIT.items()):
            if reason == "annex boilerplate":
                continue
            fh.write(f"\n### {reason}\n\n")
            c = collections.defaultdict(set)
            for reg, t in items:
                c[t[:140]].add(reg)
            for t, regs in sorted(c.items(), key=lambda kv: -len(kv[1])):
                fh.write(f"- {t}: {', '.join(sorted(regs))}\n")
        fh.write("\n## Most frequent standard_refs on lines without a scheme\n\n")
        fh.writelines(f"- {r}: {n}\n" for r, n in unmatched.most_common(40))
    print(f"bodies {len(bodies)}, accreditations {len(accs)}, product lines {len(ps)} ({with_scheme} with scheme), "
          f"dropped bodies {len(no_lines)}; review: {HERE / 'accredia_17065_review.md'}")


if __name__ == "__main__":
    main()
