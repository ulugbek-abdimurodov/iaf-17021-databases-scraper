"""HAA (Croatia) ISO/IEC 17065 scrape -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py [scrape folder] [dataset dir] [--today YYYY-MM-DD]
Input: haa_prod_data/ written by ../17021/haa_scraper.py --scheme "certifikaciju proizvoda" (bodies.json and
<folder>/document_text.txt, the register's text copy of certificate + annex).

The annex text is a flattened bilingual table, so it is read per scope section: each
"Certifikacijska shema utemeljena na / Certification scheme based on:" starts a section; the line(s) before it
name the area, the text after it the legal/scheme basis, "Dokumenti u primjeni / Applicable documents" the CB's
own programme. Every standard / regulation reference in a section becomes one product line (one line for a
section without references). Annexes without that marker are read as one section.
"""
import argparse, collections, csv, importlib.util, json, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent  # .../CertiFind/database


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


it = _load("accredia_17065", DB / "italy" / "accredia-italy-17065" / "prepare_certifind_17065.py")

AB_CODE = "HAA"
STD = "ISO/IEC 17065"
COUNTRY = "Croatia"
REGISTER_URL = "https://akreditacija.gov.hr/frontend/registar-akreditacija"
SPLIT = re.compile(r"Certifikacijsk\w* shem\w* utemeljen\w* na:?\s*(?:/\s*)?Certification scheme based on:?", re.I)
APPLICABLE = re.compile(r"Dokumenti u primjeni:?\s*(?:/\s*)?(?:Applicable documents:?)?", re.I)
NOISE = re.compile(r"^(PODRUČJE AKREDITACIJE|SCOPE OF ACCREDITATION|Prilog|Annex|Datum|Zamjenjuje|stranica|HAA-|\d{4}$|\d{4}-\d{2}-\d{2})", re.I)
REF = re.compile(
    r"\b(?:HRN\s+)?(?:EN\s+)?(?:ISO/IEC|ISO/TS|ISO|IEC|EN|CEN/TS|ETSI EN|ETSI TS)\s*\d{3,5}(?:-\d{1,3})*"
    r"|\b\d{2,4}/\d{1,4}/(?:EU|EC|EZ|EEZ|EEC)\b"
    r"|\((?:EU|EZ|EC)\)\s*(?:br\.|No\.?)?\s*\d{2,4}/\d{2,4}\b"
    r"|\b(?:GLOBALG\.?A\.?P\.?|IFS [A-Z][a-z]+|BRCGS?|FSC|PEFC|ISCC(?: EU| PLUS)?|MSC|RSPO|Rainforest Alliance|Fairtrade"
    r"|Halal|Kosher|GMP\+|Friend of the Sea|2BSvs|REDcert\w*)\b", re.I)
# Croatian-specific schemes, then the shared catalogue table.
HR_SCHEMES = [(re.compile(p, re.I), c) for p, c in [
    # Croatian national schemes (mine action equipment, Hrvatska kvaliteta) get no code: text + industry only.
    (r"2014/90|\bMED\b|marine equipment|pomorsk\w* oprem", "Marine Equipment Directive 2014/90/EU"),
    (r"2013/53|\bRCD\b|recreational craft|rekreacijsk", "Recreational Craft Directive 2013/53/EU"),
    (r"2017/625|2018/848|834/2007|ekološk|organic", "EU Organic Regulation (EU) 2018/848"),
    (r"1151/2012|2024/1143|oznak\w* izvornosti|zemljopisn|designation of origin|geographical indication", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"2016/797|interoperab", "Rail Interoperability Directive (EU) 2016/797"),
]]
WS = re.compile(r"\s+")


def local_industry(text):
    """Fallback for lines the shared INDUSTRY_WORDS miss (national mine-action scheme, IECEx)."""
    if re.search(r"protuminsk|mine action|detekciju mina", text, re.I):
        return "machinery"
    if re.search(r"IECEx|explosive atmosphere|eksplozivn", text, re.I):
        return "electrical"
    return ""


def ws(t):
    return WS.sub(" ", t or "").strip()


def english(head):
    """'Hrvatski tekst / English text' -> English half when there is one."""
    parts = [p.strip() for p in re.split(r"\s/\s|/(?=[A-Z])", head) if p.strip()]
    return parts[-1] if len(parts) > 1 else head


