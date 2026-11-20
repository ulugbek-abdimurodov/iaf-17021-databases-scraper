"""Convert the LASA / NAB (Lithuania) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_lt_nab_17065.py): nab_17065_raw.json and, per body folder, the Lithuanian "Akreditavimo pažymėjimas ir
sritis <no>.pdf" (certificate + scope; the English copy is not used, the Lithuanian one is the original). The scope
tables ("N lentelė") are not ruled, so they are read from word positions: the header words give the column starts and
roles (product / scheme / normative), a line with text starting a new product or legislation starts a record, lines
with only standards or lower-case fragments continue it. Footers ("Puslapis N iš M") and footnotes ("*...") are
dropped. Output: bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv in <dataset dir>, and
nab_17065_review.md next to this script.
"""
from __future__ import annotations

import argparse
import collections
import csv
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

AB_CODE = "LASA"
HEAD_WORDS = [("drop", r"^Eil\.?$"),
              ("scheme_text", r"^(ES|Teisės|direktyva|Atitikties|Sertifikavimo|Schem|Modul)"),
              ("product_text", r"^(Produkt|Paslaug|Proces)"),
              ("normative_docs", r"^(Norminio|Norminis|Atitinkami|Standart|Reikalavim)")]
FOOT = re.compile(r"^(Puslapis \d+ iš \d+|\*|Pastaba|Pastabos|Direktor|Pažymėjimas|Informacija apie|skelbiama|panaikintas)")
SKIP_LINE = re.compile(r"^(AKREDITAVIMO SRITIS|Veiklos vykdymo vietos adresas|\d+ lentelė|.*akredituotas LST EN ISO/IEC 17065)", re.I)
NATIONAL = re.compile(r"Lietuvos Respublikos|įsakym|nutarim|\bSTR\b|ministr|Valstybinės", re.I)
LT_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"maisto kokyb|bitinink|medaus|duonos|pieno|mėsa|paukštien|kiaušin|daržov|vaisi", "food"),
    (r"tekstil|audin|drabuž|textile", "textiles"),
    (r"gaisr|priešgaisr|fire", "construction"),
    (r"statyb|betono|mišini|skald|užpild|cement|plyt|langai|dur|stogo|izoliac|bitumin|asfalt", "construction"),
    (r"geležinkel|railway|riedmen", "transport_equipment"),
    (r"kėlimo|liftų|slėgi|katil|mašin|įrenginių|equipment", "machinery"),
    (r"elektr|electr|matavimo|svarstykl", "electrical"),
    (r"kuro|biokur|degal|energij|šilum|granul", "energy"),
    (r"ekologišk|žemės ūkio|augal|gyvul|organic|agricult", "agriculture"),
    (r"maisto|pieno|mėsos|food|vyn", "food"),
    (r"medien|wood|miško|popier", "wood_paper"),
    (r"trąš|chemin|fertili", "chemicals"),
    (r"plastik|plastic|polimer", "rubber_plastics"),
]]
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def clean(t):
    return gr.clean(t)


def scheme_of(t: str):
    p = gr.probe(t)
    eu = next((c for rx, c in gr.EU_RX if rx.search(p)), None)
    if eu:
        return eu
    if NATIONAL.search(t):
        return None
    return next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def phone_lt(raw: str) -> str:
    """First number only; '+ 370 37 400351' -> '+370 37 400351'; '+37068895950' -> '+370 688 95950'."""
    p = re.split(r"[;,]", raw or "")[0].strip()
    p = re.sub(r"^\+\s+", "+", p)
    m = re.fullmatch(r"\+370(\d{8})", p)
    if m:
        p = f"+370 {m.group(1)[:3]} {m.group(1)[3:]}"
    return p if re.fullmatch(r"\+370(?: \d+)+", p) else ""


def industry_of(t: str):
    return next((i for rx, i in LT_WORDS if rx.search(t)), None) or gr.industry_of(t)


def page_lines(page):
    rows = collections.defaultdict(list)
    for w in page.extract_words(keep_blank_chars=False, use_text_flow=False):
        k = next((k for k in rows if abs(k - w["top"]) <= 2.5), round(w["top"]))
        rows[k].append(w)
    return [(k, sorted(rows[k], key=lambda w: w["x0"])) for k in sorted(rows)]


