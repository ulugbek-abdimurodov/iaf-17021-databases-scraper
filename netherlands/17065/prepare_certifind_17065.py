"""Convert the RvA (Netherlands) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_nl_rva_17065.py): bodies.json, documents.json and files/<C...>/<C...>-scn.pdf (Dutch) and/or
-sce.pdf (English). Output: bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv in
<dataset dir>, and rva_17065_review.md next to this script.

Annex layout: location pages (skipped), then a ruled table "Product / Product Group | Certification Scheme |
Standard / normative document". Vertical rules give the columns, horizontal rules separate the records; a record
whose product and scheme cells are empty continues the record above (page break). Struck-through words are
withdrawn activities and are left out (the MS converter's struck()). One record = one line. The Dutch annex is the
original (product_text); the English annex is paired record by record into product_text_en when the record
counts match. An English-only annex fills both.
"""
from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "greece" / "esyd-greece-17065"))
import prepare_certifind_17065 as gr  # noqa: E402  (scheme regexes, refs, English industry words)


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ms = _load("rva_ms_prepare", HERE.parent / "prepare_certifind.py")  # struck(), phone(), city_case(), iso_date()

AB_CODE = "RvA"
STD = "ISO/IEC 17065"
COUNTRIES = dict(ms.COUNTRIES, **{"Slovenië": "Slovenia", "Maleisië": "Malaysia"})
PRODUCT_HEADER = re.compile(r"^Product\d?$", re.I)
ROLE_WORDS = [("scheme_text", r"Scheme|Schema|Certificatie(schema)?|Regeling"),
              ("normative_docs", r"Standard|Norm|normati|document"),
              ("product_text", r"Product|Group|Groep|Dienst|Service|Process|Proces")]
FOOT = re.compile(r"^(Dutch Accreditation Council|Raad voor Accreditatie|\d Definitions|\d Definities|\d If there|\d Indien|"
                  r"\d For normative|\d Voor normatieve|of the|van de|This annex|Deze bijlage)", re.I)
NATIONAL = re.compile(r"\bBRL\b|KOMO|\bCCV\b|NCS \d|Nationale beoordelingsrichtlijn|National Guideline|Bouwbesluit|"
                      r"Besluit|Regeling|Warenwet|\bSKH\b|\bSKG\b|Kiwa ?BRL|\bNL-|Nederlandse|Dutch|"
                      r"Stichting|Keurmerk|Groenkeur|Milieukeur|Beter Leven|\bVCA\b|Arbo|\bAI\b", re.I)
