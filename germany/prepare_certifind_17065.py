"""DAkkS (Germany) ISO/IEC 17065 register (D-ZE) -> CertiFind dataset data/dakks-germany-17065/.

Input: dakks_ZE/ from dakks_17065_scraper.py (accreditations.csv, bodies.csv, scope_lines.csv).
Rules: .claude/skills/add-country-17065/SKILL.md in the certifind repo.

    python prepare_certifind_17065.py dakks_ZE ../../certifind/data/dakks-germany-17065 --today 2026-11-17
"""
import argparse, collections, csv, importlib.util, json, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


it = _load("accredia17065", DB / "italy" / "accredia-italy-17065" / "prepare_certifind_17065.py")
clean, refs = it.clean, it.refs

AB_CODE = "DAkkS"
STD = "ISO/IEC 17065"
REGISTER = "https://www.dakks.de/de/akkreditierte-stelle.html?id="
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
PS_COLUMNS = it.PS_COLUMNS
COUNTRIES = {"Deutschland": "Germany", "Belgien": "Belgium", "Luxemburg": "Luxembourg", "Peru": "Peru",
             "China": "China", "Guatemala": "Guatemala", "Ghana": "Ghana", "Georgien": "Georgia",
             "Armenien": "Armenia", "Indien": "India", "Bolivien": "Bolivia", "Tschechische Republik": "Czechia",
             "Liechtenstein": "Liechtenstein", "Jordanien": "Jordan", "Cote d'Ivoire": "Côte d’Ivoire",
             "Österreich": "Austria", "Tansania": "Tanzania", "Uruguay": "Uruguay"}

# German-register schemes first (EU decisions on construction products are CPR), then the shared table.
DE_SCHEMES = [(re.compile(p, re.I), c) for p, c in [
    (r"Leistungsbest|Bauprodukte \(System|Bewertung und Überprüfung der Leistung|"
     r"assessment and verification of constancy", "Construction Products Regulation (EU) 305/2011"),
    (r"Öko-?(Basis)?[- ]?Verordnung|ökologische[nr]? (Landbau|Produktion)|organic production", "EU Organic Regulation (EU) 2018/848"),
    (r"geschützte[nr]? (Ursprungsbezeichnung|geografische)|g\.U\.|g\.g\.A\.", "EU Geographical Indications (DOP/IGP/STG)"),
]] + [(re.compile(p, re.I), c) for p, c in it.EU_SCHEMES] + [
    # CPR assessment decisions (1995/467/EG, 2011/19/EU ...) and European Assessment Documents, after the
    # directives; boats, RoHS, ecodesign and LVD are not CPR
    (re.compile(r"\b(?!2013/53|2011/65|2009/125|2014/35|2012/19)(19|20)\d\d/\d{2,3}/E[GU]\b|\bEAD \d{6}|\bETAG\b"),
     "Construction Products Regulation (EU) 305/2011"),
] + [(re.compile(p, re.I if i else 0), c) for p, c, i in [
    (r"GLOBAL ?G\.?A\.?P\.?,? *(Chain of Custody|CoC)", "GLOBALG.A.P. Chain of Custody", 1),
    (r"GLOBAL ?G\.?A\.?P", "GLOBALG.A.P. IFA", 1),
    (r"BRC\w*.{0,40}Packaging", "BRCGS Packaging Materials", 1),
    (r"BRC\w*.{0,40}Storage", "BRCGS Storage and Distribution", 1),
    (r"BRC\w*.{0,40}Agents", "BRCGS Agents and Brokers", 1),
    (r"BRC\w*.{0,40}Consumer", "BRCGS Consumer Products", 1),
    (r"BRC\w*.{0,40}Food|BRC Global Standard (for )?Food", "BRCGS Food Safety", 1),
    (r"IFS Wholesale", "IFS Wholesale", 1), (r"IFS Logistic", "IFS Logistics", 1), (r"IFS Broker", "IFS Broker", 1),
    (r"IFS (HPC|Household)", "IFS HPC", 1), (r"IFS PAC", "IFS PACsecure", 1), (r"IFS Food", "IFS Food", 1),
    (r"ISCC[ -]?PLUS", "ISCC PLUS", 1), (r"ISCC", "ISCC EU", 1),
    (r"PEFC", "PEFC Chain of Custody", 0), (r"\bFSC\b", "FSC Chain of Custody", 0),
    (r"\bMSC\b|Marine Stewardship", "MSC Chain of Custody", 0),
    (r"910/2014|eIDAS|ETSI EN 319", "eIDAS", 1), (r"Europrivacy", "Europrivacy", 1),
    (r"15408|Common Criteria", "Common Criteria (ISO/IEC 15408)", 1),
    (r"62443", "IEC 62443", 0), (r"61508", "IEC 61508", 0), (r"26262", "ISO 26262", 0),
    (r"5012[689]", "EN 50126 / 50128 / 50129", 0),
    (r"61400|IECRE", "IEC 61400-22 / IECRE", 0),
    (r"61215|61730", "IEC 61215 / IEC 61730", 0),
    (r"(?<!Solar )Keymark", "CEN Keymark", 1),
    (r"15085", "EN 15085-2", 0), (r"3834", "ISO 3834", 0), (r"22005", "ISO 22005", 0),
]]

