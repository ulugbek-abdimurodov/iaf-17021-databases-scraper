"""Shared converter for ISO/IEC 17065 scrapes -> CertiFind dataset (certifind/data/<ab>-<country>-17065/).

Follows certifind/.claude/skills/add-country-17065/SKILL.md. Each country keeps a small
prepare_certifind_17065.py that reads its own scrape into `Body` records with scope `lines`, then calls
`Dataset.write()`. This module owns everything that must be the same for every AB:

- the scheme regex table (only codes present in the `schemes` table are ever written),
- the industry table (V70 codes), standard-reference extraction, boilerplate filtering,
- phone normalisation to international format,
- body-row reuse from every other dataset (rows copied character for character),
- certificate-number suffix " (17065)" when the number is already used by the AB's MS dataset,
- writing bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv, SOURCES.md and the
  review file.
"""
from __future__ import annotations

import csv
import re
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DB_ROOT = Path(__file__).resolve().parent
DATA = DB_ROOT.parent / "certifind" / "data"
STANDARD = "ISO/IEC 17065"

BODY_COLS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
            "expiry_date", "proof_url"]
SCOPE_COLS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en", "scheme_text",
           "normative_docs", "standard_refs", "status"]

# ------------------------------------------------------------------ countries and phones
COUNTRY_FIX = {
    "sverige": "Sweden", "norge": "Norway", "suomi": "Finland", "danmark": "Denmark", "nederland": "Netherlands",
    "the netherlands": "Netherlands", "polska": "Poland", "česká republika": "Czechia", "czech republic": "Czechia",
    "slovenská republika": "Slovakia", "slovensko": "Slovakia", "magyarország": "Hungary", "eesti": "Estonia",
    "deutschland": "Germany", "ísland": "Iceland", "island": "Iceland", "iceland": "Iceland", "österreich": "Austria", "schweiz": "Switzerland", "suisse": "Switzerland",
    "italia": "Italy", "españa": "Spain", "espana": "Spain", "france": "France", "portugal": "Portugal",
    "türkiye": "Turkey", "turkiye": "Turkey", "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom", "usa": "United States", "us": "United States",
    "united states of america": "United States", "korea": "South Korea", "republic of korea": "South Korea",
    "uae": "United Arab Emirates", "viet nam": "Vietnam", "україна": "Ukraine", "românia": "Romania",
    "republic of north macedonia": "North Macedonia", "macedonia": "North Macedonia", "ksa": "Saudi Arabia",
    "kingdom of saudi arabia": "Saudi Arabia", "es": "Spain", "it": "Italy", "de": "Germany", "fr": "France",
    "gb": "United Kingdom", "cn": "China", "in": "India", "tr": "Turkey", "pt": "Portugal", "pl": "Poland",
    "nl": "Netherlands", "be": "Belgium", "ch": "Switzerland", "at": "Austria", "se": "Sweden", "dk": "Denmark",
    "no": "Norway", "fi": "Finland", "gr": "Greece", "ro": "Romania", "hu": "Hungary", "cz": "Czechia",
    "sk": "Slovakia", "jp": "Japan", "kr": "South Korea", "tw": "Taiwan", "sg": "Singapore", "my": "Malaysia",
    "th": "Thailand", "id": "Indonesia", "vn": "Vietnam", "ae": "United Arab Emirates", "sa": "Saudi Arabia",
    "eg": "Egypt", "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka", "br": "Brazil", "mx": "Mexico",
    "ca": "Canada", "au": "Australia", "nz": "New Zealand", "za": "South Africa", "ie": "Ireland", "il": "Israel",
    "qa": "Qatar", "sm": "San Marino", "korea, south": "South Korea", "south korea": "South Korea",
    "hk": "Hong Kong", "ph": "Philippines", "co": "Colombia", "ar": "Argentina", "cl": "Chile", "pe": "Peru",
}
DIAL = {"Albania": "355", "Algeria": "213", "Argentina": "54", "Armenia": "374", "Australia": "61", "Austria": "43",
        "Azerbaijan": "994", "Bangladesh": "880", "Belgium": "32", "Brazil": "55", "Bulgaria": "359", "Canada": "1",
        "Chile": "56", "China": "86", "Colombia": "57", "Croatia": "385", "Cyprus": "357", "Czechia": "420",
        "Denmark": "45", "Ecuador": "593", "Egypt": "20", "Estonia": "372", "Ethiopia": "251", "Finland": "358",
        "France": "33", "Georgia": "995", "Germany": "49", "Ghana": "233", "Greece": "30", "Hong Kong": "852",
        "Hungary": "36", "Iceland": "354", "India": "91", "Indonesia": "62", "Iran": "98", "Ireland": "353",
        "Israel": "972", "Italy": "39", "Japan": "81", "Jordan": "962", "Kazakhstan": "7", "Kenya": "254",
        "Latvia": "371", "Lebanon": "961", "Lithuania": "370", "Luxembourg": "352", "Malaysia": "60", "Malta": "356",
        "Mexico": "52", "Costa Rica": "506", "Honduras": "504", "Moldova": "373", "Mongolia": "976", "Montenegro": "382", "Morocco": "212", "Nepal": "977",
        "Netherlands": "31", "New Zealand": "64", "Nigeria": "234", "North Macedonia": "389", "Norway": "47",
        "Oman": "968", "Pakistan": "92", "Peru": "51", "Philippines": "63", "Poland": "48", "Portugal": "351",
        "Qatar": "974", "Romania": "40", "Russia": "7", "Saudi Arabia": "966", "Serbia": "381", "Singapore": "65",
        "Slovakia": "421", "Slovenia": "386", "South Africa": "27", "South Korea": "82", "Spain": "34",
        "Sri Lanka": "94", "Sweden": "46", "Switzerland": "41", "Taiwan": "886", "Thailand": "66", "Tunisia": "216",
        "Turkey": "90", "Ukraine": "380", "United Arab Emirates": "971", "United Kingdom": "44",
        "United States": "1", "Uruguay": "598", "Uzbekistan": "998", "Vietnam": "84", "Bahrain": "973",
        "Kuwait": "965", "Bosnia and Herzegovina": "387", "Belarus": "375", "Iceland": "354"}
TRUNK_ZERO_KEPT = {"39"}  # Italy keeps the leading 0


