"""Convert the ATS (Serbia) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_rs_ats_17065.py): ats_17065_raw.json and scope_documents/2-04-NNN.pdf (one scope PDF per body).
Output: bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv in <dataset dir>, and
ats_17065_review.md next to this script.

The "Детаљан обим акредитације" table is read with pdfplumber. The header row (Р. бр. | Производ / Група производа |
Поступак оцењивања усаглашености | Референтна документа) names the columns, and unlabeled columns join the labeled column
on their left. Sector rows (С-01 ... С-11) are not imported; they give the industry of the lines below. A row with
neither number nor product continues the line above (a cell split over several PDF rows).
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

AB_CODE = "ATS"
STD = "ISO/IEC 17065"
PS_COLUMNS = gr.PS_COLUMNS
BODY_COLUMNS = gr.BODY_COLUMNS
ACC_COLUMNS = gr.ACC_COLUMNS
# Serbian law, rulebook, decree: national, no catalogue scheme (EU references still win in scheme_of)
NATIONAL = re.compile(r"Правилник|Pravilnik|Закон|Zakon|Уредб[аеи](?! \(ЕУ\))|Uredb|Службени гласник|Сл\. гласник|"
                      r"Elaborat|Елаборат|Спецификациј|План контроле", re.I)
SECTOR = re.compile(r"^[СC]-?\s?(\d{2})\.?:?\s")
SECTOR_INDUSTRY = {"01": "electrical", "02": "machinery", "03": "construction", "04": "machinery",
                   "05": "machinery", "06": "transport_equipment", "07": "machinery", "08": "electrical",
                   "09": "agriculture", "10": "food", "11": "health"}
CYR_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"обезбеђењ|обезбеђивањ.{0,10}(лица|имовине)|приватн", "professional"),
    (r"медицинск", "health"),
    (r"радио|електри|мерил|мерн", "electrical"),
    (r"цемент|бетон|челик за армирање|грађевин|опека|агрегат", "construction"),
    (r"притис|котл|лифт|машин|експлозивн", "machinery"),
    (r"мед\b|кулен|сир\b|месо|мес[аоу]\b|вин[оа]|ракиј|купус|шаргарепа|прехрамбен", "food"),
    (r"органск|биљ|пољопривред|воће|поврће", "agriculture"),
]]
HEADER = re.compile(r"^(Р\.\s?б|R\.\s?b|Ord)", re.I)


def clean(t):
    return gr.clean((t or "").replace("\n", " "))


def scheme_of(t: str):
    p = gr.probe(t)
    # Serbia is not in the EU: an EU scheme needs the EU act itself cited, not just "organic production"
    cites_eu = re.search(r"\((ЕУ|EU|EC|ЕЗ|EEC)\)|(Regulation|Directive|Регулатив|Директив)", t)
    eu = next((c for rx, c in gr.EU_RX if rx.search(p)), None) if cites_eu else None
    if eu:
        return eu
    if NATIONAL.search(t):
        return None
    return next((c for rx, c in gr.SCHEMES if rx.search(p)), None)


def industry_of(t: str):
    return next((ind for rx, ind in CYR_WORDS if rx.search(t)), None) or gr.industry_of(t)


def roles_of(header):
    roles, last = [], "no"
    for i, h in enumerate(header):
        h = clean(h)
        if HEADER.match(h):
            last = "no"
        elif re.search(r"Производ|Product", h, re.I):
            last = "product_text"
        elif re.search(r"Поступак|Procedure", h, re.I):
            last = "scheme_text"
        elif re.search(r"Референтн|Reference|Norm", h, re.I):
            last = "normative_docs"
        elif not h and i == 0:
            last = "skip"
        roles.append(last)
    return roles


def parse_pdf(path: Path, audit, reg):
    lines, roles, sector_ind, roots = [], None, None, set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [clean(c) for c in row]
                    if not any(cells):
                        continue
                    first = next((c for c in cells if c), "")
                    if HEADER.match(first) or (any(re.search(r"Производ|Product", c) for c in cells)
                                               and any(re.search(r"Референтн|Reference", c) for c in cells)):
                        roles = roles_of(row)
                        continue
                    m = SECTOR.match(first)
                    if m and sum(1 for c in cells if c) == 1:
                        sector_ind = SECTOR_INDUSTRY.get(m.group(1))
                        if m.group(1) == "10" and re.search(r"обезбеђ", first):
                            sector_ind = "professional"
                        audit["sector heading"].append((reg, first[:100]))
                        continue
                    if not roles or len(roles) != len(cells):
                        audit["nested one-cell table (copy of a cell above)" if len(cells) == 1 else "row outside a recognised table"].append((reg, " | ".join(c for c in cells if c)[:150]))
                        continue
                    f = {"no": [], "product_text": [], "scheme_text": [], "normative_docs": [], "skip": []}
                    for r, c in zip(roles, cells):
                        if c:
                            f[r].append(c)
                    f = {k: " ".join(v) for k, v in f.items()}
                    if not f["no"] and not f["product_text"] and lines and not re.match(r"Локација|Location", first):
                        prev = lines[-1]  # continuation of the cells above
                        for k in ("scheme_text", "normative_docs"):
                            if f[k]:
                                prev[k] = (prev[k] + " " + f[k]).strip()
                        continue
                    if re.search(r"\((наставак|nastavak|continued)\)", f["product_text"], re.I) and \
                            f["no"] in roots:
                        audit["repeated parent row (наставак)"].append((reg, f["product_text"][:100]))
                        continue
                    if re.match(r"Локација|Location", first):
                        audit["site location"].append((reg, first[:100]))
                        continue
                    if not (f["product_text"] or f["scheme_text"] or f["normative_docs"]) and re.search(r"[A-Za-zА-я]{3}", f["no"]):
                        f["product_text"], f["no"] = f["no"], ""  # product text in the number column
                    elif not f["no"] and f["product_text"] and not f["scheme_text"] and not f["normative_docs"] \
                            and lines and not lines[-1].get("moved"):
                        # a product cell split over several PDF rows: join it to the line above
                        lines[-1]["product_text"] += " " + f["product_text"]
                        continue
                    if not (f["product_text"] or f["scheme_text"] or f["normative_docs"]):
                        audit["number only"].append((reg, f["no"]))
                        continue
                    if re.search(r"наставак|nastavak|continued", f["product_text"], re.I) and len(f["product_text"]) < 15:
                        audit["repeated parent row (наставак)"].append((reg, f["product_text"]))
                        continue
                    roots.add(f["no"])
                    lines.append({"no_root": f["no"], "product_text": f["product_text"],
                                  "scheme_text": f["scheme_text"], "normative_docs": f["normative_docs"],
                                  "sector": sector_ind})
    # parents: "2." carries its scheme and texts' scheme to "2.1", "2.2"... and GI items without a number
    out, parent = [], None
    for ln in lines:
        if re.search(r"-\s?наставак\s*$|\(наставак\)\s*$", ln["product_text"]):
            audit["repeated parent row (наставак)"].append((reg, ln["product_text"][:100]))
            continue
        full = " ".join([ln["product_text"], ln["scheme_text"], ln["normative_docs"]])
        s = scheme_of(full)
        is_child = (not ln["no_root"]) or re.fullmatch(r"\d+\.\d+.*", ln["no_root"] or "")
        if not is_child:
            parent = s
        elif not s and not NATIONAL.search(full):
            s = parent
        ln["scheme"] = s or ""
        out.append(ln)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "ats_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)

    ms_by_pib, by_name = {}, {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent == a.dataset.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if f.parent.name == "ats-serbia" and r["registration_no"]:
                ms_by_pib[r["registration_no"]] = r
            by_name.setdefault((r["country"], r["name"].lower()), (f.parent.name, r))
    used = set()
    for f in data_root.glob("ats-*/accreditations.csv"):
        if f.parent != a.dataset.resolve():
            used |= {r["certificate_number"] for r in csv.DictReader(open(f, encoding="utf-8"))}

    bodies, accs, ps = [], [], []
    for rec in sorted(raw, key=lambda r: r["registration_no"]):
        name = re.sub(r"^(.+?), ,", r",", gr.clean(rec["name"]))
        if rec["status"] != "Akreditovan":
            review["Skipped (not accredited)"].append(f"{rec['registration_no']} {name}: {rec['status']}")
            continue
        if rec.get("suspension") and rec["suspension"] != "Bez suspenzije":
            review["Suspension noted"].append(f"{rec['registration_no']} {name}: {rec['suspension']}")
        if rec.get("pib") in ms_by_pib:
            body = dict(ms_by_pib[rec["pib"]])
            review["Bodies reused"].append(f"{rec['registration_no']} `{body['name']}` from ats-serbia (same PIB)")
        elif ("Serbia", name.lower()) in by_name:
            ds, body = by_name[("Serbia", name.lower())]
            body = dict(body)
            review["Bodies reused"].append(f"{rec['registration_no']} `{body['name']}` from {ds} (same name)")
        else:
            ph = rec["phone"].split(",")[0].strip()
            digits = re.sub(r"\D", "", ph)
            if re.fullmatch(r"\+381 \d{2,3}( \d{2,4})+", ph):
                phone = ph
            elif digits.startswith("381"):
                phone = "+381 " + digits[3:]
            elif digits.startswith("0") and 8 <= len(digits) <= 10:
                phone = "+381 " + digits[1:]
            else:
                phone = ""
                if ph:
                    review["Invalid phones"].append(f"{rec['registration_no']} {name}: `{ph}` left empty")
            web = rec["website"].strip().rstrip("/")
            if web and not web.startswith("http"):
                web = "https://" + web
            body = {"name": name, "country": "Serbia", "registration_no": rec.get("pib", ""), "phone": phone,
                    "email": rec["email"].split(",")[0].strip().lower(), "website": web,
                    "address": gr.clean(rec["address"]),
                    "source_url": f"http://www.registar.ats.rs/predmet/{rec['id']}/", "verified_at": ""}
        pdf = a.scrape / "scope_documents" / f"{rec['file_no']}.pdf"
        lines = parse_pdf(pdf, audit, rec["registration_no"]) if pdf.exists() else []
        if not lines:
            review["Bodies dropped (no line)"].append(f"{rec['registration_no']} {name}")
            continue
        cert = rec["registration_no"]
        if cert in used:
            cert += " (17065)"
        bodies.append({k: body.get(k, "") for k in BODY_COLUMNS})
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE", "issue_date": rec["first_accreditation"] or rec["issued"],
                     "expiry_date": rec["expiry"], "proof_url": f"http://www.registar.ats.rs/predmet/{rec['id']}/"})
        for n, ln in enumerate(lines, 1):
            full = " ".join([ln["product_text"], ln["scheme_text"], ln["normative_docs"]])
            ind = "" if ln["scheme"] else (ln["sector"] or industry_of(full) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": ln["scheme"], "industry": ind,
                       "product_text": ln["product_text"], "product_text_en": "", "scheme_text": ln["scheme_text"],
                       "normative_docs": ln["normative_docs"], "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if cert in a.debug:
                print(n, ln["scheme"], "|", ind, "|", ln["product_text"][:70], "|", ln["scheme_text"][:30], "|", ln["normative_docs"][:50])

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", BODY_COLUMNS, bodies)
    write(a.dataset / "accreditations.csv", ACC_COLUMNS, accs)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", PS_COLUMNS, ps)

    neither = [p for p in ps if not p["scheme"] and not p["industry"]]
    out = [f"# ATS 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Rows not imported", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]}" for p in neither]
    (HERE / "ats_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
