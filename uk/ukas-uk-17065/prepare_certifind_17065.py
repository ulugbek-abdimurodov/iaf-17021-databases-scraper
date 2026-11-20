"""Convert the UKAS (United Kingdom) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD] [--debug REG...]

Input (from scrape_uk_ukas_17065.py): ukas_17065_raw.json and schedule_tables/<NNNN>_<name>.json (the schedule's tables,
page by page, as extracted by the scraper). Output: bodies.csv, accreditations.csv, scopes.csv (header only),
product_scopes.csv in <dataset dir>, and ukas_17065_review.md next to this script.

Schedule layout: a page header table (number, body, issue), location tables, then either
- voluntary schemes: "Product | Standard" (sometimes "| Location"), or
- statutory activity under an "Accreditation for the purpose of <UK Approved Body | Notified Body> activity ..." row:
  "Directive / Regulation | Conformity Assessment procedure / Module | Category of products | Essential requirements".
One table row = one line. Empty (merged) cells repeat the cell above. UK Approved Body (UKCA, GB legislation incl.
"retained EU law") is national: no EU scheme. Notified Body activity (EU law, Northern Ireland) gets the EU scheme.
"""
from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "greece" / "esyd-greece-17065"))
import prepare_certifind_17065 as gr  # noqa: E402  (scheme regexes, refs, English industry words)


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ms = _load("ukas_ms_prepare", HERE.parent / "prepare_certifind.py")  # phone(), checked_website()

AB_CODE = "UKAS"
STD = "ISO/IEC 17065"
SOURCE_URL = "https://www.ukas.com/find-an-organisation/browse-by-category/?cat=323"
PAGE_HEAD = re.compile(r"^(\d{4,5}\s+Accredited to|0?Error!|Schedule of Accreditation|Locations where|Overseas Locations|"
                       r"Location(s)? (where|code)|Accredited to ISO)", re.I)
CONTEXT = re.compile(r"^Accreditation for the purpos", re.I)
ROLE = [("drop", r"^Location"),
        ("scheme_text", r"Directive|Regulation|Conformity|Module|procedure|Scheme"),
        ("product_text", r"Product|Category of products|Service|Process|Activity|Scope"),
        ("normative_docs", r"Standard|Essential requirements|specification|Normative|Requirement")]
EU_CODES = {c for _, c in gr.EU_SCHEMES} | {"Cyber Resilience Act (EU) 2024/2847", "AI Act (EU) 2024/1689"}
PRIVATE_EXTRA = [
    (re.compile(r"BRC\w*.{0,40}Packaging", re.I), "BRCGS Packaging Materials"),
    (re.compile(r"BRC\w*.{0,40}(Storage|Distribution)", re.I), "BRCGS Storage and Distribution"),
    (re.compile(r"BRC\w*.{0,40}Agents", re.I), "BRCGS Agents and Brokers"),
    (re.compile(r"BRC\w*.{0,40}Consumer", re.I), "BRCGS Consumer Products"),
    (re.compile(r"BRC\w*.{0,40}Food", re.I), "BRCGS Food Safety"),
    (re.compile(r"GLOBAL ?G\.?A\.?P\.?.{0,40}(Chain of Custody|CoC)", re.I), "GLOBALG.A.P. Chain of Custody"),
    (re.compile(r"MSC.{0,30}Chain of Custody|Marine Stewardship.{0,40}Chain", re.I), "MSC Chain of Custody"),
    (re.compile(r"ENplus", re.I), "ENplus"),
    (re.compile(r"Keymark", re.I), "CEN Keymark"),
    (re.compile(r"IFS Logistics", re.I), "IFS Logistics"),
    (re.compile(r"IFS Broker", re.I), "IFS Broker"),
    (re.compile(r"IFS Wholesale", re.I), "IFS Wholesale"),
    (re.compile(r"IFS PAC", re.I), "IFS PACsecure"),
    (re.compile(r"IFS (HPC|Household)", re.I), "IFS HPC"),
    (re.compile(r"International Feature[ds] Standards? [–-] ?Food|IFS Food", re.I), "IFS Food"),
]
UK_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"explosi|flame|flameproof|ignition|mining|M1 Equipment|M2 Equipment|Group I+\b|engines?\b|pumps?\b|"
     r"spraying equipment", "machinery"),
    (r"MCERTS|monitor|flowmeter|metering", "electrical"),
    (r"heating|hot water|sanitary|plumbing|water supply", "construction"),
    (r"telecommunication|ICT|asset recovery|data destruction", "ict"),
    (r"compost|waste|recycl", "other_manufacturing"),
    (r"market research|research services", "professional"),
    (r"protective equipment|PPE|helmet|respirator", "other_manufacturing"),
    (r"age assurance|identity|digital", "ict"),
    (r"dentist|dental|clinical", "health"),
    (r"racing|racecourse|greyhound", "tourism"),
    (r"biomass", "energy"),
    (r"fire|smoke|alarm|security|intruder|CCTV|sprinkler|extinguish|door|lock", "construction"),
    (r"gambling|gaming|lotter|betting", "ict"),
    (r"meat|dairy|poultry|egg|fish|bakery|beverage|confection|food|feed", "food"),
    (r"farm|crop|livestock|organic|fresh produce|horticult|seed|plant", "agriculture"),
]]