def norm_ref(r):
    r = ws(r)
    r = re.sub(r"^HRN\s+", "", r)
    m = re.search(r"(\d{2,4})/(\d{1,4})", r)
    if m and re.search(r"EU|EC|EZ|EEZ|EEC", r) and not re.search(r"ISO|IEC|EN ", r):
        return f"{m.group(1)}/{m.group(2)}"
    return r


def scheme_of(text):
    return next((c for rx, c in HR_SCHEMES if rx.search(text)), None) or next((c for rx, c in it.SCHEMES if rx.search(text)), "")


def sections(text):
    i = text.find("PODRUČJE AKREDITACIJE")
    body = text[i:] if i >= 0 else text
    parts = SPLIT.split(body)
    out = []
    for k in range(1, len(parts)):
        prev = [ws(x) for x in parts[k - 1].splitlines()]
        prev = [x for x in prev if x and not NOISE.match(x)]
        head = " / ".join(prev[-2:])[-200:]
        p = parts[k]
        j = APPLICABLE.search(p)
        based = ws(p[: j.start()] if j else p[:400])[:400]
        app = ws(re.split(r"\n\s*(?:Br\.|Redni)", p[j.end(): j.end() + 400])[0])[:200] if j else ""
        out.append((head, based, app, p))
    if not out:  # no "scheme based on" marker: whole scope as one section
        lines = [ws(x) for x in body.splitlines()]
        lines = [x for x in lines if x and not NOISE.match(x)]
        out.append((" / ".join(lines[:2])[:200], " ".join(lines[2:6])[:400], "", body))
    return out


def phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("385"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    if len(digits) < 7:
        return ""
    area = 1 if digits.startswith("1") else 2
    return f"+385 {digits[:area]} {digits[area:]}"


def iso(d):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


MS_ALIASES = {}  # certificate number -> body name in data/haa-croatia/bodies.csv (filled in main from MS_NAME_HINTS)
MS_NAME_HINTS = {"Bureau Veritas Croatia": "Bureau Veritas Croatia d.o.o.",
                 "Hrvatski registar brodova": "Croatian Register of Shipping"}


def known_bodies():
    by_name = {}
    for f in sorted(DB.rglob("bodies.csv")):
        if HERE in f.resolve().parents:
            continue
        try:
            for r in csv.DictReader(open(f, encoding="utf-8-sig", newline="")):
                if {"name", "country", "registration_no"} <= set(r):
                    by_name.setdefault((it.key(r["name"]), r["country"]), (f.parent.name, r))
        except Exception:
            pass
    return by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path, nargs="?", default=HERE / "haa_prod_data")
    ap.add_argument("out", type=Path, nargs="?", default=HERE / "data" / "haa-croatia-17065")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    records = json.loads((args.data / "bodies.json").read_text(encoding="utf-8"))
    by_name = known_bodies()
    # Same legal entities as the HAA management-system dataset: reuse those rows exactly.
    ms_rows = {r["name"]: r for r in csv.DictReader(open(DB.parent / "certifind" / "data" / "haa-croatia" / "bodies.csv",
                                                         encoding="utf-8-sig", newline=""))}
    catalogue = {c for _, c in it.SCHEMES}
    review, reused = [], []
    new_schemes, dropped = collections.Counter(), collections.defaultdict(list)
    bodies, accs, ps = {}, [], []
    for rec in sorted(records, key=lambda r: r["BrojPotvrde"]):
        if "17065" not in (rec.get("Norma") or ""):
            continue
        cert = str(rec["BrojPotvrde"])
        tp = args.data / rec["folder"] / "document_text.txt"
        text = tp.read_text(encoding="utf-8") if tp.exists() else ""
        name = ws(rec["AkreditornoTijelo"])
        for hint, ms_prefix in MS_NAME_HINTS.items():
            if name.startswith(hint):
                MS_ALIASES[cert] = next(n for n in ms_rows if n.startswith(ms_prefix))
        website = ws(rec.get("WebAdresa", "")).strip("_")
        if website and not website.startswith("http"):
            website = "http://" + website
        body = {"name": name, "country": COUNTRY, "registration_no": "", "phone": phone(rec.get("Telefon", "")), "email": "",
                "website": website, "address": ", ".join(x for x in (ws(rec.get("UlicaKucniBroj", "")), ws(rec.get("Mjesto", ""))) if x),
                "source_url": REGISTER_URL, "verified_at": ""}
        hit = (MS_ALIASES.get(cert) and ("haa-croatia", ms_rows[MS_ALIASES[cert]])) \
            or by_name.get((it.key(name), COUNTRY)) or by_name.get((it.key(name.split(",")[0]), COUNTRY))
        if hit:
            body = dict(hit[1])
            reused.append(f"{name} ({cert}) -> '{body['name']}' from {hit[0]}")
        # label and date may sit on separate lines; fall back to the start of the current period
        DT = r"(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})"
        ini = (re.search(r"Prva akreditacija:?\s*(?:Initial accreditation:?\s*)?" + DT, text)
               or re.search(r"Akreditacija vrijedi od:?\s*(?:Accreditation valid from:?\s*)?" + DT, text))
        if ini and "." in ini.group(1):
            d_, m_, y_ = ini.group(1).split(".")
            ini_date = f"{y_}-{int(m_):02d}-{int(d_):02d}"
        else:
            ini_date = ini.group(1) if ini else ""
        if not text:
            review.append(f"{cert} {name}: no document text; one line from the register 'Podrucje' field")
        lines = []
        for head, based, app, chunk in (sections(text) if text else [(ws(rec.get("Podrucje", "")), "", "", "")]):
            area = english(head) or ws(rec.get("Podrucje", ""))
            refs = list(dict.fromkeys(norm_ref(r) for r in REF.findall(chunk)))
            sch = scheme_of(" ".join([head, based, " ".join(refs)]))
            for r in refs or [""]:
                s = scheme_of(r) if r and not sch else sch
                if s and s not in catalogue:
                    new_schemes[s] += 1
                lines.append({"scheme": s or "", "industry": "" if s else (it.industry_of(f"{area} {based}") or local_industry(f"{area} {based}")),
                              "product_text": area, "product_text_en": "", "scheme_text": based[:300],
                              "normative_docs": "; ".join(x for x in (r, app) if x)[:400],
                              "standard_refs": it.refs(r) if r else "", "status": "ACTIVE"})
        if body["name"] not in bodies:
            bodies[body["name"]] = body
        else:
            review.append(f"{body['name']}: second accreditation {cert}")
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"], "accreditation_standard": STD,
                     "status": "ACTIVE", "issue_date": ini_date, "expiry_date": iso(rec.get("DatumIsteka", "")),
                     "proof_url": REGISTER_URL})
        seen, n = set(), 0
        for l in lines:
            k = (l["scheme"], l["product_text"], l["normative_docs"])
            if k in seen:
                dropped["duplicate line"].append(cert)
                continue
            seen.add(k)
            n += 1
            ps.append({"certificate_number": cert, "line_no": n, **l})

    it.write(args.out / "bodies.csv", it.ms.BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    it.write(args.out / "accreditations.csv", it.ms.ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    it.write(args.out / "scopes.csv", it.ms.SCOPE_COLUMNS, [])
    it.write(args.out / "product_scopes.csv", it.PS_COLUMNS, ps)
    with_scheme = sum(1 for p in ps if p["scheme"])
    unmatched = collections.Counter(p["normative_docs"].split(";")[0] for p in ps if not p["scheme"] and p["normative_docs"])
    with open(HERE / "haa_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# HAA ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, {len(accs)} accreditations, "
                 f"{len(ps)} product lines ({with_scheme} with a scheme).\n\n")
        fh.write("Lines are read per annex section (one per cited standard/regulation); product rows inside the flattened "
                 "annex tables are not split further.\n\n## Lines left out (reason: lines, bodies)\n\n")
        fh.writelines(f"- {r}: {len(v)} lines, {len(set(v))} bodies\n" for r, v in dropped.items())
        fh.write("\n## Bodies dropped\n\n\n## Body rows reused from other datasets\n\n" + "".join(f"- {l}\n" for l in reused))
        fh.write("\n## Notes\n\n" + "".join(f"- {l}\n" for l in review))
        fh.write("\n## Bilingual pairing failures\n\nNot paired: the English half of each section heading is used as product_text.\n")
        fh.write("\n## New scheme codes (lines)\n\n" + "".join(f"- {s}: {n}\n" for s, n in new_schemes.most_common()))
        fh.write("\n## Most frequent standard_refs on lines without a scheme\n\n" + "".join(f"- {r}: {n}\n" for r, n in unmatched.most_common(40)))
    (HERE / "new_schemes.json").write_text(json.dumps(sorted(new_schemes), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nProduct lines: {len(ps)} (with scheme {with_scheme})\n"
          f"Dropped lines: {sum(len(v) for v in dropped.values())}")


if __name__ == "__main__":
    main()