# German sector words first; the Italian/English table catches the rest.
DE_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"Hotel|Gastronom|Tourism|Beherberg", "tourism"),
    (r"Krankenh|Medizin|Pflege|Gesundheit|Arzneimittel", "health"),
    (r"Schul|Bildung|Weiterbildung|Behörde|öffentliche Verwaltung", "public_education"),
    (r"Informationssicherheit|IT-Sicherheit|Datenschutz|Cloud|Software|Rechenzentr|BSI|digital", "ict"),
    (r"Kosmeti|Chemik|Reinigungs|Farbe|Lack|Klebstoff|Biozid|Düngemittel", "chemicals"),
    (r"Kunststoff|Gummi|Elastomer|Verpackung|Folie", "rubber_plastics"),
    (r"Schienenfahrzeug|Eisenbahn|Bahn|Fahrzeug|Kraftfahr|Automotive|Luftfahrt|Schiff", "transport_equipment"),
    (r"Schweiß|Stahlbau|Stahl|Metall|Aluminium|Betonstahl|Korrosionsschutz|Feuerverzink", "metals"),
    (r"Maschine|Aufzug|Druckgerät|Kran|Hebe|Flurförder|Traktor|Landmaschin|Pumpe|Armatur", "machinery"),
    (r"elektr|Elektronik|Leuchte|Kabel|Schaltanlag|Netzanschluss|Netzintegration|Erzeugungseinheit|"
     r"Wechselrichter|VDE|Brandmelde|Rauchwarnmelder|Sicherheitstechnik|Alarm", "electrical"),
    (r"Bauprodukt|Beton|Zement|Mörtel|Gesteinskörn|Mauer|Ziegel|Dämm|Fenster|Tür|Tore|Dach|Estrich|Asphalt|"
     r"Bauunternehm|Brandschutz|Schornst|Abgasanlag|Holzbau|Trinkwasser|Gips|Glas|Bodenbel|Fassade", "construction"),
    (r"Textil|Bekleidung|Schuh|Leder", "textiles"),
    (r"Windenergie|Wind turbine|Photovolt|Solar|Biogas|Biomethan|Wasserstoff|Brennstoff|Energie|Biokraftstoff|"
     r"Treibhausgas|Heizöl|Pellet|Kraftwerk", "energy"),
    (r"Holz|Papier|Druck|Forst", "wood_paper"),
    (r"Recycl|Abfall|Entsorgung|Spielzeug|Möbel|Sekundärrohstoff", "other_manufacturing"),
    (r"Lebensmittel|Futtermittel|Milch|Fleisch|Eier|Getränk|Wein|Bier|Obst|Gemüse|Kartoffel|Zucker|Kaffee|Kakao|"
     r"Fisch", "food"),
    (r"Landwirt|Tierhalt|Aquakultur|Erzeug(er|ung) .*Hersteller|Anbau|Pflanz|Saatgut", "agriculture"),
    (r"Logistik|Transport|Paketdienst|Kurier|Handel|Lager", "trade_logistics"),
    (r"Dienstleist|Sicherheitsdienst|Präqualifi|Beratung", "professional"),
]]