def country_name(raw: str, default: str = "") -> str:
    t = clean(raw)
    if not t:
        return default
    fixed = COUNTRY_FIX.get(t.casefold())
    if fixed:
        return fixed
    if t in DIAL:
        return t
    for name in DIAL:  # "…, Denmark" / "Republic of Turkey" style strings
        if re.search(rf"\b{re.escape(name)}\b", t, re.I):
            return name
    return default or t


def phone(raw: str, country: str, notes: list, who: str) -> str:
    """International format '+47 22 96 03 30' (spaces kept as given after the country code), or ''."""
    p = clean(raw)
    if not p:
        return ""
    p = re.split(r"\s*(?:[,;/]|\bor\b|\by\b|\bfax\b|\bmob\w*\b)\s*(?=\+?\(?\d)", p, flags=re.I)[0]
    p = re.split(r"(?<=\d)\s+(?=\+\s*\d)", p)[0]  # two numbers separated only by a space
    p = re.sub(r"\((?:0)\)", "", p)  # +31 (0)88 -> +31 88
    p = re.sub(r"(?i)^(tel\.?|phone|telefon|t\.?)\s*:?\s*", "", p)
    p = re.sub(r"\s*(#|ext\.?|x)\s*\d+$", "", p, flags=re.I)
    cc_country = DIAL.get(country, "")
    if p.startswith("+"):
        digits = re.sub(r"\D", "", p)
    elif p.startswith("00"):
        digits = re.sub(r"\D", "", p)[2:]
    elif cc_country:
        nat = re.sub(r"\D", "", p)
        digits = cc_country + (nat if cc_country in TRUNK_ZERO_KEPT else nat.lstrip("0"))
    else:
        notes.append(f"{who}: phone '{raw}' has no country code and no known country; left empty")
        return ""
    cc = next((c for c in sorted(set(DIAL.values()), key=len, reverse=True) if digits.startswith(c)), "")
    nsn = digits[len(cc):]
    if not cc or not 5 <= len(nsn) <= 12:
        notes.append(f"{who}: phone '{raw}' not a valid number; left empty")
        return ""
    if cc not in TRUNK_ZERO_KEPT:
        nsn = nsn.lstrip("0")
    # keep grouping from the source when it was international, else group in blocks
    if p.startswith("+"):
        rest = re.sub(r"^\+\s*" + cc + r"\s*", "", p)
        rest = re.sub(r"[^\d ]", " ", rest)
        rest = re.sub(r"\s+", " ", rest).strip()
        if cc not in TRUNK_ZERO_KEPT:
            rest = rest.lstrip("0").strip()
        if re.sub(r"\D", "", rest) == nsn:
            return f"+{cc} {rest}"
    return f"+{cc} {nsn}"


def url(raw: str) -> str:
    """Percent-encode spaces and other unsafe characters; the importer rejects them."""
    from urllib.parse import quote
    return quote(clean(raw), safe=":/?=&%#,+@;~!$'()*[]")


def website(raw: str) -> str:
    w = clean(raw)
    if not w or "@" in w:
        return ""
    w = w.split()[0].rstrip("/.,;")
    if not re.match(r"https?://", w, re.I):
        w = "https://" + w
    return w if re.match(r"https?://[\w.-]+\.[a-z]{2,}", w, re.I) else ""


def email(raw: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw or "")
    return m.group(0) if m else ""


# ------------------------------------------------------------------ text helpers
WS = re.compile(r"\s+")


def clean(t) -> str:
    return WS.sub(" ", str(t or "").replace("\xa0", " ").replace("​", "")).strip()


def key(s: str) -> str:
    s = unicodedata.normalize("NFKD", clean(s)).encode("ascii", "ignore").decode().casefold()
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]", "", s)