EU_EXTRA = [  # V81
    (re.compile(r"2024/2847|Cyber ?Resilience|CRA[- ]Verordening|CRA Regulation", re.I), "Cyber Resilience Act (EU) 2024/2847"),
    (re.compile(r"2024/1689|Artificial Intelligence Act|Artifici[eë]le intelligentie|AI[- ]Verordening", re.I), "AI Act (EU) 2024/1689"),
]
PRIVATE_EXTRA = [
    (re.compile(r"International Feature[ds] Standards? [–-] ?Food|IFS Food", re.I), "IFS Food"),
    (re.compile(r"International Feature[ds] Standards? [–-] ?Logistics|IFS Logistics", re.I), "IFS Logistics"),
    (re.compile(r"International Feature[ds] Standards? [–-] ?Broker|IFS Broker", re.I), "IFS Broker"),
    (re.compile(r"International Feature[ds] Standards? [–-] ?Wholesale|IFS Wholesale", re.I), "IFS Wholesale"),
    (re.compile(r"International Feature[ds] Standards? [–-] ?PAC|IFS PAC", re.I), "IFS PACsecure"),
    (re.compile(r"ENplus", re.I), "ENplus"),
    (re.compile(r"Keymark", re.I), "CEN Keymark"),
    (re.compile(r"GLOBAL ?G\.?A\.?P\.?.{0,40}(Chain of Custody|CoC|Ketenborging)", re.I), "GLOBALG.A.P. Chain of Custody"),
    (re.compile(r"MSC.{0,30}(Chain of Custody|CoC|Ketenbeheer)", re.I), "MSC Chain of Custody"),
]
NL_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"brandmeld|ontruim|inbraak|beveilig|alarm|camera|sprinkler|blus|brand|kabel|snoer|cable|elektr|electric|"
     r"toestel|appliance|verlicht|lighting|condensator|schakelaar|switch", "electrical"),
    (r"zorg|medisch|ziekenhuis|patiënt|apothe", "health"),
    (r"opleiding|onderwijs|examen|cursus|gemeente", "public_education"),
    (r"software|cyber|informatie|digitaal|privacy|gaming|kansspel|loterij|casino", "ict"),
    (r"bouw|beton|cement|asfalt|stenen|dak|gevel|kozijn|isolatie|riool|leiding|installat|bodem|grond|baggers|"
     r"funder|staal ?bouw|metsel|mortel|tegel|glas", "construction"),
    (r"kunststof|rubber|verpakking|PVC|PE-", "rubber_plastics"),
    (r"lasser|lassen|staal|metaal|aluminium|verzink", "metals"),
    (r"lift|hijs|kraan|machine|druk|ketel|steiger|valbeveilig|ladder", "machinery"),
    (r"elektr|kabel|snoer|lamp|verlicht|zonne|batterij|laad", "electrical"),
    (r"voertuig|auto|spoor|rail|trein|schip|scheeps|fiets|band", "transport_equipment"),
    (r"energie|biomassa|biobrandstof|biogas|waterstof|warmte|CO2|gas", "energy"),
    (r"hout|papier|karton|bos", "wood_paper"),
    (r"textiel|kleding|schoen", "textiles"),
    (r"chemisch|cosmetic|reinig|verf|meststof|bestrijdingsmiddel|diervoeder", "chemicals"),
    (r"voedsel|levensmiddel|vlees|zuivel|melk|kaas|vis\b|ei(eren)?\b|drank|food|feed", "food"),
    (r"landbouw|teelt|plant|bloem|boom|dier|vee|varken|kip|pluimvee|akker|tuinbouw|bollen|biologisch|organic", "agriculture"),
    (r"transport|logistiek|opslag|handel|vervoer", "trade_logistics"),
    (r"afval|recycl|meubel|speel", "other_manufacturing"),
    (r"dienst|service|audit|advies|schoonmaak|beheer", "professional"),
]]
EU_CODES = {c for _, c in gr.EU_SCHEMES} | {"Cyber Resilience Act (EU) 2024/2847", "AI Act (EU) 2024/1689"}
# notified-body heading: sets the directive for the lines below, not a line itself
NB_HEADING = re.compile(r"suitable for notification|geschikt voor aanmelding", re.I)
DROP_LINE = re.compile(r"^(\s*$|\d\s?Product as defined|\d\s?Product zoals gedefinieerd|NOTE\b|Note:|Opmerking|De accreditatie voor|The accreditation for|This accreditation|"
                       r"Product ?/ ?productgroep|Product ?/ ?Product ?Group|Location\b|Locatie\b)", re.I)
MODULE_LINE = re.compile(r"\bmodule\b|\bAnnex\b|\bBijlage\b|type[- ]?examination|typeonderzoek|Conformit|"
                         r"verification|keuring|kwaliteitsborging|quality assurance", re.I)
FOOTLINE = re.compile(r"^(\d?\s?(Definit|Indien (geen|wordt|er)|If there|If no|If reference|Voor normatieve|For normative|In case)|"
                      r"(Raad voor Accreditatie|Dutch Accreditation Council)\b|.*\b(Pagina \d+ van|Page \d+ of) \d+)", re.I)
CONT_SCHEME = re.compile(r"^(•|Periodiek|Surveillance|Toezicht|Herbeoordeling|Re-|Hertest|[a-z])")


def clean(t):
    return gr.clean((t or "").replace("\n", " "))


def scheme_of(t: str):
    p = gr.probe(t)
    eu = next((c for rx, c in EU_EXTRA if rx.search(t)), None) or next((c for rx, c in gr.EU_RX if rx.search(p)), None)
    if eu:
        return eu
    if NATIONAL.search(t):
        return None
    return next((c for rx, c in PRIVATE_EXTRA if rx.search(t)), None) or \
        next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def industry_of(t: str):
    return next((i for rx, i in NL_WORDS if rx.search(t)), None) or gr.industry_of(t)


