"""ARMNAB ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py [scrape out (default armnab_17065)] [dataset dir] [--exclude]
                                         [--today YYYY-MM-DD]

Input: armnab_17065_raw.json and scope_lines.csv from scrape_am_armnab_17065.py (Armenian only). A scope is a list:
section heading ("ԿԱՆՈՆԱԿԱՐԳՎՈՂ ՈԼՈՐՏ" regulated / "ՉԿԱՆՈՆԱԿԱՐԳՎՈՂ ՈԼՈՐՏ" voluntary), numbered product groups
("1." or "1. text") and products ("1.1. text"), HS (ԵԱՏՄ ԱՏԳ ԱԱ) code lines, then the documents (government
decisions, laws, GOST / ՀՍՏ standards) and the certification procedure for the products above them.
One product line per product: product_text = the product (with its group), HS codes appended; normative_docs =
the documents that follow it. Procedure / scheme / test-method lines are dropped. Layout follows
../../italy/accredia-italy-17065/prepare_certifind_17065.py.
"""
import collections, csv, json, re, sys, unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent
DATA = DB.parent / "certifind" / "data"

AB_CODE = "ARMNAB"
STD = "ISO/IEC 17065"
MS_DATASET = "armnab-armenia"  # the ARMNAB 17021 dataset: names "English («Armenian»)"
COUNTRY = "Armenia"
ACTIVE = "Գործող"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                         "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
COUNTRY_FIX = {"Türkiye": "Turkey", "Czech Republic": "Czechia", "Viet Nam": "Vietnam"}
# same legal entity under another spelling in another dataset
SAME_AS = {"033/S-059": "ECOGLOBE LLC"}   # ԷԿՈԳԼՈԲ, dakks-germany-17065 D-ZE-18154

# Scheme table from the ACCREDIA template (EU / private / ISO schemes). Armenian scopes cite national documents
# (government decisions, laws, GOST / ՀՍՏ); those are national schemes and stay as text with an industry.
SCHEMES = [(re.compile(p, re.I), c) for p, c in [
    (r"2018/848|834/2007", "EU Organic Regulation (EU) 2018/848"),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,40}Food Safety", "BRCGS Food Safety"),
    (r"IFS Food", "IFS Food"),
    (r"\bSQF\b", "SQF"),
    (r"GMP\+", "GMP+ FSA"),
    (r"PEFC", "PEFC Chain of Custody"),
    (r"22005", "ISO 22005"),
    (r"15085", "EN 15085-2"),
    (r"3834", "ISO 3834"),
]]

SECTION = re.compile(r"^(Չ?ԿԱՆՈՆԱԿԱՐԳՎՈՂ ՈԼՈՐՏ)\s*$")
NUM_ONLY = re.compile(r"^(\d{1,2})[.․]\s*$")
NUMBERED = re.compile(r"^(\d{1,2}(?:[.․]\d{1,2})+[.․]?|\d{1,2}[.․])\s+(.+)$")  # a dot is required: "10 կգ", "16 հունվարի" are text
HS_TOKEN = r"\d{4}(?:\s?\d{2}(?:\s?\d{3}(?:\s?\d)?)?)?(?:-ից)?"
HS_LINE = re.compile(rf"^(?:{HS_TOKEN})(?:\s*[,;]\s*{HS_TOKEN})*\s*,?$")
HS_TAIL = re.compile(rf"\s+((?:{HS_TOKEN})(?:\s*[,;]\s*{HS_TOKEN})*)\s*$")
DOC = re.compile(r"որոշում|N\s?\d+-Ն|ԳՕՍՏ|ГОСТ|ՀՍՏ|ԻՍՕ|\bISO\b|\bEN\b|\bIEC\b|ԻԷԿ|ASTM|ՍՏ ՌԴ|ՀՆ N|կառավարության|օրենք|"
                 r"հրաման|ՄՄ ՏԿ|ТР ТС|ԵԱՏՄ|տեխնիկական կանոնակարգ|ՍանՊիՆ|ՍՆ և Կ|ՍՆԻՊ|СНиП", re.I)
