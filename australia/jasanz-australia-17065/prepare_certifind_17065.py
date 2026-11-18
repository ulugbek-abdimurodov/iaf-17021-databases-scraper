"""JAS-ANZ ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py [raw json] [dataset dir] [--today YYYY-MM-DD]
Input: raw/jasanz_17065_raw.json written by scrape_au_jasanz_17065.py (one record per CAB holding a
"Product Certification" program). The register is structured: every certification standard listed under a
scheme is one product line (name = normative doc, description = product text). No PDFs.
"""
import argparse, collections, csv, json, re
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent  # .../CertiFind/database
AB_CODE = "JASANZ"
STD = "ISO/IEC 17065"
SOURCE_URL = "https://register.jasanz.org/accredited-bodies"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                         "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en",
              "scheme_text", "normative_docs", "standard_refs", "status"]
COUNTRY_FIX = {"Taiwan  Province of China": "Taiwan", "Taiwan Province of China": "Taiwan", "Korea,Republic of": "South Korea",
               "Korea, Republic of": "South Korea", "Korea": "South Korea", "Viet Nam": "Vietnam", "Türkiye": "Turkey",
               "Czech Republic": "Czechia", "UAE": "United Arab Emirates"}

# (regex on "scheme name | standard name", canonical scheme code). First match wins.
SCHEMES = [(re.compile(p, re.I), c) for p, c in [
    (r"GLOBAL ?G\.?A\.?P.{0,40}Chain of Custody|GLOBALGAP Chain", "GLOBALG.A.P. Chain of Custody"),
    (r"GLOBAL ?G\.?A\.?P|NZ ?GAP", "GLOBALG.A.P. IFA"),
    (r"BRC\w*.{0,60}Packaging", "BRCGS Packaging Materials"),
    (r"BRC\w*.{0,60}(Storage and Distribution)", "BRCGS Storage and Distribution"),
    (r"BRC\w*.{0,60}Agents? and Brokers", "BRCGS Agents and Brokers"),
    (r"BRC\w*.{0,60}Consumer Products", "BRCGS Consumer Products"),
    (r"BRC\w*|Brand Reputation through Compliance", "BRCGS Food Safety"),
    (r"IFS Wholesale", "IFS Wholesale"), (r"IFS Logistics", "IFS Logistics"), (r"IFS Broker", "IFS Broker"),
    (r"IFS (HPC|Household)", "IFS HPC"), (r"IFS PAC ?secure", "IFS PACsecure"),
    (r"IFS Food|International Featured Standards", "IFS Food"),
    (r"\bSQF\b", "SQF"),
    (r"PEFC", "PEFC Chain of Custody"),
    (r"LEAF Marque", "LEAF Marque"),
    (r"ISCC[ -]?PLUS", "ISCC PLUS"), (r"ISCC[ -]?EU", "ISCC EU"),
    (r"\b3834\b", "ISO 3834"), (r"15085", "EN 15085-2"),
    (r"\bISO 22005\b", "ISO 22005"),
    (r"Responsible Wood", "PEFC Chain of Custody"),  # Australian PEFC member scheme
]]
# Sector of a scheme-less line: from the JAS-ANZ scheme name when it is sector-specific, else from the
# product text (English keyword table of the ACCREDIA converter).
SCHEME_INDUSTRY = [(re.compile(p, re.I), i) for p, i in [
    (r"Electrical|EESS|ANZEx|Hazardous Area|Telecommunication|Pro-Switch", "electrical"),
    (r"WaterMark|CodeMark|Wastewater|Septic|Rainwater|FireMark|Post Tensioning|ICC Evaluation|IAPMO", "construction"),
    (r"Gas (Safety|Product|Appliance)|GasMark|AGA|Gas Cylinder", "machinery"),
    (r"ACRS|Structural Steel|Steelwork", "metals"),
    (r"Wood Packaging|EWPAA|Wood", "wood_paper"),
    (r"Organic|Freshcare|Farm Assurance|Synlait|Fonterra|GAP", "agriculture"),
    (r"Halal|HACCP|Food", "food"),
    (r"Disability|Human Services|Community Industry|WANADA|Approved Quality Auditors|Reproductive|Pharmacy|"
     r"Designated Audit Agency|Aged Care|Health", "health"),
    (r"Paint", "chemicals"),
    (r"Technical Infrastructure|Rail", "transport_equipment"),
    (r"carbon", "energy"),
    (r"Panel of Assessors", "professional"),
]]
_it = None


def industry_of(scheme_name, product):
    global _it
    hit = next((i for rx, i in SCHEME_INDUSTRY if rx.search(scheme_name)), None)
    if hit:
        return hit
    if _it is None:
        import importlib.util, sys
        path = DB / "italy" / "accredia-italy-17065" / "prepare_certifind_17065.py"
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location("accredia17065", path)
        _it = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_it)
    return next((i for rx, i in _it.INDUSTRY_WORDS if rx.search(product)), "")