HEADER_VOCAB = re.compile(r"\b(Produkto|Produktų grupės|Produktų sritis|Paslaugos|Atitikties|Norminio|Atitinkami|Reglamento|ES direktyva|"
                          r"Sertifikavimo schema|Techninės specifikacijos|ESPVT\d?|AVCP\d?|Srities kodas|Sprendimas|Eil\.\d?|"
                          r"pavadinimas|vertinimo|procedūr|standart|žymuo|moduliai|priedas/straipsnis|teisės aktas|perimta|taikoma|direktyva$)", re.I)
LEGISLATION = re.compile(r"(direktyv|reglament|įsakym|nutarim|įstatym)", re.I)
FOOT2 = re.compile(r"^(Akreditavimo pažymėjimas pasirašytas|Nacionalinio akreditacijos biuro direktoriaus|_{5,}|kvalifikuotu)")


def segments(ws, gap=10):
    segs, cur = [], [ws[0]]
    for w in ws[1:]:
        if w["x0"] - cur[-1]["x1"] > gap:
            segs.append(cur)
            cur = [w]
        else:
            cur.append(w)
    segs.append(cur)
    return segs


def read_scope(path: Path, audit, reg):
    records, cols, in_scope, context = [], None, False, ""
    meta = {"code": "", "issued": "", "since": ""}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = page_lines(page)
            text = "\n".join(" ".join(w["text"] for w in ws) for _, ws in lines)
            m = re.search(r"juridinio asmens kodas:\s*(\d{7,9})", text)
            if m:
                meta["code"] = m.group(1)
            m = re.search(r"Pažymėjimas išduotas / galioja nuo:\s*(\d{4}-\d{2}-\d{2})", text)
            if m:
                meta["issued"] = m.group(1)
            m = re.search(r"akredituota nuo:\s*(\d{4}-\d{2}-\d{2})", text)
            if m:
                meta["since"] = m.group(1)
            if "AKREDITAVIMO SRITIS" in text or re.search(r"Veiklos vykdymo vietos adresas", text):
                in_scope = True
            if not in_scope:
                continue
            band = []  # header lines collected until the first data line

            def close_band():
                nonlocal cols
                new = {}
                for hws in band:
                    for s in segments(hws):
                        label = " ".join(w["text"] for w in s)
                        if not re.match(r"^(Produkt|Paslaug|Atitikties|Norminio|Standart|Sertifikavimo|ES |Reglamento|Atitinkami|Teisės|"
                                        r"Techninės|ESPVT|AVCP|Sprendimas|Srities|Eil)", label):
                            continue  # wrapped fragment of a label above
                        role = ("drop" if re.match(r"^(Srities|Eil)", label)
                                else "scheme_text" if re.match(r"^Produktų sritis", label)
                                else "product_text" if re.match(r"^(Produkt|Paslaug)", label)
                                else "normative_docs" if re.match(r"^(Norminio|Standart|Reglamento|Atitinkami|Techninės)", label)
                                else "scheme_text")
                        if all(abs(s[0]["x0"] - x) > 25 for x in new):
                            new[s[0]["x0"]] = (s[-1]["x1"], role)
                if len(new) >= 2:
                    xs = sorted(new)
                    # labels are centred: split halfway between one label's end and the next label's start
                    bounds = [0] + [(new[xs[k]][0] + 12) if new[xs[k]][1] == "drop" else (new[xs[k]][0] + xs[k + 1]) / 2
                                    for k in range(len(xs) - 1)] + [page.width]  # a number column is narrow
                    cols = [(bounds[k], bounds[k + 1], new[xs[k]][1]) for k in range(len(xs))]
                    audit["table header"].append((reg, " | ".join(r for _, _, r in cols)))
                band.clear()

            for top, ws in lines:
                full = clean(" ".join(w["text"] for w in ws))
                hits = len(set(m.group(0).lower() for m in HEADER_VOCAB.finditer(full)))
                if hits >= 1 and len(full) < 220 and not re.search(r"\d{3,}", full) and \
                        (band or hits >= 2 or re.match(r"^(Produkt|Atitikties|Norminio|Sertifikavimo|ES direktyva)", full)):
                    band.append(ws)
                    continue
                if band:
                    close_band()
                if FOOT.match(full) or FOOT2.match(full) or SKIP_LINE.match(full) or re.match(r"^\d+ lentelė", full):
                    audit["page header / footer / note"].append((reg, full[:80]))
                    continue
                if not cols:
                    audit["line before any table header"].append((reg, full[:80]))
                    continue
                if re.match(r"^[A-ZŽŠČ][\wąčęėįšųūž.]+ (g|pr|al)\. \d|^\d{5} ", full):
                    audit["site address"].append((reg, full[:80]))
                    continue
                segs = segments(ws, gap=14)
                if len(segs) == 1 and LEGISLATION.search(full) and not (records and records[-1].get("_open")):
                    context = full if not (context and re.match(r"^[a-zą-ž]", full)) else context + " " + full
                    audit["legislation heading (carried into scheme_text)"].append((reg, full[:80]))
                    continue
                cells = collections.defaultdict(list)
                for w in ws:
                    role = next((r for x0, x1, r in cols if x0 <= w["x0"] < x1), cols[-1][2])
                    cells[role].append(w["text"])
                cells = {k: clean(" ".join(v)) for k, v in cells.items() if k != "drop"}
                lead = cells.get("product_text", "")
                starts_new = bool(lead) and bool(re.match(r"^[A-ZĄČĘĖĮŠŲŪŽ0-9„\"(]", lead)) and \
                    not (records and re.search(r"[,–-]$|\bir$|\bar$|\bsu$", records[-1].get("product_text", "")))
                if starts_new or not records:
                    rec = dict(cells)
                    rec["context"] = context
                    records.append(rec)
                else:
                    prev = records[-1]
                    for k, v in cells.items():
                        prev[k] = clean(prev.get(k, "") + " " + v)
    for r in records:
        r["scheme_text"] = "; ".join(x for x in (r.pop("context", ""), r.get("scheme_text", "")) if x)
    out = []
    pending = None  # a record without a product (legislation only) is merged into the next one
    for r in records:
        if re.fullmatch(r"[\d.)\s(]*", r.get("product_text", "")) and r.get("product_text"):
            audit["numbering fragment"].append((reg, r["product_text"]))
            r["product_text"] = ""
        if not r.get("product_text"):
            if pending:
                for k in ("scheme_text", "normative_docs"):
                    pending[k] = clean(pending.get(k, "") + " " + r.get(k, ""))
            else:
                pending = dict(r)
            continue
        if pending:
            for k in ("scheme_text", "normative_docs"):
                r[k] = clean(pending.get(k, "") + " " + r.get(k, ""))
            audit["record without product (merged into the next)"].append((reg, pending.get("scheme_text", "")[:60]))
            pending = None
        out.append(r)
    if pending and not out:
        out.append(pending)
    return out, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "nab_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)
    ms_rows = list(csv.DictReader(open(data_root / "lasa-lithuania" / "bodies.csv", encoding="utf-8")))
    ms_by_code = {r["registration_no"]: r for r in ms_rows if r["registration_no"]}
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "lasa-lithuania" / "accreditations.csv", encoding="utf-8"))}
    others = {}
    for f in data_root.glob("*/bodies.csv"):
        if f.parent != a.dataset.resolve():
            for r in csv.DictReader(open(f, encoding="utf-8")):
                others.setdefault((r["country"], r["name"]), (f.parent.name, r))
    folders = {p.name: p for p in a.scrape.iterdir() if p.is_dir()}

    bodies, accs, ps, seen = [], [], [], {}
    for rec in sorted(raw, key=lambda r: r["registration_no"]):
        no = rec["registration_no"]
        legal = clean(rec.get("legal_entity") or rec["name"])
        if rec["status"] != "active":
            review["Skipped (withdrawn in the register)"].append(f"{no} {clean(rec['name'])}")
            continue
        key = no.replace(".", "_").replace("-", "_")
        folder = next((p for n, p in folders.items() if n.startswith(key + "_") or n.startswith(key.replace("LA_", "LA.") + "_")
                       or n.replace(".", "_").startswith(key + "_")), None)
        pdfs = sorted(folder.glob("Akreditavimo*.pdf")) if folder else []
        if not pdfs and folder:
            pdfs = sorted(folder.glob("Akreditavimo*")) + sorted(folder.glob("*.pdf"))[:1]
        records, meta = [], {"code": "", "issued": "", "since": ""}
        for pdf in pdfs:
            r_, m_ = read_scope(pdf, audit, no)
            records += r_
            meta = {k: meta[k] or m_[k] for k in meta}
        # body: the MS row by legal entity code, else by name, else a new row named after the legal entity
        if meta["code"] in ms_by_code:
            body = dict(ms_by_code[meta["code"]])
            review["Bodies reused"].append(f"{no} `{body['name']}` from lasa-lithuania (same legal entity code {meta['code']})")
        elif ("Lithuania", legal) in others:
            ds, row = others[("Lithuania", legal)]
            body = dict(row)
            review["Bodies reused"].append(f"{no} `{legal}` from {ds} (same name)")
        else:
            web = re.sub(r"\s+", "", rec.get("website") or "")
            if web and not re.match(r"https?://", web, re.I):
                web = "https://" + web
            body = {"name": legal, "country": "Lithuania", "registration_no": meta["code"],
                    "phone": phone_lt(rec.get("phone", "")),
                    "email": re.split(r"[;,\s]+", (rec.get("email") or "").strip())[0], "website": web,
                    "address": clean(rec["address"]) + ", Lithuania", "source_url": "http://db.nab.lt/ais/accreditation/" + rec["id"],
                    "verified_at": ""}
            if rec.get("phone") and not body["phone"]:
                review["Invalid phones"].append(f"{no} {legal}: `{rec['phone']}` left empty")
        if not records:
            review["No scope table read: register scope text imported"].append(f"{no} {legal}")
            records = [{"product_text": s.strip()} for s in re.split(r";\s*", rec.get("scope_lt", "")) if s.strip()]
        if not records:
            review["Bodies dropped (no line)"].append(f"{no} {legal}")
            continue
        if body["name"] in seen:
            cert = seen[body["name"]]
            review["Accreditations merged (same body)"].append(f"{no} -> {cert}")
        else:
            cert = no if no not in used else f"{no} (17065)"
            seen[body["name"]] = cert
            bodies.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
            accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                         "accreditation_standard": "ISO/IEC 17065", "status": "ACTIVE",
                         "issue_date": rec.get("issued") or meta["since"] or meta["issued"],
                         "expiry_date": rec.get("expiry", ""), "proof_url": (rec.get("annex_urls") or [""])[0]})
        start = sum(1 for p in ps if p["certificate_number"] == cert)
        sticky = None
        for n, r_ in enumerate(records, start + 1):
            prod, sch, norm = r_.get("product_text", ""), r_.get("scheme_text", ""), r_.get("normative_docs", "")
            full = " ".join([prod, sch, norm])
            s = scheme_of(full)
            if s in {c for _, c in gr.EU_SCHEMES}:
                sticky = s
            elif not s and sticky and not NATIONAL.search(full) and \
                    (re.match(r"^\d{2,4}/\d+/E", sch or "") or re.search(r"modul|priedas", sch or "", re.I)):
                s = sticky
            ind = "" if s else (industry_of(full) or industry_of(rec.get("scope_lt", "")) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": s or "", "industry": ind,
                       "product_text": prod, "product_text_en": "", "scheme_text": sch, "normative_docs": norm,
                       "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if no in a.debug:
                print(n, s, "|", ind, "|", prod[:60], "|", sch[:50], "|", norm[:50])

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", gr.BODY_COLUMNS, bodies)
    write(a.dataset / "accreditations.csv", gr.ACC_COLUMNS, accs)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", gr.PS_COLUMNS, ps)
    neither = [p for p in ps if not p["scheme"] and not p["industry"]]
    out = [f"# LASA / NAB 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Lines per body", ""] + [f"- {c}: {n}" for c, n in collections.Counter(p['certificate_number'] for p in ps).items()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Not imported / context", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v[:120]] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]}" for p in neither]
    (HERE / "nab_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} "
          f"with scheme {sum(1 for p in ps if p['scheme'])} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