DROPS = [(re.compile(p, re.I), r) for p, r in [
    (r"^-{3,}|^-//-$", "separator / ditto mark"),
    (r"ընթացակարգ|սխեմա|ԿԱՐԳ\b|^\(?\d\s?[ՍսS](\s*,\s*\d\s?[ՍսS])*\)?$|^\d[ՍսS][, ]", "certification procedure / scheme"),
    (r"փորձարկման.*մեթոդ|մեթոդներ|նմուշառման", "test / sampling methods"),
    (r"^և ըստ|^Ըստ ներկայացվող|^Կոնկրետ արտադրանքի|^Ըստ .*հրամանով հաստատված", "'and per submitted documents' note"),
    (r"Հավատարմագրման ոլորտի (արդիականացման|նկարագրությունը)|որոշում № .* առ", "scope amendment note"),
]]
NATIONAL = re.compile(r"կառավարության|օրենք|հրաման|ՀՍՏ|ԳՕՍՏ", re.I)
EXCLUDE = "--exclude" in sys.argv

# HS chapter -> industry (language independent; Armenian scopes give HS codes for nearly every product)
HS_INDUSTRY = [((1, 14), "agriculture"), ((15, 24), "food"), ((25, 26), "construction"), ((27, 27), "energy"),
               ((28, 38), "chemicals"), ((39, 40), "rubber_plastics"), ((41, 43), "textiles"),
               ((44, 49), "wood_paper"), ((50, 67), "textiles"), ((68, 70), "construction"),
               ((71, 71), "other_manufacturing"), ((72, 83), "metals"), ((84, 84), "machinery"),
               ((85, 85), "electrical"), ((86, 89), "transport_equipment"), ((90, 90), "health"),
               ((91, 97), "other_manufacturing")]
INDUSTRY_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"ցեմենտ|բետոն|շինարար|ավազ|խիճ|աղյուս|ապակ", "construction"),
    (r"պողպատ|մետաղ|երկաթ", "metals"),
    (r"էլեկտր|ռադիո|հեռահաղորդ", "electrical"),
    (r"լվացող|մաքրող|լաք|ներկ|պարարտանյութ|քիմի|կոսմետ", "chemicals"),
    (r"պլաստ|պոլիմեր|ռետին", "rubber_plastics"),
    (r"թուղթ|փայտ", "wood_paper"),
    (r"մանածագործ|հագուստ|կոշիկ|կաշի", "textiles"),
    (r"սնունդ|սննդ|մթերք|խմիչք|գինի|օղի|կոնյակ|հաց|միս|կաթ|մեղր|պահածո|ծխախոտ|ջուր", "food"),
    (r"գյուղատնտես|օրգանական|կեր|բույս|պտուղ|բանջար|անասուն|թռչուն", "agriculture"),
    (r"ծառայություն", "professional"),
    (r"մածուն|լավաշ|բաստուրմա|սուջուխ|աշխարհագրական նշ", "food"),
    (r"հրազեն|զենք|նիկոտին", "other_manufacturing"),
]]
REF = re.compile(r"\b((?:UNI|CEI|BS|DIN|NF)\s+)*(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{3,5})((?:-\d{1,3})?)")
NREF = re.compile(r"(ԳՕՍՏ(?: Ռ)?(?: ԻՍՕ| ԻԷԿ| EN)?|ՀՍՏ|ASTM)\s*([A-Z]?\s?\d[\d.\-/ ]*\d)")
WS = re.compile(r"\s+")


def clean(t):
    return WS.sub(" ", (t or "").replace("․", ".").replace("¬", "").replace("00ad", "")).strip()


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def scheme_of(t):
    return next((c for rx, c in SCHEMES if rx.search(t)), "")


def refs(t):
    out = []
    for m in REF.finditer(t):
        org = m.group(3)
        out.append(f"{'EN ' if m.group(2) and org != 'EN' else ''}{org} {m.group(4)}{m.group(5)}")
    for m in NREF.finditer(t):
        org = m.group(1).replace("ԳՕՍՏ Ռ", "GOST R").replace("ԳՕՍՏ", "GOST").replace("ՀՍՏ", "AST") \
            .replace(" ԻՍՕ", " ISO").replace(" ԻԷԿ", " IEC")
        out.append(f"{org} {m.group(2).strip()}")
    return ";".join(dict.fromkeys(out))


def industry_of(hs, *texts):
    for code in hs:
        ch = int(code[:2])
        for (lo, hi), ind in HS_INDUSTRY:
            if lo <= ch <= hi:
                return ind
    for t in texts:
        for rx, ind in INDUSTRY_WORDS:
            if t and rx.search(t):
                return ind
    return ""


def hs_codes(t):
    return [c.strip() for c in re.split(r"[,;]", t) if re.match(r"\d{4}", c.strip())]