CATALOGUE = {"GLOBALG.A.P. Chain of Custody", "GLOBALG.A.P. IFA", "BRCGS Packaging Materials", "BRCGS Storage and Distribution",
             "BRCGS Agents and Brokers", "BRCGS Consumer Products", "BRCGS Food Safety", "IFS Wholesale", "IFS Logistics",
             "IFS Broker", "IFS HPC", "IFS PACsecure", "IFS Food", "SQF", "PEFC Chain of Custody", "LEAF Marque", "ISCC PLUS",
             "ISCC EU", "ISO 3834", "EN 15085-2", "ISO 22005"}
REF = re.compile(r"\b((?:AS/NZS|AS|NZS|UNI|BS|DIN|NF)\s+)*(?:(EN)\s+)?(ISO/IEC|ISO/TS|ISO|IEC|CEN/TS|EN)\s*(\d{3,5})((?:-\d{1,3})?)")
ASNZS = re.compile(r"\b(AS/NZS|AS|NZS)\s*(\d{1,5}(?:\.\d+)*)((?:-\d{1,3}(?!\d))?)")
WS = re.compile(r"\s+")
BOILER = re.compile(r"^(N/?A|-|Refer to .*scheme.*|See (attached|scope).*)$", re.I)


def clean(t):
    return WS.sub(" ", (t or "").replace("\xa0", " ")).strip()