DROP_VALUE = re.compile(
    r"Zertifizierungen von Produkten, Prozessen und Dienstleistungen in den Bereichen|"
    r"Certifications? of products, processes and services|Die Zertifizierungsstelle verfügt|"
    r"Der Zertifizierungsstelle ist|The certification body (is|has|maintains)|flexiblen Akkreditierungsbereich|"
    r"flexible scope|Standorten ausgeführt|following (sites|locations)|^\d\)\s?\D|www\.dakks\.de|Akkreditierungsurkunde|"
    r"accreditation certificate|Abkürzungen|Abbreviations|^Zertifizierungen nach:?$|^Certifications? according to:?$|"
    r"^in Verbindung mit:?$|^in conjunction with:?$|Kriterienliste:?$|Richtlinie oder Norm ?/ ?Ausgabedatum|"
    r"für folgende Produkte auf Grundlage von|^Standort$|^Site$|^\w{1,3} = \w|Gültig ab|Seite \d+ von|"
    r"Page \d+ of|Verwendete Abkürzungen|^Legende|^Legend|Konformitätsbewertungen werden ganz oder teilweise|"
    r"^Titel der (Richtlinie|Norm)|^Bezeichnung$|^Ausgabe(datum)?$|^Kurztitel$|^Document (reference|title)$", re.I)
SKIP_KEY = re.compile(r"^(System|Standort|Ort$|Site|Scope Nr|Spalte 7$|Assessment process|Ausgabe|Issue)", re.I)
REF_KEY = re.compile(r"Kurztitel|Document reference|Richtlinie oder Norm|^Norm$|Normative", re.I)
SECTION_KEYS = ("Abschnitt",)
AREA_KEYS = ("Bereich",)
REF_START = re.compile(r"^(DIN|EN|ISO|IEC|VDE|VDI|DVGW|ETSI|ASTM|UL|FGW|TR|BSI|DAfStb|DWA|RAL|ZTV|TL|EAD|ETAG|CEN|"
                       r"Z\d{4}|PIZO|QMA|[A-Z]{2,6}[- ]?\d[\w.-]*)[\s\d:/.-]", re.I)
NOISE = re.compile(r"^[\s−\-–•·.,;:()\[\]IVXivx\d]*$")
SECTION_NO = re.compile(r"^\d+(\.\d+)*\.?\s+")


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def iso_date(d):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def scheme_of(t):
    return next((c for rx, c in DE_SCHEMES if rx.search(t)), None)


def industry_of(t):
    return (next((i for rx, i in DE_WORDS if rx.search(t)), None)
            or next((i for rx, i in it.INDUSTRY_WORDS if rx.search(t)), None))


def country_of(a):
    if a["country"] in COUNTRIES:
        return COUNTRIES[a["country"]]
    parts = [p.strip() for p in a["address"].split(",")]
    for p in reversed(parts):
        if p in COUNTRIES:
            return COUNTRIES[p]
    return ""