def classify(lines):
    """Scope text lines -> (product lines, dropped Counter)."""
    out, dropped = [], collections.Counter()
    section, group = "", ""
    pending = []              # products waiting for their documents
    docs_open = False         # documents have started for the pending products
    expect_name = False       # previous line was a bare "N."

    def flush():
        nonlocal pending, docs_open
        out.extend(pending); pending = []; docs_open = False

    def new_product(text, num=""):
        nonlocal docs_open
        if docs_open:
            flush()
        p = {"num": num, "text": text, "hs": [], "docs": [], "section": section, "group": group}
        pending.append(p)
        return p

    for raw in lines:
        t = clean(raw)
        if not t:
            continue
        if SECTION.match(t):
            flush(); section, group = t, ""; continue
        m = NUM_ONLY.match(t)
        if m:
            flush(); expect_name, group = True, ""; continue
        reason = next((r for rx, r in DROPS if rx.search(t)), "")
        if reason and (not NUMBERED.match(t) or re.match(r"^\d+\s+(հունվարի|[ՍսS])", t)):
            dropped[reason] += 1; continue
        if re.match(r"^\d+\s+հունվարի\s+\d{4}|^N\s?\d+-Ն որոշմամբ հաստատված\s*$|^Համաձայն ՀՀ կառավարության\s*$", t):   # wrapped "Համաձայն ... 16 հունվարի 2014 ... սխեմաների"
            dropped["certification procedure / scheme"] += 1; continue
        if HS_LINE.match(t):
            if pending:
                pending[-1]["hs"] += hs_codes(t)
            else:
                dropped["HS codes without a product"] += 1
            continue
        if DOC.search(t) and not NUMBERED.match(t) and not expect_name:
            if not pending:
                dropped["document without a product"] += 1; continue
            docs_open = True
            for p in pending:
                p["docs"].append(t)
            continue
        m = NUMBERED.match(t)
        if m:
            num, text = m.group(1).rstrip(".․").replace("․", "."), m.group(2)
            tail = HS_TAIL.search(text)
            hs = hs_codes(tail.group(1)) if tail else []
            if tail:
                text = text[:tail.start()].strip()
            if "." not in num:                     # top-level group: a product until children appear
                flush(); group = text
                p = new_product(text, num); p["hs"] += hs
            else:
                if pending and pending[-1]["num"] and "." not in pending[-1]["num"] and not pending[-1]["hs"] \
                        and not pending[-1]["docs"]:
                    pending.pop()                  # its first child: the group is a heading, not a product
                p = new_product(text, num); p["hs"] += hs
            expect_name = False
            continue
        # unnumbered text: product name after a bare "N.", a wrapped name, or a new product after documents
        if expect_name:
            group = t
            new_product(t); expect_name = False
        elif pending and not pending[-1]["hs"] and not docs_open:
            pending[-1]["text"] += " " + t
            if pending[-1]["text"].startswith(group) or not group:
                group = pending[-1]["text"] if not pending[-1]["num"] or "." not in pending[-1]["num"] else group
        else:
            new_product(t)
    flush()

    result = []
    for p in out:
        text = p["text"]
        if p["group"] and p["group"] != text and not text.startswith(p["group"]):
            text = f"{p['group']}: {text}"
        if p["hs"]:
            text += f" (HS {', '.join(dict.fromkeys(p['hs']))})"
        docs = "; ".join(dict.fromkeys(p["docs"]))
        scheme = scheme_of(text + " " + docs)
        if EXCLUDE and not scheme and NATIONAL.search(docs):
            dropped["national scheme (--exclude)"] += 1; continue
        result.append({"scheme": scheme, "industry": "" if scheme else industry_of(p["hs"], text, docs),
                       "product_text": text, "scheme_text": p["section"], "normative_docs": docs,
                       "standard_refs": refs(docs)})
    return result, dropped


def phone(raw):
    d = re.sub(r"\D", "", (raw or "").split(",")[0])
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    elif d.startswith("0"):
        d = "374" + d[1:]
    elif not d.startswith("374"):
        d = "374" + d
    return f"+374 {d[3:5]} {d[5:]}"


def brand(name):
    """The «quoted» Armenian brand name, the part both ARMNAB registers share."""
    m = re.search(r"«([^»]+)»", name or "")
    return clean(m.group(1)).replace("և", "ԵՎ").upper() if m else ""


def load_bodies(out_dir):
    by_name, by_exact = {}, {}
    for f in sorted(DATA.glob("*/bodies.csv")):
        if f.parent.resolve() == out_dir.resolve():
            continue
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                by_name.setdefault((key(row["name"]), row["country"]), (row, f.parent.name))
                by_exact.setdefault(row["name"], (row, f.parent.name))
                if f.parent.name == MS_DATASET and brand(row["name"]):
                    by_exact.setdefault("«" + brand(row["name"]) + "»", (row, f.parent.name))
    return by_name, by_exact


