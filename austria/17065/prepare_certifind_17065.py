"""Akkreditierung Austria ISO/IEC 17065 scrape (program 929, Produktzertifizierungsstellen) -> CertiFind dataset.

Usage: python prepare_certifind_17065.py [raw json] [dataset dir] [--today YYYY-MM-DD]
Input: raw/aa_17065_raw.json from scrape_at_aa_17065.py: {"bodies": [...], "scopes": [...]}, one scope per
register row (docNr = certified standard / regulation, attr = public attributes, ics = technical fields).

Rows of type N (accredited), C (construction products / CPR), S (national schemes) and B are product lines.
Types E and D are applicable documents (scheme rules, EA/IAF documents): not product lines; their
docNr is attached to the body's lines only through the review.
Scheme, industry and reference tables come from ../../italy/accredia-italy-17065/prepare_certifind_17065.py.
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

AB_CODE = "AA"
STD = "ISO/IEC 17065"
SOURCE_URL = "https://akkreditierung-austria.gv.at/"
BODY_COLUMNS = it.ms.BODY_COLUMNS
ACCREDITATION_COLUMNS = it.ms.ACCREDITATION_COLUMNS
SCOPE_COLUMNS = it.ms.SCOPE_COLUMNS
PS_COLUMNS = it.PS_COLUMNS
LINE_TYPES = {"N", "C", "S", "B"}
DOC_TYPES = {"E": "applicable document (scheme rules, EA/IAF documents)", "D": "applicable document (scheme rules, EA/IAF documents)"}

# Austrian / German-language schemes first, then the shared catalogue (EU regulations, GLOBALG.A.P., IFS, ...).
AT_SCHEMES = [(re.compile(p, re.I), c) for p, c in [
    (r"\bTSI\b|2016/797|Interoperabilit", "Rail Interoperability Directive (EU) 2016/797"),
    (r"445/2011|2019/779|\bECM\b", "ECM Regulation (EU) 2019/779"),
    (r"305/2011|2011/305|Bauprodukt|construction products|\bCPR\b|\bAVCP\b|werkseigene[nr]? Produktionskontrol|\bWPK\b|\bFPC\b", "Construction Products Regulation (EU) 305/2011"),
    (r"2014/33|Aufzüge", "Lifts Directive 2014/33/EU"),
    (r"2014/53|Funkanlagen", "Radio Equipment Directive 2014/53/EU"),
    (r"2014/34|EX-Schutz", "ATEX Directive 2014/34/EU"),
    (r"2014/30|\bEMV\b", "EMC Directive 2014/30/EU"),
    (r"2016/425|Schutzausrüstung", "PPE Regulation (EU) 2016/425"),
    (r"2016/424|Seilbahn", "Cableway Installations Regulation (EU) 2016/424"),
    (r"2018/848|834/2007|Biologisch|Bio-", "EU Organic Regulation (EU) 2018/848"),
    (r"2024/1143|1151/2012|\bg\.U\.|\bg\.g\.A\.|\bg\.t\.S\.|geschützte (Ursprungs|geographische)", "EU Geographical Indications (DOP/IGP/STG)"),
    (r"ETSI EN 319 403|eIDAS|910/2014|Vertrauensdienst", "eIDAS"),
]]
# Austrian national schemes: imported as text (scheme_text) with a sector, no catalogue scheme.
NATIONAL = [(re.compile(p, re.I), name, ind) for p, name, ind in [
    (r"ÖVGW|OEVGW", "ÖVGW Qualitätszeichen", "energy"),
    (r"\bOVE\b|ÖVE|OEVE", "ÖVE Prüfzeichen", "electrical"),
    (r"ÖNORM.{0,20}(Produktprüfzeichen|Zertifizierungsschema)|Zertifizierungsschema [NR]\d\d", "Austrian Standards ÖNORM Mark", ""),
    (r"Tierschutz geprüft", "Tierschutz geprüft", "agriculture"),
    (r"AMA[ -]?(Gütesiegel|Genuss|Biosiegel)", "AMA Gütesiegel", "food"),
    (r"Ohne Gentechnik|Gentechnikfrei", "Ohne Gentechnik", "food"),
    (r"Lebensmittelbuch", "Österreichisches Lebensmittelbuch", "food"),
    (r"QS[- ]Qualit|QS-System|\bQS\b", "QS", "food"),
    (r"MRA1044|MNB", "MNB Assessment Scheme", "professional"),
    (r"Österreichisches Umweltzeichen|Umweltzeichen", "Österreichisches Umweltzeichen", "other_manufacturing"),
]]
de = _load("dakks17065", DB / "germany" / "prepare_certifind_17065.py")
INDUSTRY_DE = [(re.compile(p, re.I), ind) for p, ind in [
    (r"Beton|Zement|Ziegel|Mauer|Dämm|Bau|Fenster|Türen|Dach|Abgas|Kamin|Estrich|Gesteinskörn|Asphalt", "construction"),
    (r"Schweiß|Stahl|Metall|Alumin", "metals"),
    (r"elektr|Kabel|Leuchte|Schalt", "electrical"),
    (r"Lebensmittel|Fleisch|Milch|Wein|Futter", "food"),
    (r"Landwirt|Tier", "agriculture"),
    (r"Holz|Papier|Forst", "wood_paper"),
    (r"Kunststoff|Rohr", "rubber_plastics"),
    (r"Fahrzeug|Bahn|Eisenbahn", "transport_equipment"),
]]
WS = re.compile(r"\s+")


def clean(t):
    return WS.sub(" ", (t or "").replace("\xa0", " ")).strip()


def iso(d):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def scheme_of(text):
    hit = next((c for rx, c in AT_SCHEMES if rx.search(text)), None)
    if hit:
        return hit
    if next((n for rx, n, _ in NATIONAL if rx.search(text)), None):
        return None
    return de.scheme_of(text) or next((c for rx, c in it.SCHEMES if rx.search(text)), None)


def national_of(text):
    return next(((n, i) for rx, n, i in NATIONAL if rx.search(text)), (None, ""))


def industry_of(text):
    return de.industry_of(text) or next((ind for rx, ind in INDUSTRY_DE if rx.search(text)), "")


def known_17021():
    """Austrian 17021 bodies (same AA identification numbers) and every other dataset's bodies by name."""
    ms_ids, by_name = {}, {}
    data = DB.parent / "certifind" / "data"
    for r in csv.DictReader(open(data / "aa-austria" / "bodies.csv", encoding="utf-8-sig", newline="")):
        ms_ids[r["registration_no"]] = r
    for f in sorted(data.glob("*/bodies.csv")):
        if f.parent.name in ("aa-austria", "aa-austria-17065"):
            continue
        try:
            for r in csv.DictReader(open(f, encoding="utf-8-sig", newline="")):
                if {"name", "country", "registration_no"} <= set(r):
                    by_name.setdefault((it.key(r["name"]), r["country"]), (f.parent.name, r))
        except Exception:
            pass
    return ms_ids, by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path, nargs="?", default=HERE / "raw" / "aa_17065_raw.json")
    ap.add_argument("out", type=Path, nargs="?", default=DB.parent / "certifind" / "data" / "aa-austria-17065")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    ms_ids, by_name = known_17021()

    scopes = collections.defaultdict(list)
    for s in raw["scopes"]:
        scopes[s["b"]].append(s)
    review, reused, no_lines = [], [], []
    dropped = collections.defaultdict(list)
    new_schemes = collections.Counter()
    catalogue = {c for _, c in it.SCHEMES}
    bodies, accs, ps = [], [], []
    for b in sorted(raw["bodies"], key=lambda b: b["id"]):
        bid = b["id"]
        con = {t: v for t, v in reversed(b["contacts"])}
        org = b["org"] + [""] * (6 - len(b["org"]))
        country = it.COUNTRY_FIX.get(clean(org[4]), clean(org[4])) or "Austria"
        if country == "AT":
            country = "Austria"
        name = clean(b["name"])
        body = {"name": name, "country": country, "registration_no": bid,
                "phone": clean(con.get("PHONE_BUSINESS", "")), "email": clean(con.get("EMAIL_BUSINESS", "")),
                "website": clean(con.get("WEBSITE_BUSINESS", "") or org[5]).rstrip("/"),
                "address": ", ".join(x for x in (clean(org[1]), clean(f"{org[2]} {org[3]}")) if x),
                "source_url": SOURCE_URL, "verified_at": ""}
        if bid in ms_ids:
            body = dict(ms_ids[bid])
            reused.append(f"{name} ({bid}): same AA number as the 17021 dataset (aa-austria); body row copied, certificate '{bid} (17065)'")
        elif (it.key(name), country) in by_name:
            ds, row = by_name[(it.key(name), country)]
            body = dict(row)
            reused.append(f"{name} ({bid}) -> '{row['name']}' from {ds}")
        cert = f"{bid} (17065)" if bid in ms_ids else bid

        lines = []
        for s in sorted(scopes.get(bid, []), key=lambda s: (s["doc"] or "", s["id"])):
            if s["status"] != "VALID":
                dropped[f"scope status {s['status']}"].append(bid)
                continue
            if s["type"] in DOC_TYPES:
                dropped[DOC_TYPES[s["type"]]].append(bid)
                continue
            if s["type"] not in LINE_TYPES:
                dropped[f"unknown row type {s['type']}"].append(bid)
                continue
            a = s["attr"]
            doc, title = clean(s["doc"]), clean(s["title"])
            rng, sch_t = clean(a.get("field/ range", "")), clean(a.get("certification scheme(s)", ""))
            ics = "; ".join(clean(f[1] or f[2]) for f in s["ics"])
            nb = "; ".join(clean(f[3]) for f in s["ics"] if f[3])
            alltext = " | ".join([doc, title, sch_t, ics, nb])
            scheme = scheme_of(alltext) or ""
            nat, nat_ind = national_of(alltext) if not scheme else (None, "")
            if nat:
                new_schemes[nat] += 1
            prod = rng or title or doc
            lines.append({"scheme": scheme, "industry": "" if scheme else (nat_ind or industry_of(" ".join([title, rng, ics]))),
                          "product_text": prod, "product_text_en": "", "scheme_text": sch_t or (nat or ""),
                          "normative_docs": doc, "standard_refs": it.refs(f"{doc} {title}"), "status": "ACTIVE"})
        if not lines:
            no_lines.append(f"{name} ({bid}): no importable scope row; dropped")
            continue
        bodies.append(body)
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": iso(b["start"]),
                     "expiry_date": "", "proof_url": SOURCE_URL})
        seen = set()
        n = 0
        for l in lines:
            k = (l["scheme"], l["product_text"], l["normative_docs"])
            if k in seen:
                dropped["duplicate line"].append(bid)
                continue
            seen.add(k)
            n += 1
            ps.append({"certificate_number": cert, "line_no": n, **l})

    names = collections.Counter(b["name"] for b in bodies)
    for nm, c in names.items():
        if c > 1:
            review.append(f"{nm}: {c} AA identification numbers; separate body rows would clash on name")
    it.write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda r: r["name"].casefold()))
    it.write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    it.write(args.out / "scopes.csv", SCOPE_COLUMNS, [])
    it.write(args.out / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    unmatched = collections.Counter(r for p in ps if not p["scheme"] for r in p["standard_refs"].split(";") if r)
    no_scheme_docs = collections.Counter(p["scheme_text"][:80] for p in ps if not p["scheme"])
    with open(HERE / "aa_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Akkreditierung Austria ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, "
                 f"{len(accs)} accreditations, {len(ps)} product lines ({with_scheme} with a scheme).\n\n")
        fh.write("## Lines left out (reason: lines, bodies)\n\n")
        for reason, regs in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
            fh.write(f"- {reason}: {len(regs)} lines, {len(set(regs))} bodies\n")
        fh.write("\n## Bodies dropped\n\n" + "".join(f"- {l}\n" for l in no_lines))
        fh.write("\n## Body rows reused from other datasets\n\n" + "".join(f"- {l}\n" for l in reused))
        fh.write("\n## Notes\n\n" + "".join(f"- {l}\n" for l in review))
        fh.write("\n## Bilingual pairing failures\n\nNone: register text is German only; product_text_en left empty.\n")
        fh.write("\n## Austrian national schemes kept as text (no catalogue scheme; lines)\n\n")
        fh.writelines(f"- {s}: {n}\n" for s, n in new_schemes.most_common())
        fh.write("\n## Most frequent standard_refs on lines without a scheme\n\n")
        fh.writelines(f"- {r}: {n}\n" for r, n in unmatched.most_common(40))
        fh.write("\n## Most frequent certification-scheme texts on lines without a scheme\n\n")
        fh.writelines(f"- {r}: {n}\n" for r, n in no_scheme_docs.most_common(30))
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nProduct lines: {len(ps)} (with scheme {with_scheme})\n"
          f"Dropped lines: {sum(len(v) for v in dropped.values())}")


if __name__ == "__main__":
    main()