def lines_of(rows, dropped, reg):
    """scope_lines rows of one annex -> out-lines. Section headings ('Abschnitt') are context."""
    has_section = any("Abschnitt" in json.loads(r["other_columns_raw"] or "{}") for r in rows)
    out, section, sec_children, sec_line = [], "", 0, None

    def close():
        if sec_line is not None and sec_children == 0:
            out.append(sec_line)

    for r in rows:
        o = json.loads(r["other_columns_raw"] or "{}")
        sec = clean(next((o[k] for k in SECTION_KEYS if k in o), ""))
        prod, norm = [], []
        for v in (r["product_text_raw"],):
            if clean(v):
                prod.append(clean(v))
        if clean(r["normative_docs_raw"]):
            norm.append(clean(r["normative_docs_raw"]))
        sch_t = clean(r["scheme_text_raw"])
        area = ""
        for k, v in o.items():
            v = clean(v)
            if k in SECTION_KEYS or SKIP_KEY.search(k) or not v or NOISE.match(v) or len(v) <= 3:
                continue
            if DROP_VALUE.search(v):
                dropped["boilerplate (annex text, legends, footnotes)"].append(reg)
                continue
            if k in AREA_KEYS:
                area = v
                continue
            if REF_KEY.search(k) or (REF_START.match(v) and len(v) < 70):
                norm.append(v)
            else:
                prod.append(v)
        if sec and sec != section:
            close()
            section, sec_children = sec, 0
            head = SECTION_NO.sub("", sec)
            sec_line = None if DROP_VALUE.search(head) else make(head, "", "", head)
        if area and not prod and not norm and not sch_t:
            if has_section:
                dropped["area list (repeated by the sections below)"].append(reg)
            else:
                out.append(make(area, "", "", area))
            continue
        if not (prod or norm or sch_t):
            if not sec:
                dropped["empty or column-only row"].append(reg)
            continue
        ctx = SECTION_NO.sub("", section) if section else ""
        out.append(make(" ".join(prod), sch_t or ctx, " ".join(norm), " ".join([ctx, sch_t])))
        sec_children += 1
    close()
    return out