def clean(t):
    return gr.clean((t or "").replace("\n", " "))


def scheme_of(t: str, regime: str):
    p = gr.probe(t)
    eu = next((c for rx, c in gr.EU_RX if rx.search(p)), None)
    if eu and regime == "EU":
        return eu
    if eu or re.search(r"\bUKCA\b|retained EU law|Approved Body|Statutory Instrument|\bS\.?I\.? ?\d{4}|Regulations \d{4}", t):
        return None  # GB legislation: national
    return next((c for rx, c in PRIVATE_EXTRA if rx.search(t)), None) or \
        next((c for rx, c in gr.SCHEMES[len(gr.EU_RX):] if rx.search(p)), None)


def fix_phone(raw: str) -> str:
    """First number only; split the country code off unspaced numbers ('+421422852221' -> '+421 422852221')."""
    raw = re.split(r"\s+(?=\+)", raw.strip())[0]
    m = re.fullmatch(r"\+(1|44|421|420|353|49|33|39|34|31)(\d{7,11})", raw)
    return f"+{m.group(1)} {m.group(2)}" if m else raw


def industry_of(t: str):
    return next((i for rx, i in UK_WORDS if rx.search(t)), None) or gr.industry_of(t)


def roles_of(cells):
    roles = []
    for c in cells:
        c = clean(c)
        roles.append(next((r for r, rx in ROLE if c and re.search(rx, c, re.I)), None))
    if not any(roles):
        return None
    # unlabeled columns join the labeled column on their left
    last = "product_text"
    for i, r in enumerate(roles):
        if r:
            last = r
        else:
            roles[i] = last
    return roles