def iso_date(raw: str) -> str:
    t = clean(raw)
    if not t:
        return ""
    for rx, order in [(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "ymd"), (r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", "dmy")]:
        m = re.search(rx, t)
        if m:
            a, b, c = m.groups()
            y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
            try:
                return date(int(y), int(mo), int(d)).isoformat()
            except ValueError:
                return ""
    months = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                          "nov", "dec"], 1)}
    m = re.search(r"(\d{1,2})\s*([A-Za-z]{3})[a-z]*\.?,?\s*(\d{4})", t) or None
    if m:
        try:
            return date(int(m.group(3)), months[m.group(2)[:3].lower()], int(m.group(1))).isoformat()
        except (KeyError, ValueError):
            return ""
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2}),?\s*(\d{4})", t)
    if m:
        try:
            return date(int(m.group(3)), months[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
        except (KeyError, ValueError):
            return ""
    return ""


# ------------------------------------------------------------------ schemes, industries, references
EU_SCHEMES = [
    (r"305/2011|2011/305|construction products? regulation|\bCPR\b", "Construction Products Regulation (EU) 305/2011"),
    (r"2023/1230", "Machinery Regulation (EU) 2023/1230"),
    (r"2006/42", "Machinery Directive 2006/42/EC"),
    (r"2014/33|95/16", "Lifts Directive 2014/33/EU"),
    (r"2014/68|97/23", "Pressure Equipment Directive 2014/68/EU"),
    (r"2014/29|2009/105", "Simple Pressure Vessels Directive 2014/29/EU"),
    (r"2014/34|94/9/E", "ATEX Directive 2014/34/EU"),
    (r"2014/30|2004/108", "EMC Directive 2014/30/EU"),
    (r"2014/53|1999/5/E", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/32|2004/22", "Measuring Instruments Directive 2014/32/EU"),
    (r"2014/31|2009/23", "Non-automatic Weighing Instruments Directive 2014/31/EU"),
    (r"2009/48", "Toy Safety Directive 2009/48/EC"),
    (r"2000/14", "Outdoor Noise Directive 2000/14/EC"),
    (r"92/42", "Hot-water Boilers Directive 92/42/EEC"),
    (r"2016/425|89/686", "PPE Regulation (EU) 2016/425"),
    (r"2016/426|2009/142", "Gas Appliances Regulation (EU) 2016/426"),
    (r"2016/424|2000/9/E", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2016/797|2008/57", "Rail Interoperability Directive (EU) 2016/797"),
    (r"2013/53|94/25", "Recreational Craft Directive 2013/53/EU"),
    (r"2014/90|96/98", "Marine Equipment Directive 2014/90/EU"),
    (r"2019/779|445/2011", "ECM Regulation (EU) 2019/779"),
    (r"402/2013", "CSM Risk Assessment Regulation (EU) 402/2013"),
    (r"2024/1143|1151/2012|\bPDO\b|\bPGI\b|\bTSG\b|geographical indication", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2018/848|834/2007|889/2008", "EU Organic Regulation (EU) 2018/848"),
    (r"517/2014|2024/573|2015/2067|2015/2066|304/2008|842/2006|303/2008|F-gas|fluorinated", "EU F-gas Regulation"),
    (r"910/2014|eIDAS|ETSI EN 319 4", "eIDAS"),
]
PRIVATE_SCHEMES = [
    (r"GLOBAL ?G\.?A\.?P\.?,? *(Chain of Custody|CoC)", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"PRIMUS ?GFS", "PrimusGFS"),
    (r"Best +Aquaculture +Practices|\bBAP\b.{0,40}(aquacult|acuicult|seafood|shrimp|camar)", "Best Aquaculture Practices"),
    (r"Flor ?verde", "Florverde Sustainable Flowers"),
    (r"Global Recycled? Standard", "Global Recycled Standard"),
    (r"Recycled Claim Standard", "Recycled Claim Standard"),
    (r"Organic Content Standard", "Organic Content Standard"),
    (r"Content Claim Standard", "Content Claim Standard"),
    (r"IECEx", "IECEx Certified Equipment Scheme"),
    (r"\bGOTS\b|Global Organic Textile Standard", "GOTS"),
    (r"Sustainable Fibre Alliance|\bSFA\b.{0,30}(C00\d|cashmere|ноолуур)", "SFA Cashmere Standard"),
    (r"\bhalal\b|\bhelal\b|حلال", "Halal"),
    (r"OIML[- ]?CS\b|OIML Certification System", "OIML-CS"),
    (r"BRC\w*.{0,40}Packaging", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,40}Storage and Distribution", "BRCGS Storage and Distribution"),
    (r"BRC\w*.{0,40}Agents? and Brokers", "BRCGS Agents and Brokers"),
    (r"BRC\w*.{0,40}Consumer Products", "BRCGS Consumer Products"),
    (r"BRC\w*.{0,40}Food Safety|BRCGS Food|BRC Global Standard for Food", "BRCGS Food Safety"),
    (r"IFS Wholesale", "IFS Wholesale"), (r"IFS Logistics", "IFS Logistics"), (r"IFS Broker", "IFS Broker"),
    (r"IFS (HPC|Household)", "IFS HPC"), (r"IFS PAC ?secure", "IFS PACsecure"), (r"IFS Food", "IFS Food"),
    (r"\bSQF\b", "SQF"), (r"GMP\+", "GMP+ FSA"),
    (r"ISCC[ -]?PLUS", "ISCC PLUS"), (r"ISCC[ -]?EU", "ISCC EU"), (r"\b2BS", "2BSvs"),
    (r"PEFC", "PEFC Chain of Custody"), (r"\bFSC\b|Forest Stewardship", "FSC Chain of Custody"),
    (r"\bMSC\b|Marine Stewardship", "MSC Chain of Custody"),
    (r"Friend of the Sea", "Friend of the Sea"), (r"LEAF Marque", "LEAF Marque"),
    (r"EUROPRIVACY", "Europrivacy"), (r"Keymark", "CEN Keymark"), (r"Bio ?Suisse", "Bio Suisse Standard"),
    (r"GSTC", "GSTC Criteria"),
    (r"ISO/IEC 15408|Common Criteria", "Common Criteria (ISO/IEC 15408)"),
    (r"IEC 61215|IEC 61730", "IEC 61215 / IEC 61730"), (r"IEC 61400-22|IECRE", "IEC 61400-22 / IECRE"),
    (r"IEC 61508", "IEC 61508"), (r"IEC 62443", "IEC 62443"), (r"ISO 26262", "ISO 26262"),
    (r"EN 5012[689]", "EN 50126 / 50128 / 50129"), (r"EN 15085", "EN 15085-2"), (r"EN 15343", "EN 15343"),
    (r"ISO 3834", "ISO 3834"), (r"ISO 22005", "ISO 22005"), (r"ISO 13009", "ISO 13009"),
    (r"ISO 18295", "ISO 18295"), (r"ISO 22222", "ISO 22222"), (r"ISO 2999[0-4]", "ISO 29993"),
]


def _load_catalogue() -> set[str]:
    try:
        out = subprocess.run(["docker", "exec", "certifind-postgres", "psql", "-U", "postgres", "-d", "certifind_db",
                              "-t", "-A", "-c", "SELECT code FROM schemes"], capture_output=True, text=True,
                             encoding="utf-8", timeout=60, check=True).stdout
        codes = {l.strip() for l in out.splitlines() if l.strip()}
        if codes:
            return codes
    except Exception:  # noqa: BLE001  database not running: fall back to the codes known to exist (V66-V79)
        pass
    return {c for _, c in EU_SCHEMES + PRIVATE_SCHEMES}


CATALOGUE = _load_catalogue()
SCHEMES = [(re.compile(p, re.I), c) for p, c in EU_SCHEMES + PRIVATE_SCHEMES if c in CATALOGUE]
EU_CODES = {c for _, c in EU_SCHEMES}


def scheme_of(text: str) -> str:
    return next((c for rx, c in SCHEMES if rx.search(text)), "")


# First match wins: specific service sectors, manufacturing, then broad words. Multilingual (EN, DE, FR, NL,
# Nordic, PL, CS/SK, HU, ET, PT, RO, UK).
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"touris|turis|hotel|restaurant|catering|\bspa\b|beach", "tourism"),
    (r"medical device|medicinsk|medizin|medic|hospital|health ?care|patient|pharma|léčiv|lääk|gyógy", "health"),
    (r"educat|training|school|e-learning|teaching|oktat|koolitus|vzdělá", "public_education"),
    (r"cyber|software|\bICT\b|\bIT\b|informat|data protect|privacy|digital|cloud|PKI|signature|trust service|"
     r"kryptogr|\bIEC 62443|ISO/IEC 27\d\d\d|tietoturva", "ict"),
    (r"security services|alarm|guard|consult|credit|financ|insurance|call cent|contact cent|vagyonvéd", "professional"),
    (r"cosmetic|kosmet|detergent|chemi|kemi|chemik|vegyi|keemia|paint|maling|farb|lakk|fertili|gødning|"
     r"hnojiv|nawoz|biocid|lubric", "chemicals"),
    (r"plastic|plast\b|plasty|tworzyw|műanyag|kunststof|rubber|gumi|guma|kumi|packag|emballa|opakow|csomagol|"
     r"pakend|verpack|obal", "rubber_plastics"),
    (r"railway|rolling stock|\brail|jernbane|järnväg|rautatie|kolej|železn|vasút|raudtee|vehicle|fordon|"
     r"køretøj|pojazd|vozid|jármű|sõiduk|automotive|aircraft|aviation|marine|ship|vessel|boat|båt|fartyg|lod",
     "transport_equipment"),
    (r"weld|svejs|svets|hitsau|spaw|svař|zvár|hegeszt|keevit|steel|stål|teräs|stal\b|ocel|acél|teras|metal|"
     r"aluminium|alumin|cast iron|galvaniz|forg", "metals"),
    (r"machin|maskin|kone|maszyn|stroj|gép|masin|lift|elevator|hiss|heis|elevátor|winda|výtah|crane|kran|"
     r"pressure|tryk|tryck|paine|ciśnien|tlak|nyomás|surve|hoist", "machinery"),
    (r"electr|elektr|electron|photovolt|solar|aurinko|fotowolt|napelem|päike|cable|kabel|lamp|luminair|"
     r"switchgear|battery|batteri|akku|low voltage|lavspænding|lågspänning|ATEX|explosi", "electrical"),
    (r"construct|building|bygg|bygge|rakennus|budowl|staveb|stavebn|építő|ehitus|concrete|beton|cement|"
     r"brick|tegel|tile|glass|glas|lasi|szkło|sklo|üveg|klaas|window|vindu|fönster|ikkuna|okn|ablak|aken|"
     r"door|dør|dörr|ovi|drzw|dveř|ajtó|uks|insulat|isoler|eriste|izol|szigetel|soojustus|aggregat|kamen|"
     r"\bpipe|\btube|rør|rör|putki|rur|potrub|cső|toru|drinking water|dricksvatten|drikkevann|sanit|"
     r"roof|tak\b|katto|dach|střech|tető|katus|gypsum|gips|timber struct", "construction"),
    (r"textil|tekstil|clothing|garment|footwear|shoe|leather|læder|läder|nahk|bőr|kůž", "textiles"),
    (r"biofuel|biodiesel|biomass|pellet|fuel|brændsel|bränsle|polttoaine|paliw|palivo|üzemanyag|kütus|"
     r"energy|energi|energia|hydrogen|vety|wodór|vodík|hidrogén|vesinik|biogas|biometh|heat pump|varmepumpe|"
     r"värmepump|lämpöpumppu|boiler|kedel|panna|kazán|katel", "energy"),
    (r"recycl|genanvend|återvinn|kierrät|recykl|újrahasznos|ringlus|end-of-waste|scrap|waste|affald|avfall|"
     r"jäte|odpad|hulladék|jäätme|toy|legetøj|leksak|lelu|zabaw|hračk|játék|mänguas|furniture|møbel|möbel|"
     r"huonekalu|mebl|nábyt|bútor|mööbel|jewel|smykk|watch|ur\b", "other_manufacturing"),
    (r"wood|træ\b|trä\b|tre\b|puu\b|drewn|dřev|drev|fa\b|faanyag|puit|paper|papir|papper|paperi|papier|papír|"
     r"paber|forest|skov|skog|metsä|las\b|les\b|erdő|mets", "wood_paper"),
    (r"food|fødevar|livsmedel|elintarvi|żywnoś|potravin|élelmiszer|toidu|feed|foder|rehu|pasz|krmiv|takarmány|"
     r"sööt|wine|vin\b|viini|wino|víno|bor\b|vein|meat|kød|kött|liha|mięs|maso|hús|liha|dairy|mejeri|meieri|"
     r"maito|mlecz|mléko|tej|piim|fish|fisk|kala|ryb|hal\b|beverage|drik|dryck|juoma|napoj|ital|jook|"
     r"halal|kosher|honey|honning|honung|hunaja|miód|med\b|méz|mesi|bakery|bread|brød|bröd|leipä|chleb|"
     r"chléb|kenyér|leib", "food"),
    (r"organic|økolog|ekolog|luomu|ekologiczn|ekologick|bio\b|biolog|öko|mahe|agricult|landbrug|jordbruk|"
     r"maatal|rolnic|zeměděl|mezőgazd|põllum|crop|plant|seed|frø|frö|sieme|nasion|osiv|vetőmag|seemn|"
     r"aquacult|akvakult|vesiviljel|akwakult|fishing|fiskeri|animal welfare|dyrevelfærd|livestock|"
     r"husdyr|kotieläin|hospodářsk|állat|loom", "agriculture"),
    (r"logistic|transport|storage|warehouse|lager|varasto|magazyn|sklad|raktár|ladu|trade|handel|kauppa",
     "trade_logistics"),
    (r"service|tjeneste|tjänst|palvelu|usług|služb|szolgáltat|teenus|process", "professional"),
]]
DEFAULT_INDUSTRY = "other_manufacturing"


def industry_of(text: str) -> str:
    return next((ind for rx, ind in INDUSTRY_WORDS if rx.search(text)), "")


REF = re.compile(r"(?:\b|(?<=pr))((?:SS|NS|SFS|DS|PN|ČSN|STN|MSZ|EVS|NP|SR|DSTU|BS|DIN|NF|UNI|CEI|ÖNORM|SN|SIST)\s+)*"
                 r"(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN|AS|ANSI|UL|CSA|ASTM|JIS)\s*(\d{2,5})((?:-\d{1,3})*)")
ETSI = re.compile(r"ETSI\s+(EN|TS)\s+(\d{3})\s+(\d{3})((?:-\d+)?)")
EU_ACT = re.compile(r"\b(?:\(EU\)|\(EC\)|\(EEC\)|EU|EC|EEC)?\s*(?:No\.?\s*|nr\.?\s*)?(\d{2,4}/\d{1,4})(?:/(EU|EC|EEC|EG|EØF))?\b")


def refs(text: str) -> str:
    out: list[str] = []
    for m in ETSI.finditer(text):
        out.append(f"ETSI {m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}")
    t2 = ETSI.sub(" ", text)
    for m in REF.finditer(t2):
        body, num, part = m.group(3), m.group(4), m.group(5)
        if body in ("ISO", "IEC", "EN") and len(num) < 3:
            continue
        r = f"{'EN ' if m.group(2) and body != 'EN' else ''}{body} {num}{part}"
        if r not in out:
            out.append(r)
    return ";".join(out)


# Lines that are never scope content: page furniture, column headers, signatures, legal footers.
BOILER = re.compile(
    r"^(page \d+|side \d+|sida \d+|sivu \d+|strona \d+|strana \d+|oldal \d+|lk\.? ?\d+|\d+\s*(/|of|av|af|z|ze)\s*\d+|"
    r"\d{1,3}|annex|appendix|bilaga|bilag|liite|załącznik|příloha|príloha|melléklet|lisa|anexo|anexa|"
    r"scope of accreditation|accreditation scope|ackrediteringens omfattning|akkrediteringsomfang|"
    r"pätevyysalue|zakres akredytacji|rozsah akreditace|rozsah akreditácie|akkreditált terület|"
    r"akrediteerimisulatus|"
    r"product|products|produkt|produkter|tuote|tuotteet|wyrób|wyroby|výrobek|výrobky|termék|toode|"
    r"standard|standards|norm|normer|normit|normy|szabvány|standardid|normative documents?|"
    r"certification scheme|sertifiointijärjestelmä|scheme|"
    r"date|datum|päivämäärä|signature|underskrift|allekirjoitus|podpis|aláírás|allkiri|"
    r"remarks?|comments?|notes?|bemærkning|anmärkning|huomautus|uwagi|poznámk|megjegyzés|märkus|"
    r"no\.?|nr\.?|item|pos\.?|jrk\.? ?nr)\s*:?$", re.I)
NOISE = re.compile(r"^[\W\d_]{0,6}$")


def is_boiler(text: str) -> bool:
    t = clean(text)
    return not t or len(t) < 3 or bool(NOISE.match(t)) or bool(BOILER.match(t))


# ------------------------------------------------------------------ records
@dataclass
class Line:
    product_text: str = ""
    scheme_text: str = ""
    normative_docs: str = ""
    product_text_en: str = ""
    status: str = "ACTIVE"
    scheme: str | None = None      # None: classify; "" : force none
    industry: str | None = None    # None: classify


@dataclass
class Body:
    reg: str                       # certificate / accreditation number as published
    name: str
    country: str
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    issued: str = ""
    expiry: str = ""
    proof_url: str = ""
    source_url: str = ""
    active: bool = True
    status_note: str = ""
    lines: list[Line] = field(default_factory=list)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Dataset:
    def __init__(self, ab_code: str, folder: str, ms_dataset: str | None, register_url: str):
        self.ab = ab_code
        self.folder = folder
        self.out = DATA / folder
        self.ms = ms_dataset
        self.register_url = register_url
        self.notes: list[str] = []
        self.dropped: Counter = Counter()
        # existing body rows in every other dataset, by (country, name key)
        self.known: dict[tuple[str, str], dict] = {}
        for p in sorted(DATA.glob("*/bodies.csv")):
            if p.parent.name == folder:
                continue
            for r in _read(p):
                self.known.setdefault((r["country"], key(r["name"])), r)
        self.ms_acc = _read(DATA / ms_dataset / "accreditations.csv") if ms_dataset else []
        self.ms_bodies = {r["name"]: r for r in _read(DATA / ms_dataset / "bodies.csv")} if ms_dataset else {}
        # the AB's own MS dataset wins over other datasets that spell the same body differently
        for r in self.ms_bodies.values():
            self.known[(r["country"], key(r["name"]))] = r
        self.ms_certs = {r["certificate_number"]: r for r in self.ms_acc}

    def note(self, text: str) -> None:
        self.notes.append(text)

    # -------------------------------------------------------------- bodies
    def body_row(self, b: Body) -> tuple[dict, str]:
        """The CSV body row: reused from another dataset when the body is already known."""
        ms = self.ms_certs.get(b.reg)
        if ms and ms["body_name"] in self.ms_bodies:
            return dict(self.ms_bodies[ms["body_name"]]), f"reused from {self.ms} (same number {b.reg})"
        hit = self.known.get((b.country, key(b.name)))
        if hit:
            return dict(hit), "reused (same country and name)"
        row = {"name": clean(b.name), "country": b.country, "registration_no": "",
               "phone": phone(b.phone, b.country, self.notes, b.name) if b.phone else "",
               "email": email(b.email), "website": website(b.website), "address": clean(b.address),
               "source_url": url(b.source_url or self.register_url), "verified_at": ""}
        return row, ""

    # -------------------------------------------------------------- write
    def write(self, bodies: list[Body], today: str, sources_extra: str = "") -> dict:
        self.out.mkdir(parents=True, exist_ok=True)
        body_rows: dict[str, dict] = {}
        acc_rows, ps_rows, reused = [], [], []
        used_certs: set[str] = set()
        stats = Counter()
        for b in sorted(bodies, key=lambda x: (x.reg, x.name)):
            if not b.active:
                self.dropped[f"not accredited ({b.status_note or 'inactive'})"] += 1
                self.note(f"{b.reg} {b.name}: skipped, register status {b.status_note or 'inactive'}")
                continue
            kept = []
            seen_txt = set()
            for ln in b.lines:
                prod, sch, norm = clean(ln.product_text), clean(ln.scheme_text), clean(ln.normative_docs)
                full = " ".join(x for x in (prod, sch, norm) if x)
                if not full or is_boiler(full):
                    self.dropped["boilerplate / header line"] += 1
                    continue
                if full.casefold() in seen_txt:
                    self.dropped["duplicate line within the accreditation"] += 1
                    continue
                seen_txt.add(full.casefold())
                scheme = scheme_of(full) if ln.scheme is None else ln.scheme
                industry = "" if scheme else (ln.industry if ln.industry is not None else industry_of(full))
                if not scheme and not industry:
                    industry = DEFAULT_INDUSTRY
                    stats["industry defaulted"] += 1
                kept.append({"scheme": scheme, "industry": industry, "product_text": prod,
                             "product_text_en": clean(ln.product_text_en), "scheme_text": sch,
                             "normative_docs": norm, "standard_refs": refs(full), "status": ln.status})
            if not kept:
                self.dropped["body with no importable scope line"] += 1
                self.note(f"{b.reg} {b.name}: no scope line could be read; body not imported")
                continue
            row, how = self.body_row(b)
            if row["name"] in body_rows and body_rows[row["name"]] != row:
                self.note(f"{b.reg}: body name '{row['name']}' already used by another row; kept the first row")
            body_rows.setdefault(row["name"], row)
            if how:
                reused.append(f"{b.reg} {row['name']}: {how}")
            cert = clean(b.reg)
            if cert in self.ms_certs or cert in used_certs:
                cert = f"{cert} (17065)"
            n = 2
            while cert in used_certs:
                cert = f"{clean(b.reg)} (17065-{n})"
                n += 1
            used_certs.add(cert)
            issued = iso_date(b.issued) or b.issued
            if not issued:
                issued = today
                self.note(f"{cert}: no issue date in the register; run date {today} used")
            acc_rows.append({"ab_code": self.ab, "certificate_number": cert, "body_name": row["name"],
                             "accreditation_standard": STANDARD, "status": "ACTIVE", "issue_date": issued,
                             "expiry_date": iso_date(b.expiry), "proof_url": url(b.proof_url or self.register_url)})
            for i, k in enumerate(kept, 1):
                ps_rows.append({"certificate_number": cert, "line_no": i, **k})
                stats["lines with scheme" if k["scheme"] else "lines without scheme"] += 1
        # one accreditation per body and standard (uq_cb_ab_standard): merge duplicates into the first
        by_body: dict[str, str] = {}
        merged_acc = []
        remap = {}
        for a in acc_rows:
            first = by_body.get(a["body_name"])
            if first:
                remap[a["certificate_number"]] = first
                self.note(f"{a['certificate_number']}: same body as {first} ({a['body_name']}); lines merged into {first}")
                continue
            by_body[a["body_name"]] = a["certificate_number"]
            merged_acc.append(a)
        if remap:
            counters = Counter()
            final = []
            for r in ps_rows:
                c = remap.get(r["certificate_number"], r["certificate_number"])
                final.append({**r, "certificate_number": c})
            final.sort(key=lambda r: (r["certificate_number"], 0))
            out_rows = []
            for r in final:
                counters[r["certificate_number"]] += 1
                out_rows.append({**r, "line_no": counters[r["certificate_number"]]})
            ps_rows = out_rows
        self._csv("bodies.csv", BODY_COLS, list(body_rows.values()))
        self._csv("accreditations.csv", ACC_COLS, merged_acc)
        self._csv("scopes.csv", SCOPE_COLS, [])
        self._csv("product_scopes.csv", PS_COLS, ps_rows)
        result = {"bodies": len(body_rows), "accreditations": len(merged_acc), "lines": len(ps_rows),
                  "with_scheme": stats["lines with scheme"], "without_scheme": stats["lines without scheme"],
                  "industry_defaulted": stats["industry defaulted"], "reused": reused, "today": today}
        self._sources(result, sources_extra)
        return result

    def _csv(self, name, cols, rows):
        with open(self.out / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    def _sources(self, r: dict, extra: str):
        dropped = "\n".join(f"- {reason}: {n}" for reason, n in self.dropped.most_common()) or "- none"
        reused = "\n".join(f"- {x}" for x in r["reused"]) or "- none"
        text = f"""# {self.ab} - ISO/IEC 17065

Source: {self.register_url}

{extra.strip()}

Converted with the shared `database/certifind_17065_common.py` (rules of `/add-country-17065`). Not yet verified by a
person, so `verified_at` is empty.

Rules:

- One accreditation row per body, `accreditation_standard` = ISO/IEC 17065. A certificate number that the AB's
  management system dataset (`{self.ms or 'none'}`) already uses gets the suffix ` (17065)`.
- `scopes.csv` is header only (no EA codes for 17065).
- `product_scopes.csv`: one row per scope line, in register/annex order, text verbatim (whitespace collapsed).
  `scheme` only when the text cites a scheme in the `schemes` catalogue (EU directive/regulation number or a
  private scheme name). Lines without a scheme get an `industry` from keywords; when no keyword matches it is
  `{DEFAULT_INDUSTRY}` ({r['industry_defaulted']} lines). National schemes stay text only.
- Body rows already present in another dataset are copied unchanged; others are built from the register.
- Only bodies the register lists as accredited are imported.

Left out:

{dropped}

Reused body rows:

{reused}

| Retrieved | Bodies | Accreditations | Product lines | with scheme | without scheme |
| --- | --- | --- | --- | --- | --- |
| {r['today']} | {r['bodies']} | {r['accreditations']} | {r['lines']} | {r['with_scheme']} | {r['without_scheme']} |
"""
        (self.out / "SOURCES.md").write_text(text, encoding="utf-8")

    def review(self, path: Path, result: dict) -> None:
        lines = [f"# {self.ab} 17065 review", "", f"Bodies {result['bodies']}, accreditations {result['accreditations']}, "
                 f"lines {result['lines']} ({result['with_scheme']} with scheme, {result['industry_defaulted']} industry defaulted).",
                 "", "## Left out", ""]
        lines += [f"- {k}: {v}" for k, v in self.dropped.most_common()] or ["- none"]
        lines += ["", "## Notes", ""] + ([f"- {n}" for n in self.notes] or ["- none"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(ab: str, folder: str, ms: str | None, url: str, bodies: list[Body], review_path: Path, today: str,
        sources_extra: str = "", pre_notes: list[str] | None = None) -> dict:
    ds = Dataset(ab, folder, ms, url)
    for n in pre_notes or []:
        ds.note(n)
    res = ds.write(bodies, today, sources_extra)
    ds.review(review_path, res)
    print(f"{folder}: {res['bodies']} bodies, {res['accreditations']} accreditations, {res['lines']} lines "
          f"({res['with_scheme']} with scheme, {res['industry_defaulted']} industry defaulted); "
          f"left out {dict(ds.dropped)}")
    return res


# ------------------------------------------------------------------ header-driven table mapping
HDR_PRODUCT = re.compile(r"product|produkt|toode|tuote|termék|výrob|wyrób|produto|produs|продукц|"
                         r"process|item|family|famille|catégor|produit|scope|covered|kategor|title|description|"
                         r"denumire|název", re.I)
HDR_NORM = re.compile(r"normative|standard|norm|technical spec|specification|szabvány|regulation|criteria|"
                      r"critérios|référentiel|requirement|vaatimus|kravspec|документ", re.I)
HDR_SCHEME = re.compile(r"scheme|skeem|system|avcp|module|moodul|modul|procedure|procedur|programme|"
                        r"procedimento|järjestelmä|схем", re.I)
HDR_SKIP = re.compile(r"^(no\.?|nr\.?|jrk\.? ?nr|s\.? ?no\.?|sl\.? ?no\.?|item no|#|iaf scope|ea code|"
                      r"otsus decision|decision|remarks?|märkus|type)(?=[\s:.,(]|$)", re.I)


def header_map(cells: list[str]) -> dict[int, str] | None:
    """Column index -> 'product' / 'norm' / 'scheme' when the row looks like a table header, else None."""
    texts = [clean(x) for x in cells]
    filled = [t for t in texts if t]
    # header cells are short labels; a data row that mentions "standard" or "process" is not a header
    # (a trailing footnote mark such as "Degrees of freedom1" is allowed)
    # "(ISO/IEC 17067)" in a "Type" column label is allowed too
    if not filled or any(len(t) > 110 or len(t.split()) > 14 or
                         re.search(r"\d", re.sub(r"\d+\)?$", "", re.sub(r"\(?(cf\. )?ISO/IEC 17067\)?", "", t)))
                         for t in filled):
        return None
    m: dict[int, str] = {}
    for i, t in enumerate(texts):
        if not t or HDR_SKIP.match(t):
            continue
        if HDR_SCHEME.search(t) and not re.search(r"product|produkt|výrob|toode|tuote|termék|wyrób|produto",
                                                  t.split("/")[0], re.I):
            m[i] = "scheme"
        elif HDR_NORM.search(t):
            m[i] = "norm"
        elif HDR_PRODUCT.search(t):
            m[i] = "product"
    hits = set(m.values())
    return m if "product" in hits and len(hits) >= 2 else None


def rows_to_lines(rows: list[list[str]], fallback: dict[int, str] | None = None,
                  strict: bool = False) -> tuple[list[Line], int]:
    """Turn table rows into Lines using the latest header seen. Rows before any header use `fallback`
    (or the whole row as product text). Returns (lines, header rows dropped)."""
    cur = fallback
    out, headers = [], 0
    for cells in rows:
        hm = header_map(cells)
        if hm:
            cur, headers = hm, headers + 1
            continue
        if cur:
            parts = {"product": [], "norm": [], "scheme": []}
            for i, t in enumerate(cells):
                t = clean(t)
                if t and i in cur:
                    parts[cur[i]].append(t)
            if not any(parts.values()):
                rest = " | ".join(clean(t) for t in cells if clean(t))
                if rest:
                    out.append(Line(product_text=rest))
                continue
            out.append(Line(product_text=" | ".join(parts["product"]), normative_docs=" | ".join(parts["norm"]),
                            scheme_text=" | ".join(parts["scheme"])))
        elif not strict:
            rest = " | ".join(clean(t) for t in cells if clean(t))
            if rest:
                out.append(Line(product_text=rest))
    return out, headers


def cli(default_scrape: Path) -> tuple[Path, str]:
    """Arguments of every converter: [scrape_dir] [--today YYYY-MM-DD]."""
    import sys
    argv = sys.argv[1:]
    pos = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--today")]
    today = argv[argv.index("--today") + 1] if "--today" in argv else date.today().isoformat()
    return (Path(pos[0]) if pos else default_scrape), today


def rd(path: Path) -> list[dict]:
    return _read(Path(path))


# ------------------------------------------------------------------ industry refinements (checked first)
# ICS (International Classification for Standards) field -> V70 industry; used when a line cites "ICS".
ICS_INDUSTRY = {"11": "health", "17": "other_manufacturing", "21": "machinery", "23": "machinery",
                "25": "machinery", "27": "energy", "29": "electrical", "31": "electrical", "33": "ict", "35": "ict",
                "37": "other_manufacturing", "39": "other_manufacturing", "43": "transport_equipment",
                "45": "transport_equipment", "47": "transport_equipment", "49": "transport_equipment",
                "53": "machinery", "55": "rubber_plastics", "59": "textiles", "61": "textiles", "65": "agriculture",
                "67": "food", "71": "chemicals", "73": "construction", "75": "energy", "77": "metals",
                "79": "wood_paper", "81": "construction", "83": "rubber_plastics", "85": "wood_paper",
                "87": "chemicals", "91": "construction", "93": "construction", "97": "other_manufacturing"}
ICS_RE = re.compile(r"\bICS\b\W*((?:\d{2}(?:\.\d{2,3})*[\s,;]*)+)", re.I)
EXTRA_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    # French
    (r"viande|abats|volaille|lait|fromage|boisson|spiritueu|\bvins?\b|fruits?\b|légume|céréal|alimentaire|"
     r"charcut|poisson|\bmiel\b|œufs?|oeufs?|denrée|produits laitiers|beurre|huile d'olive|pain\b|farine", "food"),
    (r"formation|compétences|enseignement|apprentissage", "public_education"),
    (r"services immobiliers|conseil|audit\b|prestataire", "professional"),
    (r"agricult|végét|animaux|semence|aquacult|biologique|élevage", "agriculture"),
    # Spanish (Uruguay, Latin America)
    (r"calentador|cilindro|propano|butano|supergás|gas licuado|eficiencia energ|petróleo|combustible", "energy"),
    (r"interruptor|lámpara|envolvente|cajas? (de|para)|artefactos? eléctric|baja tensión|eléctric|enchufe|"
     r"tomacorriente|conductor|cable", "electrical"),
    (r"juguete|toy", "other_manufacturing"),
    # Ukrainian
    (r"медичн|діагностик|лікар|фармац", "health"),
    (r"колісн|транспортн|залізнич|рухом|причеп|причіп|автомобіл|вагон|трактор|мотоцикл", "transport_equipment"),
    (r"будівел|конструкці|труб|цемент|бетон|вікн|двер|скл[оа]\b|покрівл|утеплюв", "construction"),
    (r"електричн|електронн|радіообладн|кабел|світильн|ламп|акумулятор|вимірювальн|прилад", "electrical"),
    (r"бензин|палив|дизельн|газ\b|котл|енерг|нафт", "energy"),
    (r"машин|устаткуван|обладнання.{0,20}тиском|тиском|ліфт|підйомн|верстат", "machinery"),
    (r"харчов|продукти харчув|м'яс|молок|напо|зерн|борошн|хліб|риб|корм", "food"),
    (r"насінн|садивн|сільськогосподарськ|лісогосподарськ|добрив|рослин|тварин|органічн", "agriculture"),
    (r"мийн|хімічн|косметик|фарб|лак|пестицид", "chemicals"),
    (r"текстильн|одяг|взутт|шкір", "textiles"),
    (r"металев|з металу|сталь|сталев|чавун|прокат", "metals"),
    (r"іграш|меблі|посуд|вироби побутов", "other_manufacturing"),
    (r"індивідуального захисту|засоби захисту|безпеки", "machinery"),
    (r"послуг|обслуговуван|зелений офіс", "professional"),
    (r"\bIEC 6\d{4}|\bEN 6\d{4}", "electrical"),
    (r"surg|scissor|forceps|medical", "health"),
    (r"vehículo|neumático|bicicleta|casco", "transport_equipment"),
    # Portuguese / Spanish / Romanian
    (r"leite|queij|vinh|azeit|água mineral|agua mineral|bebida|pão\b|enchid|presunto|fruta|hortí|mel\b|"
     r"alimentar|carne|pescad|conserv|lacticín|aliment|vin\b|brânz|lapte", "food"),
    (r"agregad|cimento|betão|cerâmic|telha|tijolo|argamass|caixilh|vidro|tubagem|torneira|loiça sanit", "construction"),
    (r"lâmpad|ilumin|seccionador|corrente|tensão|aparelhos de cozinha|eletrodom|electrodom|elétric|eléctric|"
     r"electric|motor\b|motors\b|transformer|tap-changer|switch|relay|meter\b|thermometer", "electrical"),
    (r"máscara|calçado|vestuário|têxt|footwear|garment|\bcords?\b|\bropes?\b|\bcorda", "textiles"),
    (r"fio de máquina|aço|varão|chapa|laminad|perfis metálicos|axle|wheel|rail\b", "metals"),
    (r"clínic|saúde|hospitalar|surgical|syringe|thermometer|condom|glove", "health"),
    (r"pump|valve|compressor|bomba|válvul|closet|cistern|tap\b|faucet|boiler", "machinery"),
    # Polish
    (r"roślin|rolnic|zboż|uprawy|ekologiczn", "agriculture"),
    (r"produktów regionalnych|tradycyjnych|żywnoś|mięs|mleka|QAFP|QMP|KZR", "food"),
    # Estonian
    (r"tulekustut|tuletõke|korsten|korstn|lõõr|liiklus|ehitus|fire-fighting|fire barrier|chimney|flue|"
     r"fire detection|sprinkler|circulation fixture|road equipment", "construction"),
    (r"kompost|compost|väetis", "agriculture"),
]]
JUNK = re.compile(r"^(show more|show less|read more|requirements for certification bodies|"
                  r"click here|back to top|download)$", re.I)
_base_industry_of = industry_of
_base_is_boiler = is_boiler


def industry_of(text: str) -> str:  # noqa: F811
    m = ICS_RE.search(text)
    if m:
        for code in re.findall(r"(?<![\d.])(\d{2})(?![\d])", m.group(1)):
            if code in ICS_INDUSTRY:
                return ICS_INDUSTRY[code]
    hit = next((ind for rx, ind in EXTRA_WORDS if rx.search(text)), "")
    return hit or _base_industry_of(text)


# ISO/IEC 17067 scheme-type lines ("Elementele prevazute de schema 5 din SR EN ISO/IEC 17067") have no column
SCHEME_TYPE = re.compile(r"^(?=.*17067)(?!.*\b(EN|ISO|IEC)\s*(?!17067)\d{3,5}).{0,160}$", re.I)


def is_boiler(text: str) -> bool:  # noqa: F811
    t = clean(text)
    return _base_is_boiler(t) or bool(JUNK.match(t)) or bool(SCHEME_TYPE.match(t))


STATEMENT = re.compile(r"(szerint akkreditálva|accredited (according|in accordance|to)|akkrediteret|ackrediter|"
                       r"akkreditoitu|akredytowan|akreditován|akreditovan|akrediteeritud|acreditad)", re.I)


def text_to_lines(text: str, keep_statement: bool = False) -> list[Line]:
    """Free scope text -> Lines. A line ending with ':' is a heading: not imported itself, it becomes the
    scheme_text of the lines under it (and its scheme, via classification of the joined text). Wrapped lines
    (starting lower-case after a line without closing punctuation) are joined. The opening accreditation
    statement ('... szerint akkreditálva:') is dropped unless keep_statement."""
    raw = [clean(l) for l in (text or "").splitlines()]
    joined: list[str] = []
    for l in raw:
        if not l:
            continue
        if joined and l[:1].islower() and not re.search(r"[;:.]$", joined[-1]) and not re.match(r"^[a-z]\)", l):
            joined[-1] += " " + l
        else:
            joined.append(l)
    out, heading = [], ""
    for l in joined:
        if l.endswith(":"):
            if STATEMENT.search(l) and not keep_statement:
                heading = ""
                continue
            heading = l.rstrip(":").strip()
            continue
        out.append(Line(product_text=l, scheme_text=heading))
    if not out and heading:
        out.append(Line(product_text=heading))
    return out


# ------------------------------------------------------------------ PDF annexes
PAGE_FURNITURE = re.compile(r"^(page|side|sida|sivu|strona|strana|oldal|pagina|página|seite|stránka)\s*\d+|"
                            r"^\d+\s*(/|of|av|af|z|ze|de|di|von|из|з)\s*\d+$|^-\s*\d+\s*-$", re.I)


def pdf_rows(path: Path, skip_pages: int = 0) -> tuple[list[list[str]], str]:
    """Rows of the annex: table rows (pdfplumber) per page, else text lines as one-cell rows.
    Returns (rows, mode) with mode 'tables', 'text' or 'no text layer'."""
    import pdfplumber
    rows: list[list[str]] = []
    modes = set()
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i < skip_pages:
                    continue
                tables = [t for t in page.extract_tables(table_settings={"text_x_tolerance": 1.5}) if t and len(t) > 1 and max(len(r) for r in t) > 1]
                if tables:
                    modes.add("tables")
                    for t in tables:
                        for r in t:
                            cells = [clean(x) for x in r]
                            if any(cells):
                                rows.append(cells)
                    continue
                text = page.extract_text() or ""
                if text.strip():
                    modes.add("text")
                    rows += [[l] for l in (clean(x) for x in text.splitlines()) if l and not PAGE_FURNITURE.match(l)]
    except Exception as e:  # noqa: BLE001
        return [], f"unreadable ({e.__class__.__name__})"
    return rows, ("tables" if "tables" in modes else "text" if modes else "no text layer")


def pdf_lines(path: Path, skip_pages: int = 0, fallback: dict[int, str] | None = None,
              strict: bool = True) -> tuple[list[Line], str]:
    """Annex lines from the PDF's tables. strict: only rows under a recognised product/standard header (site,
    address and signature tables are ignored); text-only PDFs then give no lines."""
    rows, mode = pdf_rows(path, skip_pages)
    if strict:
        rows = [r for r in rows if len(r) > 1]
    lines, _ = rows_to_lines(rows, fallback, strict=strict)
    return lines, mode