def key(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(pty|ltd|limited|inc|llc|co|trading as)\b", "", (s or "").lower()))


DIAL = {"Australia": "61", "New Zealand": "64"}


def norm_phone(raw, country, review, name):
    t = clean(raw)
    if not t:
        return ""
    if t.startswith("+"):
        return "+" + clean(t[1:])
    digits = re.sub(r"\D", "", t)
    if re.match(r"^(0800|0508|1800|1300)", digits):
        review.append(f"{name}: toll-free phone '{t}' not reachable from abroad; left empty")
        return ""
    if country in DIAL and digits.startswith("0"):
        return f"+{DIAL[country]} " + clean(re.sub(r"^0\s*", "", t))
    review.append(f"{name}: phone '{t}' could not be made international; left empty")
    return ""


def norm_web(raw):
    t = clean(raw)
    return t if not t or re.match(r"https?://", t, re.I) else "https://" + t


def iso(d):
    d = clean(d)
    for f in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(d[:19] if "T" in d else d, f).date().isoformat()
        except ValueError:
            pass
    return ""


def refs(t):
    out = []
    for m in ASNZS.finditer(t):
        r = f"{m.group(1)} {m.group(2)}{m.group(3)}"
        if r not in out:
            out.append(r)
    for m in REF.finditer(ASNZS.sub(" ", t)):
        r = f"{m.group(3)} {m.group(4)}{m.group(5)}"
        if r not in out:
            out.append(r)
    return ";".join(out)


def scheme_code(name):
    s = clean(re.sub(r"\s*(Certification )?Scheme$", "", clean(name), flags=re.I))
    return next((c for rx, c in SCHEMES if rx.search(name)), s), s


def load_bodies(out):
    by_reg, by_name = {}, {}
    for f in sorted((DB.parent / "certifind" / "data").glob("*/bodies.csv")):
        if out.resolve() in f.resolve().parents or f.parent.resolve() == out.resolve():
            continue
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8-sig", newline="")))
        except Exception:
            continue
        for r in rows:
            if "name" not in r or "country" not in r:
                continue
            ds = f.parent.name
            by_name.setdefault((key(r["name"]), r["country"]), (ds, r))
            if ds == "jasanz-australia":
                by_reg[r["registration_no"]] = (ds, r)
    return by_reg, by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path, nargs="?", default=HERE / "raw" / "jasanz_17065_raw.json")
    ap.add_argument("out", type=Path, nargs="?", default=DB.parent / "certifind" / "data" / "jasanz-australia-17065")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    by_reg, by_name = load_bodies(args.out)
    # certificate numbers are unique per AB: suffix the ones the 17021 dataset already uses
    ms_acc = args.out.parent / "jasanz-australia" / "accreditations.csv"
    ms_certs = {r["certificate_number"] for r in csv.DictReader(open(ms_acc, encoding="utf-8-sig", newline=""))}

    review, reused, no_lines, new_schemes = [], [], [], collections.Counter()
    dropped = collections.defaultdict(list)
    bodies, accs, ps = {}, [], []
    for rec in raw:
        nums = [a[0] for a in rec["acc"] if a and a[0]]
        z = [n for n in nums if n.upper().startswith("Z")]
        reg = z[0] if z else next((n for n in nums if not n.upper().startswith("M")), nums[0] if nums else str(rec["id"]))
        if len(z) > 1:
            review.append(f"{rec['name']}: several product accreditation numbers {', '.join(z)}; {reg} used")
        a = rec["addr"] + [""] * (7 - len(rec["addr"])) if rec["addr"] else [""] * 7
        country = COUNTRY_FIX.get(clean(a[6]), clean(a[6]))
        city = " ".join(x for x in (clean(a[3]).title() if clean(a[3]).isupper() else clean(a[3]), clean(a[4]), clean(a[5])) if x)
        parsed = {"name": clean(rec["name"]), "country": country, "registration_no": reg,
                  "phone": norm_phone(rec["phone"], country, review, clean(rec["name"])),
                  "email": clean(rec["email"]), "website": norm_web(rec["web"]),
                  "address": ", ".join(x for x in [clean(a[0]), clean(a[1]), clean(a[2]), city] if x),
                  "source_url": SOURCE_URL, "verified_at": ""}
        m_hit = next((by_reg[n] for n in nums if n in by_reg), None)
        if m_hit:
            body = dict(m_hit[1])
            reused.append(f"{body['name']} ({reg}) from {m_hit[0]} (registration {body['registration_no']})")
        elif (key(parsed["name"]), country) in by_name:
            ds, row = by_name[(key(parsed["name"]), country)]
            body = dict(row)
            reused.append(f"{parsed['name']} ({reg}) -> '{row['name']}' from {ds}")
        else:
            body = parsed
        if not body["country"]:
            review.append(f"{body['name']} ({reg}): no country in the register")

        lines = []
        for s in rec["schemes"]:
            code, short = scheme_code(s["s"])
            acc_docs = [x for x in s.get("acc") or [] if "17065" not in x and "MD4" not in x]
            for name, desc in s["c"]:
                name, desc = clean(name), clean(desc)
                if not name and not desc:
                    drop(dropped, "empty line", reg)
                    continue
                if BOILER.match(desc or name):
                    drop(dropped, "boilerplate / placeholder", reg)
                    continue
                sc = next((c for rx, c in SCHEMES if rx.search(f"{s['s']} | {name}")), code)
                if sc not in CATALOGUE:
                    new_schemes[sc] += 1
                    sc = ""
                ind = "" if sc else industry_of(s["s"], f"{desc} {name}")
                lines.append({"scheme": sc, "industry": ind, "product_text": desc or name, "product_text_en": "",
                              "scheme_text": clean(s["s"]), "normative_docs": "; ".join([name] + acc_docs) if name else "; ".join(acc_docs),
                              "standard_refs": refs(f"{name} {desc}"), "status": "ACTIVE"})
        if not lines:
            no_lines.append(f"{body['name']} ({reg}): no importable line; dropped")
            continue
        if body["name"] in bodies:
            review.append(f"{body['name']}: second CAB record {reg}; lines merged into the first")
            cert = next(x["certificate_number"] for x in accs if x["body_name"] == body["name"])
        else:
            bodies[body["name"]] = body
            cert = f"{reg} (17065)" if reg in ms_certs else reg
            accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                         "accreditation_standard": STD, "status": "ACTIVE", "issue_date": iso(rec.get("issued") or ""),
                         "expiry_date": iso(rec.get("expiry") or ""), "proof_url": SOURCE_URL})
        start = sum(1 for p in ps if p["certificate_number"] == cert)
        seen = set()
        for l in lines:
            k = (l["scheme"], l["product_text"], l["normative_docs"])
            if k in seen:
                drop(dropped, "duplicate line within the same scheme", reg)
                continue
            seen.add(k)
            start += 1
            ps.append({"certificate_number": cert, "line_no": start, **l})

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS, [])
    write(args.out / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    unmatched = collections.Counter(r for p in ps if not p["scheme"] for r in p["standard_refs"].split(";") if r)
    with open(HERE / "jasanz_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# JAS-ANZ ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, "
                 f"{len(accs)} accreditations, {len(ps)} product lines ({with_scheme} with a scheme; "
                 f"{sum(1 for p in ps if p['industry'])} scheme-less lines with a sector).\n\n")
        fh.write("## Lines left out (reason: lines, bodies)\n\n")
        for reason, regs in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            fh.write(f"- {reason}: {len(regs)} lines, {len(set(regs))} bodies\n")
        fh.write("\n## Bodies dropped\n\n" + "".join(f"- {l}\n" for l in no_lines))
        fh.write("\n## Body rows reused from other datasets\n\n" + "".join(f"- {l}\n" for l in reused))
        fh.write("\n## Notes\n\n" + "".join(f"- {l}\n" for l in review))
        fh.write("\n## Bilingual pairing failures\n\nNone: the register is English only.\n")
        fh.write("\n## JAS-ANZ schemes kept as scheme_text only (national or single-certifier; lines)\n\n")
        fh.writelines(f"- {s}: {n}\n" for s, n in new_schemes.most_common())
        fh.write("\n## Most frequent standard_refs on lines of new schemes\n\n")
        fh.writelines(f"- {r}: {n}\n" for r, n in unmatched.most_common(40))
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nProduct lines: {len(ps)} (with scheme {with_scheme})\n"
          f"Dropped lines: {sum(len(v) for v in dropped.values())}")


def drop(dropped, reason, reg):
    dropped[reason].append(reg)


def write(path, columns, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