def parse_schedule(tables, audit, reg):
    lines, roles, width, context, regime, group = [], None, None, "", "", ""
    carry = {}
    for t in tables:
        for row in t["rows"]:
            cells = [clean(c) for c in row]
            filled = [c for c in cells if c]
            if not filled:
                continue
            first = filled[0]
            if PAGE_HEAD.match(first) or (len(cells) <= 3 and re.search(r"Issue No:", " ".join(filled))):
                audit["page header / location table"].append((reg, first[:80]))
                roles = roles if not PAGE_HEAD.match(first) or not first.startswith(("Locations", "Overseas")) else None
                continue
            if CONTEXT.match(first):
                context = first
                regime = "EU" if re.search(r"Notified Body", first, re.I) else ("UK" if re.search(r"Approved Body|UK|Designated", first) else "")
                group = ""
                audit["activity heading (carried into scheme_text)"].append((reg, first[:100]))
                continue
            r = roles_of(cells) if all(len(c) < 120 for c in filled) else None
            if r and all(len(c) < 160 for c in filled) and \
                    all(re.search(r"^(Products?|Standards?|Directive|Conformity|Category|Essential|Location|Service|Process|"
                                  r"Scheme|Normative)\b", c, re.I) for c in filled):
                roles, width, carry = r, len(cells), {}
                continue
            if len(filled) == 1 and (len(cells) == 1 or cells[0] == first) and roles and len(cells) != width:
                group = first  # a one-cell sub-heading ("Construction Products", "Personal Protective Equipment")
                audit["group heading (carried into scheme_text)"].append((reg, first[:80]))
                continue
            if re.search(r"Overseas Location of Activities", first, re.I):
                audit["page header / location table"].append((reg, first[:80]))
                roles = None
                continue
            if re.fullmatch(r"END|End of schedule", first, re.I) and len(filled) == 1:
                audit["END marker"].append((reg, first))
                continue
            if not roles and context and len(cells) >= 3:
                # statutory table without a header row (e.g. rail): subsystem | procedure | category | requirements
                roles = (["product_text", "scheme_text", "product_text"] + ["normative_docs"] * len(cells))[:len(cells)]
                width, carry = len(cells), {}
                audit["statutory table without a header (default columns)"].append((reg, " | ".join(filled)[:80]))
            if not roles or len(cells) != width:
                if roles and len(cells) < width:
                    cells = cells + [""] * (width - len(cells))
                elif roles and len(cells) > width:
                    cells = cells[:width - 1] + [" ".join(cells[width - 1:])]
                else:
                    audit["row before any column header"].append((reg, " | ".join(filled)[:100]))
                    continue
            f = collections.defaultdict(list)
            for i, (role, c) in enumerate(zip(roles, cells)):
                if role == "drop":
                    continue
                if c:
                    carry[i] = c
                    f[role].append(c)
                elif role in ("scheme_text", "product_text") and i in carry and any(cells):
                    f[role].append(carry[i])  # vertically merged cell
            f = {k: " ".join(v) for k, v in f.items()}
            joined = " ".join(filled)
            if re.fullmatch(r"[\w()/ ]{0,12}[✓\s]+", joined) or "Application Review" in joined or \
                    re.fullmatch(r"(England|Northern Ireland|Scotland|Wales|United Kingdom)( (England|Northern Ireland|Scotland|Wales))*", joined):
                audit["matrix / location row"].append((reg, joined[:80]))
                continue
            if not (f.get("product_text") or f.get("normative_docs")):
                audit["row without product or standard"].append((reg, " | ".join(filled)[:80]))
                continue
            lines.append({"product_text": f.get("product_text", ""), "normative_docs": f.get("normative_docs", ""),
                          "scheme_col": f.get("scheme_text", ""), "context": context, "regime": regime, "group": group})
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()
    data_root = a.dataset.resolve().parent
    a.dataset.mkdir(parents=True, exist_ok=True)
    raw = json.loads((a.scrape / "ukas_17065_raw.json").read_text(encoding="utf-8"))
    review, audit = collections.defaultdict(list), collections.defaultdict(list)

    ms_by_no, others = {}, {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent == a.dataset.resolve():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if f.parent.name == "ukas-united-kingdom" and r["registration_no"]:
                ms_by_no[r["registration_no"]] = r
            others.setdefault((r["country"], r["name"]), (f.parent.name, r))
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "ukas-united-kingdom" / "accreditations.csv", encoding="utf-8"))}
    tables_by_no = {p.name.split("_")[0]: p for p in (a.scrape / "schedule_tables").glob("*.json")}

    out_b, out_a, ps = [], [], []
    seen, line_count = {}, collections.Counter()
    for rec in raw:
        no, name = rec["registration_no"], gr.clean(rec["name"])
        parts = [p.strip() for p in rec["address"].split(",")]
        country = parts[-1] if len(parts) > 1 else "United Kingdom"
        country = {"UK": "United Kingdom", "England": "United Kingdom", "Scotland": "United Kingdom",
                   "Wales": "United Kingdom", "Northern Ireland": "United Kingdom"}.get(country, country)
        if no in ms_by_no:
            body = dict(ms_by_no[no])
            review["Bodies reused"].append(f"{no} `{body['name']}` from ukas-united-kingdom (same UKAS number)")
        elif (country, name) in others:
            ds, row = others[(country, name)]
            body = dict(row)
            review["Bodies reused"].append(f"{no} `{name}` from {ds} (same name)")
        else:
            notes = []
            website = re.sub(r"\s+", "", rec.get("website", ""))
            if website and not re.match(r"https?://", website, re.I):
                website = "https://" + website
            body = {"name": name, "country": country, "registration_no": no,
                    "phone": ms.phone(no, name, fix_phone(rec.get("phone", "")), notes, country),
                    "email": (rec.get("email") or "").strip(), "website": website.rstrip("/"),
                    "address": ", ".join(parts[:-1]) if len(parts) > 1 else rec["address"],
                    "source_url": SOURCE_URL, "verified_at": ""}
            review["Invalid phones"].extend(notes)

        lines = []
        tpath = tables_by_no.get(no)
        if tpath:
            lines = parse_schedule(json.loads(tpath.read_text(encoding="utf-8")), audit, no)
        if not tpath and not rec.get("issued"):
            review["Not imported (schedule not downloaded, no issue date)"].append(
                f"{no} {name}: retry the scraper; UKAS returned HTTP 502 for the schedule")
            continue
        if not lines:
            why = "schedule not downloaded" if not tpath else "no table rows read"
            review["Register categories imported as the line"].append(f"{no} {name}: {why}")
            lines = [{"product_text": "; ".join(rec.get("categories") or []), "normative_docs": "", "scheme_col": "",
                      "context": "", "regime": "", "group": ""}]
        if body["name"] in seen:
            # the same company holds several UKAS numbers: one accreditation per body, lines merged into the first
            cert = seen[body["name"]]
            review["Accreditations merged"].append(f"{no} {name}: lines added to `{cert}`")
        else:
            cert = no if no not in used else f"{no} (17065)"
            seen[body["name"]] = cert
            out_b.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
            out_a.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                          "accreditation_standard": STD, "status": "ACTIVE", "issue_date": rec.get("issued", ""),
                          "expiry_date": "", "proof_url": (rec.get("annex_urls") or [SOURCE_URL])[0]})
        last_eu, last_ctx = None, None
        start = line_count[cert]
        line_count[cert] += len(lines)
        for n, ln in enumerate(lines, start + 1):
            if ln["context"] != last_ctx:
                last_eu, last_ctx = None, ln["context"]
            st = "; ".join(x for x in (ln["context"], ln["group"], ln["scheme_col"]) if x)
            own = " ".join([ln["scheme_col"], ln["product_text"], ln["normative_docs"], ln["group"]])
            s = scheme_of(own, ln["regime"]) or (scheme_of(ln["context"], ln["regime"]) if ln["regime"] == "EU" else None)
            if s in EU_CODES:
                last_eu = s
            elif not s and ln["regime"] == "EU" and last_eu:
                s = last_eu  # Notified Body block: the directive of the rows above (merged legislation cell)
            full = " ".join([ln["product_text"], st, ln["normative_docs"]])
            ind = "" if s else (industry_of(full) or industry_of(" ".join(rec.get("categories") or [])) or "")
            ps.append({"certificate_number": cert, "line_no": n, "scheme": s or "", "industry": ind,
                       "product_text": ln["product_text"], "product_text_en": "", "scheme_text": st,
                       "normative_docs": ln["normative_docs"], "standard_refs": gr.refs(full), "status": "ACTIVE"})
            if no in a.debug:
                print(n, s, "|", ind, "|", ln["product_text"][:60], "|", st[:60], "|", ln["normative_docs"][:50])

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
    names = collections.Counter(b["name"] for b in out_b)
    for nme, c in names.items():
        if c > 1:
            review["DUPLICATE body names"].append(nme)
    out = [f"# UKAS 17065 review ({a.today})", "",
           f"Bodies {len(out_b)}, accreditations {len(out_a)}, lines {len(ps)} "
           f"({sum(1 for p in ps if p['scheme'])} with a scheme, {len(neither)} with neither).", "", "## Schemes", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['scheme'] or '(none)' for p in ps).most_common()] + [""]
    out += ["## Industries (lines without a scheme)", ""]
    out += [f"- {c}: {n}" for c, n in collections.Counter(p['industry'] for p in ps if not p['scheme']).most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Not imported / context", ""] + [f"- {k}: {len(v)}" for k, v in audit.items()] + [""]
    for k, v in audit.items():
        out += [f"### {k}", ""] + [f"- {r}: {t}" for r, t in v[:200]] + [""]
    out += ["## Lines with neither scheme nor industry", ""] + [f"- {p['certificate_number']}: {p['product_text'][:90]} || {p['normative_docs'][:60]}" for p in neither]
    (HERE / "ukas_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"bodies {len(out_b)} accreditations {len(out_a)} lines {len(ps)} "
          f"with scheme {sum(1 for p in ps if p['scheme'])} neither {len(neither)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