def make(prod, sch_t, norm, ctx):
    own = " ".join([prod, sch_t, norm])
    sc = scheme_of(own) or scheme_of(ctx)
    ind = None if sc else (industry_of(prod + " " + norm) or industry_of(ctx + " " + sch_t))
    return {"scheme": sc or "", "industry": ind or "", "product_text": prod, "product_text_en": "",
            "scheme_text": sch_t, "normative_docs": norm, "standard_refs": refs(own), "status": "ACTIVE"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    review, dropped = [], collections.defaultdict(list)

    accs = read(args.scrape / "accreditations.csv")
    by_reg = {a["accreditation_id"]: a for a in accs}
    lines = collections.defaultdict(list)
    for r in read(args.scrape / "scope_lines.csv"):
        lines[r["registration_no"]].append(r)

    # existing body rows: DAkkS MS dataset by body number, others by country + name
    data = args.out.parent
    ms_rows, any_rows = {}, {}
    for f in data.glob("*/bodies.csv"):
        if f.parent == args.out:
            continue
        for b in read(f):
            if f.parent.name == "dakks-germany":
                ms_rows[b["registration_no"][5:]] = b
            any_rows.setdefault((b["country"], b["name"].casefold()), b)
    contacts = {r["registration_no"][5:]: r for r in read(HERE / "contacts.csv")}

    by_body = collections.defaultdict(list)
    for a in accs:
        by_body[a["body_id"]].append(a)

    bodies, acc_rows, ps = [], [], []
    for body_id in sorted(by_body):
        regs = sorted(by_body[body_id], key=lambda a: a["accreditation_id"])
        live = [a for a in regs if a["status"] != "Zurückgezogen"]
        if not live:
            review.append(f"{body_id} {regs[0]['name']}: all accreditations withdrawn, left out")
            continue
        out = []
        for a in live:
            rows = sorted(lines.get(a["accreditation_id"], []), key=lambda r: (int(r["page"]), int(r["row_index"])))
            got = lines_of(rows, dropped, a["accreditation_id"])
            if a["status"] != "Aktiv":
                for g in got:
                    g["status"] = "SUSPENDED"
            out += got
        # same line twice in one body (certificate and annex repeat each other)
        seen, uniq = set(), []
        for g in out:
            k = (g["product_text"], g["scheme_text"], g["normative_docs"])
            if k in seen:
                dropped["duplicate of an earlier line of the same body"].append(body_id)
                continue
            seen.add(k)
            uniq.append(g)
        if not uniq:  # annex did not parse: fall back to the register's scope summary
            for a in live:
                for part in re.split(r";\s+", clean(a["scope_de"])):
                    if len(part) > 15 and not re.match(r"D-ZE-|Gültig ab", part):
                        g = make(part, "", "", "")
                        g["status"] = "ACTIVE" if a["status"] == "Aktiv" else "SUSPENDED"
                        uniq.append(g)
            if uniq:
                review.append(f"{body_id} {regs[0]['name']}: annex not parsed, {len(uniq)} lines from the register scope summary")
        if not uniq:
            review.append(f"{body_id} {regs[0]['name']}: no importable line ({len(live)} documents), left out")
            continue
        a0 = live[0]
        number = body_id[5:]
        country = country_of(a0) or "Germany"
        if number in ms_rows:
            b = dict(ms_rows[number])
            review.append(f"{body_id}: reuses DAkkS MS body row '{b['name']}'")
        elif (country, a0["name"].strip().casefold()) in any_rows:
            b = dict(any_rows[(country, a0["name"].strip().casefold())])
            review.append(f"{body_id}: reuses body row '{b['name']}' from another dataset")
        else:
            c = contacts.get(number, {})
            b = {"name": a0["name"].strip(), "country": country, "registration_no": body_id,
                 "phone": c.get("phone", ""), "email": c.get("email", ""), "website": c.get("website", ""),
                 "address": ", ".join(p for p in (a0["street"].strip(), f"{a0['postcode']} {a0['city']}".strip()) if p),
                 "source_url": REGISTER + a0["accreditation_id"], "verified_at": ""}
        bodies.append(b)
        cert = next((a["accreditation_id"] for a in live if a["accreditation_id"].endswith("-00")), live[0]["accreditation_id"])
        if len({a["accreditation_id"][:13] for a in live}) > 1:
            review.append(f"{body_id}: accreditations {sorted({a['accreditation_id'][:13] for a in live})} merged into {cert}")
        acc_rows.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": b["name"],
                         "accreditation_standard": STD,
                         "status": "ACTIVE" if any(a["status"] == "Aktiv" for a in live) else "SUSPENDED",
                         "issue_date": min(iso_date(a["status_since"]) for a in live), "expiry_date": "",
                         "proof_url": a0["pdf_de_url"] or a0["pdf_en_url"] or REGISTER + a0["accreditation_id"]})
        for i, g in enumerate(uniq, 1):
            ps.append({"certificate_number": cert, "line_no": i, **g})

    names = collections.Counter(b["name"] for b in bodies)
    for n, k in names.items():
        if k > 1:
            review.append(f"DUPLICATE body name {n} x{k}")
    no_phone = [b["name"] for b in bodies if not b["phone"]]

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies, key=lambda b: b["name"].casefold()))
    write(args.out / "accreditations.csv", ACC_COLUMNS, sorted(acc_rows, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(args.out / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    with open(HERE / "dakks_17065_review.md", "w", encoding="utf-8") as f:
        f.write(f"# DAkkS ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, "
                f"{len(acc_rows)} accreditations, {len(ps)} product lines ({with_scheme} with a scheme).\n\n")
        f.write("## Lines left out (reason: lines)\n\n")
        f.writelines(f"- {k}: {len(v)}\n" for k, v in sorted(dropped.items(), key=lambda kv: -len(kv[1])))
        f.write("\n## Notes\n\n")
        f.writelines(f"- {r}\n" for r in review)
        f.write(f"\n## Bodies without phone ({len(no_phone)})\n\nDAkkS publishes no contacts; left empty.\n")
    print(f"bodies {len(bodies)}, accreditations {len(acc_rows)}, product lines {len(ps)} ({with_scheme} with scheme)")


if __name__ == "__main__":
    main()
