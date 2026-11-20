"""Convert the LATAK (Latvia) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_lv_latak_17065.py): latak_17065_raw.json and <S1-NNN>/<S1-NNN>_annex_tables.csv (page,table,row,cells...)
extracted from the annex pages. Annex table: "Objekts Subjects | Sertifikācijas shēma Certification scheme |
Normatīvi-tehniskās dokumentācijas nosaukums Normative document" (cells are Latvian followed by English). A row with an
object starts a line; rows with only a scheme / normative document continue it. A body without an annex (S1-182) gets
one line per item of the register's scope text. Output: bodies.csv, accreditations.csv, scopes.csv (header only),
product_scopes.csv in <dataset dir>, and latak_17065_review.md next to this script.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "greece" / "esyd-greece-17065"))
import prepare_certifind_17065 as gr  # noqa: E402  (scheme regexes, refs, English industry words)

AB_CODE = "LATAK"
REGISTER = "https://www.latak.gov.lv/lv/akreditetas-institucijas"
ROLE = [("product_text", r"Objekt|Subject|Product|Produkt"),
        ("scheme_text", r"shēm|scheme|Modul|procedūr"),
        ("normative_docs", r"Normatīv|Normative|dokument|standart")]
NATIONAL = re.compile(r"Ministru Kabineta|Cabinet Regulation|\bMK\b|Latvijas Republikas|Republic of Latvia|\bLVS\b(?! EN)", re.I)
PRIVATE_EXTRA = [(re.compile(r"\bFSC\b|Forest Stewardship", re.I), "FSC Chain of Custody"),
                 (re.compile(r"PEFC", re.I), "PEFC Chain of Custody")]
LV_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"ugunsdzēs|fire extinguish|mašīn|machinery|iekārt", "machinery"),
    (r"sprādzienbīstam|explosive atmosphere", "machinery"),
    (r"skaitītāj|meter|svar|weighing", "electrical"),
    (r"koksn|wood|mežsaimniec|forest", "wood_paper"),
    (r"degviel|fuel|benzīn|petrol|dīzeļ|diesel", "energy"),
    (r"mēslošan|fertili", "chemicals"),
    (r"ūden|water|dzēriel|beverage|pārtik|food", "food"),
    (r"bioloģisk|organic", "agriculture"),
]]


def clean(t):
    return gr.clean(t)


def scheme_of(t: str):
    p = gr.probe(t)
    eu = next((c for rx, c in gr.EU_RX if rx.search(p)), None)
    if eu:
        return eu
    if NATIONAL.search(t):
        return None
    return next((c for rx, c in PRIVATE_EXTRA if rx.search(t)), None) or \
        next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def industry_of(t: str):
    return next((i for rx, i in LV_WORDS if rx.search(t)), None) or gr.industry_of(t)


def read_annex(path: Path, audit, reg):
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))[1:]
    lines, roles = [], None
    for r in rows:
        cells = [clean(c) for c in r[3:]]
        filled = [c for c in cells if c]
        if not filled:
            continue
        if re.match(r"AKREDITĀCIJAS APLIECĪBAS|PIELIKUMS|ANNEX TO", filled[0], re.I):
            audit["page header"].append((reg, filled[0][:80]))
            continue
        if all(re.fullmatch(r"\d{1,2}", c) for c in filled):
            audit["column number row (1 | 2 | 3)"].append((reg, " | ".join(filled)))
            continue
        if any(re.match(r"^(Objekts|Subjects|Objekts Subjects)", c) for c in filled) or \
                (all(len(c) < 90 for c in filled) and sum(1 for c in filled if any(re.search(rx, c) for _, rx in ROLE)) == len(filled) >= 2):
            roles = []
            last = "product_text"
            for c in cells:
                role = next((ro for ro, rx in ROLE if c and re.search(rx, c, re.I)), None)
                last = role or last
                roles.append(last)
            audit["column header"].append((reg, " | ".join(filled)[:80]))
            continue
        if roles is None or len(roles) != len(cells):
            roles = (["product_text", "scheme_text", "normative_docs"] + ["normative_docs"] * len(cells))[:len(cells)]
        f = collections.defaultdict(list)
        for role, c in zip(roles, cells):
            if c:
                f[role].append(c)
        f = {k: " ".join(v) for k, v in f.items()}
        prod = f.get("product_text", "")
        if lines and prod and re.match(r"^[a-zāčēģīķļņšūž(]", prod):
            # the object cell continues from the row / page above
            prev = lines[-1]
            prev["product_text"] = (prev["product_text"] + " " + prod).strip()
            for k in ("scheme_text", "normative_docs"):
                if f.get(k):
                    prev[k] = (prev[k] + "; " + f[k]).strip("; ")
            audit["object cell continued (joined to the line above)"].append((reg, prod[:80]))
            continue
        if lines and prod and prod == lines[-1]["product_text"] and f.get("scheme_text", "") in ("", lines[-1]["scheme_text"]):
            prev = lines[-1]  # same object repeated for the next regulation: one line, documents collected
            if f.get("normative_docs"):
                prev["normative_docs"] = (prev["normative_docs"] + "; " + f["normative_docs"]).strip("; ")
            audit["repeated object row (merged)"].append((reg, prod[:80]))
            continue
        if f.get("product_text") or not lines:
            lines.append({"product_text": f.get("product_text", ""), "scheme_text": f.get("scheme_text", ""),
                          "normative_docs": f.get("normative_docs", "")})
        else:
            prev = lines[-1]  # continuation rows (vertically merged object cell)
            for k in ("scheme_text", "normative_docs"):
                if f.get(k):
                    prev[k] = (prev[k] + "; " + f[k]).strip("; ")
            audit["continuation row (joined to the line above)"].append((reg, " | ".join(filled)[:80]))
    return lines


LV_MONTHS = {"janvār": 1, "februār": 2, "mart": 3, "aprīl": 4, "maij": 5, "jūnij": 6, "jūlij": 7, "august": 8,
             "septembr": 9, "oktobr": 10, "novembr": 11, "decembr": 12}
EN_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}


def iso_date(raw: str) -> str:
    """'2025-03-20', '20.07.2031', '2023. gada 23. aprīļa' -> ISO."""
    raw = (raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\.?", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})\.\s*gada\s+(\d{1,2})\.\s*(\w+)", raw)
    if m:
        month = next((v for k, v in LV_MONTHS.items() if m.group(3).lower().startswith(k[:4])), None)
        if month:
            return f"{m.group(1)}-{month:02d}-{int(m.group(2)):02d}"
    return ""


def phone_lv(raw: str) -> str:
    d = re.sub(r"\D", "", (raw or "").split(",")[0])
    if d.startswith("371") and len(d) == 11:
        d = d[3:]
    return f"+371 {d}" if len(d) == 8 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "latak_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)
    ms = list(csv.DictReader(open(data_root / "latak-latvia" / "bodies.csv", encoding="utf-8")))
    ms_by_id = {r["registration_no"]: r for r in ms if r["registration_no"]}
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "latak-latvia" / "accreditations.csv", encoding="utf-8"))}
    others = {}
    for f in data_root.glob("*/bodies.csv"):
        if f.parent != a.dataset.resolve():
            for r in csv.DictReader(open(f, encoding="utf-8")):
                others.setdefault((r["country"], r["name"]), (f.parent.name, r))

    bodies, accs, ps, seen = [], [], [], {}
    for rec in sorted(raw, key=lambda r: r["registration_no"]):
        no, name = rec["registration_no"], clean(rec["name"])
        if rec["status"] != "active":
            review["Skipped (inactive in the register)"].append(f"{no} {name}")
            continue
        if rec.get("id") in ms_by_id:
            body = dict(ms_by_id[rec["id"]])
            review["Bodies reused"].append(f"{no} `{body['name']}` from latak-latvia (same company register number)")
        elif re.search(r"Kiwa Latvia", name) and any("Kiwa Latvia" in r["name"] for r in ms):
            body = dict(next(r for r in ms if "Kiwa Latvia" in r["name"]))
            review["Bodies reused"].append(f"{no} `{name}` -> `{body['name']}` from latak-latvia (same company, AS Kiwa Latvia)")
        elif ("Latvia", name) in others:
            ds, row = others[("Latvia", name)]
            body = dict(row)
            review["Bodies reused"].append(f"{no} `{name}` from {ds} (same name)")
        else:
            phone = phone_lv(rec.get("phone", ""))
            if rec.get("phone") and not phone:
                review["Invalid phones"].append(f"{no} {name}: `{rec['phone']}` left empty")
            body = {"name": name, "country": "Latvia", "registration_no": rec.get("id", ""), "phone": phone,
                    "email": rec.get("email", ""), "website": rec.get("website", ""),
                    "address": clean(rec["address"]) + ("" if rec["address"].endswith("Latvia") else ", Latvia"),
                    "source_url": REGISTER, "verified_at": ""}
        path = a.scrape / no / f"{no}_annex_tables.csv"
        lines = read_annex(path, audit, no) if path.exists() else []
        if not lines and rec.get("scope_text"):
            review["No annex tables: register scope text imported, one line per item"].append(f"{no} {name}")
            lines = [{"product_text": it.strip(), "scheme_text": "", "normative_docs": ""}
                     for it in re.split(r",\s*(?![^()]*\))", rec["scope_text"]) if it.strip()]
        if not lines:
            review["Bodies dropped (no line)"].append(f"{no} {name}")
            continue
        if body["name"] in seen:
            review["DUPLICATE body (second registration merged)"].append(f"{no} {name} -> {seen[body['name']]}")
            cert = seen[body["name"]]
        else:
            cert = no if no not in used else f"{no} (17065)"
            seen[body["name"]] = cert
            issued = iso_date(rec["issued"])
            if not issued:  # "Date of the Accreditation Committee decision: 26th of June 2026"
                txt = a.scrape / no / f"{no}_text.txt"
                m = re.search(r"Committee decision:\s*(\d{1,2})\w*\s+of\s+(\w+)\s+(\d{4})", txt.read_text(encoding="utf-8")) if txt.exists() else None
                if m and m.group(2).lower() in EN_MONTHS:
                    issued = f"{m.group(3)}-{EN_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
                    review["Issue date from the certificate text"].append(f"{no} {name}: {issued}")
            rec = dict(rec, issued=issued, expiry=iso_date(rec["expiry"]))
            bodies.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
            accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                         "accreditation_standard": "ISO/IEC 17065", "status": "ACTIVE", "issue_date": rec["issued"],
                         "expiry_date": rec["expiry"], "proof_url": (rec.get("annex_urls") or [REGISTER])[0]})
        start = sum(1 for p in ps if p["certificate_number"] == cert)
        for n, ln in enumerate(lines, start + 1):
            full = " ".join([ln["product_text"], ln["scheme_text"], ln["normative_docs"]])
            s = scheme_of(full) or ""
            ind = "" if s else (industry_of(full) or industry_of(rec.get("scope_text", "")) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": s, "industry": ind,
                       "product_text": ln["product_text"], "product_text_en": "", "scheme_text": ln["scheme_text"],
                       "normative_docs": ln["normative_docs"], "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if no in a.debug:
                print(n, s, "|", ind, "|", ln["product_text"][:60], "|", ln["scheme_text"][:40], "|", ln["normative_docs"][:60])

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
    out = [f"# LATAK 17065 review ({a.today})", "",
           f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Not imported / context", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:100]}" for p in neither]
    (HERE / "latak_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)} "
          f"with scheme {sum(1 for p in ps if p['scheme'])} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