def page_records(page, audit, reg):
    """[(cells dict, starts_new)] for the scope table of one page, or None for a page without it."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    head = next((w for w in words if PRODUCT_HEADER.match(w["text"]) and w["x0"] < 120), None)
    strokes = [r for r in page.rects + page.lines if abs(r["bottom"] - r["top"]) <= 1.5]
    hrules = sorted({round(r["top"]) for r in strokes if r["x1"] - r["x0"] > 60})
    verts = [r for r in page.rects + page.lines if abs(r["x1"] - r["x0"]) <= 1.5 and r["bottom"] - r["top"] > 15]
    context = ""
    if head is None:
        # no column header: the scope table is the one ruled to x≈558 (page header and location boxes end at 565)
        scope_h = sorted(round(r["top"]) for r in strokes if r["x1"] - r["x0"] > 60 and r["x1"] <= 561 and r["x0"] >= 36)
        if not scope_h:
            return None
        # scope tables have column rules at x≈140-175 and/or x≈415-430; location tables only at x≈305
        scope_v = [r for r in verts if 140 <= r["x0"] <= 175 or 415 <= r["x0"] <= 430]
        if not scope_v:
            return None
        top = max(scope_h[0], min(round(r["top"]) for r in scope_v) - 2)
        vrules = sorted({round(r["x0"]) for r in verts if r["top"] >= top - 2})
        inner = [x for x in vrules if 60 < x < page.width - 60]
        if len(inner) < 1:
            return None
        bounds = sorted(set([0] + inner + [page.width]))
        cols = list(zip(bounds[:-1], bounds[1:]))
        roles = (["product_text", "scheme_text", "normative_docs"] + ["normative_docs"] * len(cols))[:len(cols)]
        if len(cols) == 2:
            roles = ["product_text", "normative_docs"]
        above = [w for w in words if w["bottom"] < top and w["top"] > 100]
        context = clean(" ".join(w["text"] for w in sorted(above, key=lambda w: (round(w["top"]), w["x0"]))))
        if not re.search(r"Directive|Richtlijn|Regulation|Verordening|Scheme|Schema", context, re.I):
            context = ""
        audit["page without a column header (default columns)"].append((reg, f"page {page.page_number}"))
    else:
        vrules = sorted({round(r["x0"]) for r in verts if r["top"] > head["top"] and r["bottom"] - r["top"] > 30})
        # columns: vertical rules, else header word positions
        band = [w for w in words if head["top"] - 2 <= w["top"] <= head["top"] + 30]
        if vrules:
            bounds = [0] + [x for x in vrules if 60 < x < page.width - 60] + [page.width]
            bounds = sorted(set(bounds))
        else:
            starts = sorted({round(w["x0"]) for w in band if any(re.search(rx, w["text"], re.I) for _, rx in ROLE_WORDS)})
            bounds = [0] + starts[1:] + [page.width]
        cols = list(zip(bounds[:-1], bounds[1:]))
        roles = []
        for x0, x1 in cols:
            label = " ".join(w["text"] for w in band if x0 <= w["x0"] < x1)
            roles.append(next((r for r, rx in ROLE_WORDS if re.search(rx, label, re.I)), "product_text" if not roles else "normative_docs"))
        header_bottom = max(w["bottom"] for w in band)
        top = next((h for h in hrules if h > header_bottom - 1), header_bottom)
    rows_ = collections.defaultdict(list)
    for w in words:
        k = next((k for k in rows_ if abs(k - w["top"]) <= 2), round(w["top"]))
        rows_[k].append(w)
    foot = page.height
    for k in sorted(rows_):
        if k <= top:
            continue
        txt = " ".join(w["text"] for w in sorted(rows_[k], key=lambda w: w["x0"]))
        if FOOTLINE.match(txt):
            foot = k - 1
            break
    seps = [h for h in hrules if top + 3 < h < foot - 3]
    segments = list(zip([top] + seps, seps + [foot]))
    out = []
    for s0, s1 in segments:
        cells = collections.defaultdict(list)
        lines = collections.defaultdict(list)
        for w in words:
            if not (s0 <= w["top"] < s1):
                continue
            if ms.struck(w, strokes):
                audit["struck-through word (withdrawn)"].append((reg, w["text"]))
                continue
            ci = next((i for i, (x0, x1) in enumerate(cols) if x0 <= w["x0"] < x1), len(cols) - 1)
            key = next((k for k in lines[ci] if abs(k - w["top"]) <= 2), round(w["top"]))
            lines[ci].append(key)
            cells[(ci, key)].append(w)
        rec = collections.defaultdict(list)
        for (ci, key) in sorted(cells, key=lambda k: (k[0], k[1])):
            txt = " ".join(w["text"] for w in sorted(cells[(ci, key)], key=lambda w: w["x0"]))
            if FOOT.match(txt):
                continue
            rec[roles[ci]].append(txt)
        rec = {k: clean(" ".join(v)) for k, v in rec.items()}
        if any(rec.values()):
            if head is None:
                rec["headerless"] = True
                rec["context"] = context
            out.append(rec)
    return out


def read_annex(path: Path, audit, reg):
    records, ctx = [], ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            recs = page_records(page, audit, reg)
            if recs is None:
                continue
            for rec in recs:  # a directive heading above a header-less table carries to the next such pages
                if rec.get("headerless"):
                    ctx = rec["context"] or ctx
                    rec["context"] = ctx
                else:
                    ctx = ""
            for i, rec in enumerate(recs):
                if i == 0 and records and not rec.get("product_text") and \
                        (not rec.get("scheme_text") or CONT_SCHEME.match(rec["scheme_text"])):
                    prev = records[-1]  # the record continues from the previous page
                    for k in ("scheme_text", "normative_docs"):
                        if rec.get(k):
                            prev[k] = clean(prev.get(k, "") + " " + rec[k])
                    audit["record continued across a page"].append((reg, (rec.get("scheme_text") or rec.get("normative_docs", ""))[:60]))
                    continue
                records.append(dict(rec))
    # a record without product text repeats the product of the record above (merged product cell)
    last = ""
    for rec in records:
        if rec.get("product_text"):
            last = rec["product_text"]
        else:
            rec["product_text"] = last
            rec["carried"] = True
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    bodies = json.loads((a.scrape / "bodies.json").read_text(encoding="utf-8"))
    docs = json.loads((a.scrape / "documents.json").read_text(encoding="utf-8"))
    by_id = collections.defaultdict(dict)
    for d in docs:
        if d["download_status"] in ("downloaded", "unchanged"):
            by_id[d["id"]][d["language"]] = d
    review, audit = collections.defaultdict(list), collections.defaultdict(list)

    others = {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent == a.dataset.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            others.setdefault((r["country"], r["name"]), (f.parent.name, r))
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "rva-netherlands" / "accreditations.csv", encoding="utf-8"))}

    out_b, out_a, ps = [], [], []
    for b in bodies:
        rid, name = b["id"], b["title"].strip()
        name = ms.ALIASES.get(name, name)
        country = COUNTRIES.get(b["country"], b["country"])
        nl, en = by_id[rid].get("NL"), by_id[rid].get("EN")
        if not (nl or en):
            review["No annex (not imported)"].append(f"{rid} {name}")
            continue
        main_doc = nl or en
        recs = read_annex(a.scrape / main_doc["file"], audit, rid)
        if not recs and nl and en:  # the Dutch annex has no readable scope table: use the English one
            review["English annex used (Dutch table unreadable)"].append(f"{rid} {name}")
            main_doc, nl = en, None
            recs = read_annex(a.scrape / en["file"], audit, rid)
        en_recs = read_annex(a.scrape / en["file"], collections.defaultdict(list), rid) if (nl and en) else None
        if en_recs is not None and len(en_recs) != len(recs):
            review["Bilingual pairing failed (Dutch lines only)"].append(f"{rid} {name}: NL {len(recs)} records, EN {len(en_recs)}")
            en_recs = None
        if not recs:
            review["Bodies dropped (no line)"].append(f"{rid} {name}")
            continue
        if (country, name) in others:
            ds, row = others[(country, name)]
            body = dict(row)
            review["Bodies reused"].append(f"{rid} `{name}` from {ds} (same name)")
        else:
            street = re.sub(r"\s0(?=\s|$)", "", b["street"]).strip()
            address = ", ".join(x for x in (street, ms.city_case(b["address"].strip())) if x)
            website = b["website"].strip()
            if not re.search(r"[a-z0-9]\.[a-z]", website, re.I):  # the register shows a bare "http://" when empty
                website = ""
            if website and not re.match(r"https?://", website, re.I):
                website = "http://" + website
            notes = []
            raw_phone = b["phone"].strip()
            if re.fullmatch(r"\+60\d{8,10}", raw_phone):  # Malaysia, written without spaces
                raw_phone = f"+60 {raw_phone[3:5]} {raw_phone[5:8]} {raw_phone[8:]}"
            body = {"name": name, "country": country, "registration_no": rid,
                    "phone": ms.phone(rid, name, raw_phone, notes), "email": b["email"].strip(),
                    "website": re.sub(r"^HTTP", "http", website), "address": address,
                    "source_url": b["url"], "verified_at": ""}
            review["Invalid phones"].extend(notes)
        cert = rid if rid not in used else f"{rid} (17065)"
        valid_from = next((d["valid_from"] for d in (main_doc, by_id[rid].get("NL"), by_id[rid].get("EN"))
                           if d and d.get("valid_from")), "")
        valid_until = next((d["valid_until"] for d in (main_doc, by_id[rid].get("NL"), by_id[rid].get("EN"))
                            if d and d.get("valid_until")), "")
        if not valid_from:  # "geldig van: 11-09-2026 tot 01-05-2030" / "valid from: ... to ..."
            with pdfplumber.open(a.scrape / main_doc["file"]) as pdf:
                m = re.search(r"(?:geldig van|valid from)\D{0,5}(\d{2}-\d{2}-\d{4})\D{1,8}(\d{2}-\d{2}-\d{4})?",
                              pdf.pages[0].extract_text() or "", re.I)
            if m:
                valid_from, valid_until = m.group(1), m.group(2) or valid_until
                review["Dates read from the annex text"].append(f"{rid} {name}: {valid_from} – {valid_until}")
            else:
                review["No validity date found"].append(f"{rid} {name}")
        out_b.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
        out_a.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                      "accreditation_standard": STD, "status": "ACTIVE",
                      "issue_date": ms.iso_date(valid_from) if valid_from else "",
                      "expiry_date": ms.iso_date(valid_until) if valid_until else "",
                      "proof_url": main_doc["url"]})
        sticky, n, body_lines = None, 0, []
        for idx, rec in enumerate(recs):
            prod, sch, norm = rec.get("product_text", ""), rec.get("scheme_text", ""), rec.get("normative_docs", "")
            en_prod = ""
            if en_recs is not None:
                en_prod = en_recs[idx].get("product_text", "")
            elif not nl:
                en_prod = prod
            full = " ".join([prod, sch, norm, en_prod])
            s = scheme_of(" ".join([sch, prod, en_prod])) or scheme_of(norm) or scheme_of(rec.get("context", ""))
            if s in EU_CODES:
                sticky = s
            elif s:
                sticky = None  # a private or national scheme block ends the directive block
            if NB_HEADING.search(full):
                audit["notified-body heading (sets the directive below)"].append((rid, full[:100]))
                continue
            if DROP_LINE.match(prod) or DROP_LINE.match(full):
                audit["note / header row"].append((rid, full[:100]))
                continue
            if not s and sticky and not NATIONAL.search(full) and (MODULE_LINE.search(full) or rec.get("carried")):
                s = sticky
            ind = "" if s else (industry_of(full) or "")
            n += 1
            row = {"certificate_number": cert, "line_no": n, "scheme": s or "", "industry": ind,
                   "product_text": prod, "product_text_en": en_prod, "scheme_text": sch,
                   "normative_docs": norm, "standard_refs": gr.refs(full), "status": "ACTIVE"}
            body_lines.append(row)
            if rid in a.debug:
                print(n, s, "|", ind, "|", prod[:50], "|", en_prod[:30], "|", sch[:50], "|", norm[:50])
        # lines still without scheme or industry take the body's most common industry
        common = collections.Counter(r["industry"] for r in body_lines if r["industry"]).most_common(1)
        for r in body_lines:
            if not r["scheme"] and not r["industry"] and common:
                r["industry"] = common[0][0]
                audit["industry from the body's other lines"].append((rid, r["product_text"][:80]))
        ps.extend(body_lines)

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", gr.BODY_COLUMNS, out_b)
    write(a.dataset / "accreditations.csv", gr.ACC_COLUMNS, out_a)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", gr.PS_COLUMNS, ps)

    neither = [p for p in ps if not p["scheme"] and not p["industry"]]
    out = [f"# RvA 17065 review ({a.today})", "",
           f"Bodies {len(out_b)}, accreditations {len(out_a)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither, "
           f"{sum(1 for p in ps if p['product_text_en'])} with English text).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    out += ["## Lines per body", ""] + [f"- {c}: {n}" for c, n in collections.Counter(p['certificate_number'] for p in ps).items()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Not imported / context", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v[:200]] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:90]} || {p['scheme_text'][:60]}" for p in neither]
    (HERE / "rva_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(out_b)} accreditations {len(out_a)} lines {len(ps)} "
          f"with scheme {sum(1 for p in ps if p['scheme'])} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