def main():
    argv = sys.argv[1:]
    today = date.today().isoformat()
    if "--today" in argv:
        today = argv[argv.index("--today") + 1]
    args = [a for a in argv if not a.startswith("--") and a != today]
    src = Path(args[0]) if args else HERE / "armnab_17065"
    out = Path(args[1]) if len(args) > 1 else DATA / "armnab-armenia-17065"
    out.mkdir(parents=True, exist_ok=True)
    recs = json.loads((src / "armnab_17065_raw.json").read_text(encoding="utf-8"))
    by_reg = collections.defaultdict(list)
    with open(src / "scope_lines.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            by_reg[r["registration_no"]].append(r["product_text_raw"])
    by_name, by_exact = load_bodies(out)

    bodies, accs, ps = {}, [], []
    dropped, dropped_bodies = collections.Counter(), collections.defaultdict(set)
    bodies_dropped, reused, no_scheme_refs = [], [], collections.Counter()
    for rec in sorted(recs, key=lambda r: r["registration_no"]):
        reg, name = rec["registration_no"], clean(rec["name"])
        if rec["status"] != ACTIVE:
            bodies_dropped.append(f"{reg} {name}: {rec['status']} (terminated)"); continue
        if rec["expiry"] and rec["expiry"] < today:
            bodies_dropped.append(f"{reg} {name}: expired {rec['expiry']}"); continue
        hit = (by_exact.get(SAME_AS[reg]) if reg in SAME_AS else None) or by_name.get((key(name), COUNTRY))             or (by_exact.get("«" + brand(name) + "»") if brand(name) else None)
        if hit:
            row, ds = hit
            reused.append(f"{reg} {name} -> `{row['name']}` ({ds})")
            bodies.setdefault(row["name"], row); body_name = row["name"]
        else:
            addr = clean(rec["address"])
            bodies.setdefault(name, {"name": name, "country": COUNTRY, "registration_no": reg,
                                     "phone": phone(rec["phone"]), "email": rec["email"], "website": "",
                                     "address": f"{addr}, Armenia" if addr else "", "source_url": rec["detail_url"],
                                     "verified_at": ""})
            body_name = name
        accs.append({"ab_code": AB_CODE, "certificate_number": reg, "body_name": body_name,
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": rec["issued"],
                     "expiry_date": rec["expiry"], "proof_url": rec["detail_url"]})
        lines, d = classify(by_reg.get(reg, []))
        for k, v in d.items():
            dropped[k] += v; dropped_bodies[k].add(reg)
        for n, ln in enumerate(lines, 1):
            ps.append({"certificate_number": reg, "line_no": n, **ln, "product_text_en": "", "status": "ACTIVE"})
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
    per = collections.Counter(p["certificate_number"] for p in ps)
    rv = ["# ARMNAB ISO/IEC 17065 - review", "",
          f"Generated by `prepare_certifind_17065.py`{' --exclude' if EXCLUDE else ''} on {today}.", "",
          "## Lines left out", "", "| Reason | Lines | Bodies |", "| --- | --- | --- |"]
    rv += [f"| {r} | {c} | {len(dropped_bodies[r])} |" for r, c in dropped.most_common()]
    rv += ["", "## Bodies dropped", ""] + [f"- {b}" for b in bodies_dropped]
    rv += ["", "## Body rows reused", ""] + ([f"- {r}" for r in reused] or ["None."])
    rv += ["", "## Bilingual pairing failures", "",
           "None attempted: the register is Armenian only, so `product_text_en` is empty."]
    rv += ["", "## Product lines per accreditation", ""] + [f"- {c}: {n}" for c, n in sorted(per.items())]
    rv += ["", "## Schemes", ""] + ([f"- {c}: {n}" for c, n in sch.most_common()] or [
        "None. Every line cites Armenian national documents (government decisions, laws, GOST / ՀՍՏ standards), "
        "kept as text with an industry, as in the TUNAC and TURKAK datasets."])
    rv += ["", "## Lines without a scheme by industry", ""] + [f"- {k}: {v}" for k, v in ind.most_common()]
    rv += ["", "## Most frequent standard_refs on lines without a scheme", ""] + \
          [f"- {r}: {c}" for r, c in no_scheme_refs.most_common(25)]
    (HERE / "armnab_17065_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\n"
          f"Product lines (with scheme): {len(ps)} ({sum(sch.values())})\nDropped lines: {sum(dropped.values())}")


if __name__ == "__main__":
    main()
