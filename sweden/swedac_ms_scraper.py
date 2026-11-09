#!/usr/bin/env python3
"""Collect management system certification bodies (ISO/IEC 17021-1) from the
public Swedac accreditation register, https://ackrediteringar.swedac.se/en

Read-only. Uses the JSON API behind the site's own pages:
  /api                          search (standard=, controlForm=, q=, page, pagesize)
  /api/org-list                 every published accreditation (with --full-scan)
  /api/<accNo>                  organisation and offices
  /api/scope-rows/<accNo>       scope lines
  /api/scope-headers/by-code/<controlFormCode>   column labels
  /api/reqdocs                  normative documents referred to by scope lines

Usage: python swedac_ms_scraper.py [--out se_ms_output] [--delay 0.5] [--full-scan]
"""
import argparse
import csv
import json
import re
import sys
import time
from html import unescape
from pathlib import Path

import requests

BASE = "https://ackrediteringar.swedac.se"
MS_CONTROL_FORM = "cert-ledningssystem"
NAME_RE = re.compile(r"management system|ledningssystem", re.I)
USER_AGENT = "accreditation-registry-scraper/1.0 (python-requests)"

BODY_COLS = ["ident", "url", "company", "accreditation_name", "state", "standard", "cvr",
             "address", "contact_name", "phone", "email", "website", "started", "renewed",
             "expires", "scope_entries", "latest_decision_date", "ms_certification",
             "matched_by", "scope_entries_all_standards", "other_standards"]
SCOPE_COLS = ["ident", "company", "scheme_title", "scheme_url", "published", "row_type",
              "column1", "column2", "column3", "column4", "column5", "column6", "column7",
              "column8", "column9", "comment", "standard", "control_form_code",
              "in_17021_scope", "business_unit", "requirement_docs", "footnotes"]
COLUMN_LEVELS = {"scheme_title": "level5", "column1": "level6", "column2": "level7",
                 "column3": "level8", "column4": "level9", "column5": "level10",
                 "column6": "level11", "column7": "level12", "column8": "level13",
                 "column9": "level14", "comment": "level15"}
CONTACT_COLS = ["ident", "company", "office_number", "office_name", "department",
                "office_status", "phone", "website"]
ADDRESS_COLS = ["ident", "company", "office_number", "office_name", "address_type",
                "address_lines", "zip", "city", "country"]
COLUMN_COLS = ["control_form_code", "control_form", "csv_column", "label_en", "label_sv"]
REQDOC_COLS = ["code", "name", "title", "title_en", "url"]
EXCLUDED_COLS = ["ident", "company", "reason"]


class Client:
    def __init__(self, base, delay, retries=5):
        self.base, self.delay, self.retries = base.rstrip("/"), delay, retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def get(self, path, **params):
        for attempt in range(self.retries):
            try:
                resp = self.session.get(self.base + path, params=params, timeout=60)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                time.sleep(self.delay)
                return resp.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                retryable = not (isinstance(exc, requests.HTTPError)
                                 and exc.response is not None
                                 and exc.response.status_code not in (429, 500, 502, 503, 504))
                if not retryable or attempt == self.retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")


def search_all(client, **filters):
    """Page through a search and fail if the rows do not match the reported total."""
    page, hits, total = 1, {}, None
    while True:
        data = client.get("/api", lang="en", page=page, pagesize=100, **filters)
        total = data["totalCount"]
        batch = data["hits"]
        for hit in batch:
            hits[hit["accNo"]] = hit["orgName"]
        if len(hits) >= total or not batch:
            break
        page += 1
    if len(hits) != total:
        sys.exit(f"Incomplete listing for {filters}: got {len(hits)} of {total}")
    return hits


def clean(value):
    """Plain text for CSV: decode JSON held in strings, strip HTML, tidy whitespace."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, (list, dict)):
        value = "; ".join(str(v) for v in (value if isinstance(value, list) else value.values()))
    text = unescape(re.sub(r"<[^>]+>", " ", str(value)))
    return re.sub(r"\s+", " ", text).strip()


def is_17021(row):
    return (row.get("standardCode") or "").startswith("iso-17021-1")


def is_ms_row(row):
    return (is_17021(row) or row.get("controlFormCode") == MS_CONTROL_FORM
            or (not row.get("standardCode") and bool(NAME_RE.search(row.get("level5") or ""))))


def office_number(office):
    return (office.get("customerNumber") or "").rsplit("-", 1)[-1]


def office_label(office):
    city = (office.get("visitingAddress") or office.get("postalAddress") or {}).get("city") or ""
    return f"{city} (ID {office_number(office)})".strip()


def address_lines(addr):
    keys = sorted(k for k in addr if k.startswith("addressLine"))
    return ", ".join(clean(addr[k]) for k in keys if addr[k])


def one_line_address(addr):
    place = " ".join(x for x in (addr.get("zipCode"), addr.get("city")) if x)
    return ", ".join(x for x in (address_lines(addr), place, addr.get("country")) if x)


def uniq(values):
    return list(dict.fromkeys(v for v in values if v))


def fetch_case(client, acc_no, headers_cache):
    case = {"ident": acc_no, "url": f"{client.base}/en/{acc_no}",
            "record": {}, "scope_rows": {}, "scope_headers": {}}
    for lang in ("en", "sv"):
        case["record"][lang] = client.get(f"/api/{acc_no}", lang=lang)
        case["scope_rows"][lang] = client.get(f"/api/scope-rows/{acc_no}", lang=lang)
    for code in uniq(r.get("controlFormCode") for r in case["scope_rows"]["en"]):
        if code not in headers_cache:
            headers_cache[code] = {lang: client.get(f"/api/scope-headers/by-code/{code}", lang=lang)
                                   for lang in ("en", "sv")}
        case["scope_headers"][code] = headers_cache[code]
    return case


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def control_form_en(case, code, fallback=""):
    header = case["scope_headers"].get(code, {}).get("en") or {}
    return header.get("controlFormEnglish") or header.get("externalNameEnglish") or fallback


def body_row(case):
    rec, rows = case["record"]["en"], case["scope_rows"]["en"]
    in_scope = [r for r in rows if is_ms_row(r)]
    forms = uniq(control_form_en(case, r.get("controlFormCode"), r.get("controlFormName"))
                 for r in in_scope)
    standards = uniq(r.get("standardName") for r in in_scope)
    others = uniq(r.get("standardName") for r in rows if r not in in_scope)
    addr = rec.get("visitingAddress") or rec.get("postalAddress") or {}
    return {
        "ident": case["ident"], "url": case["url"], "company": clean(rec.get("orgName")),
        "accreditation_name": "; ".join(forms), "state": rec.get("status") or "",
        "standard": "; ".join(standards), "cvr": rec.get("orgNumber") or "",
        "address": one_line_address(addr), "contact_name": "", "phone": rec.get("phoneNo") or "",
        "email": rec.get("email") or "", "website": rec.get("website") or "",
        "started": "", "renewed": "", "expires": "", "scope_entries": len(in_scope),
        "latest_decision_date": max((r.get("lastDecisionDate") or "" for r in in_scope), default=""),
        "ms_certification": "yes" if any(r.get("controlFormCode") == MS_CONTROL_FORM for r in rows) else "no",
        "matched_by": case["matched_by"], "scope_entries_all_standards": len(rows),
        "other_standards": "; ".join(others),
    }


def scope_rows(case):
    rec, rows = case["record"]["en"], case["scope_rows"]["en"]
    offices = {o.get("id"): office_label(o) for o in rec.get("offices") or []}
    out = []
    for row in rows:
        item = {"ident": case["ident"], "company": clean(rec.get("orgName")), "scheme_url": "",
                "published": row.get("lastDecisionDate") or "",
                "row_type": control_form_en(case, row.get("controlFormCode"), row.get("controlFormName")),
                "standard": row.get("standardName") or "",
                "control_form_code": row.get("controlFormCode") or "",
                "in_17021_scope": "yes" if is_ms_row(row) else "no",
                "business_unit": "; ".join(offices.get(i, i) for i in row.get("officeIds") or []),
                "requirement_docs": "; ".join(row.get("requirementDocSlugs") or []),
                "footnotes": clean(row.get("footnotes"))}
        for col, level in COLUMN_LEVELS.items():
            item[col] = clean(row.get(level))
        out.append(item)
    return out


def contact_rows(case):
    rec = case["record"]["en"]
    return [{"ident": case["ident"], "company": clean(rec.get("orgName")),
             "office_number": office_number(o), "office_name": clean(o.get("name")),
             "department": clean(o.get("department")), "office_status": o.get("status") or "",
             "phone": o.get("phoneNo") or "", "website": rec.get("website") or ""}
            for o in rec.get("offices") or []]


def address_rows(case):
    rec, out = case["record"]["en"], []
    for office in rec.get("offices") or []:
        for kind, key in (("postal", "postalAddress"), ("visiting", "visitingAddress")):
            addr = office.get(key)
            if addr:
                out.append({"ident": case["ident"], "company": clean(rec.get("orgName")),
                            "office_number": office_number(office), "office_name": clean(office.get("name")),
                            "address_type": kind, "address_lines": address_lines(addr),
                            "zip": addr.get("zipCode") or "", "city": addr.get("city") or "",
                            "country": addr.get("country") or ""})
    return out


def column_rows(headers_cache):
    out = []
    for code, langs in sorted(headers_cache.items()):
        en, sv = langs["en"], langs["sv"]
        for col, level in COLUMN_LEVELS.items():
            if en.get(level) or sv.get(level):
                out.append({"control_form_code": code,
                            "control_form": en.get("controlFormEnglish") or "",
                            "csv_column": col, "label_en": clean(en.get(level)),
                            "label_sv": clean(sv.get(level))})
    return out


def reqdoc_rows(reqdocs, used):
    return [{"code": d.get("code") or "", "name": d.get("name") or "", "title": d.get("title") or "",
             "title_en": d.get("titleEn") or "",
             "url": d.get("htmlPublicUrl") or d.get("pdfPublicUrl") or ""}
            for d in sorted(reqdocs, key=lambda d: d.get("code") or "") if d.get("code") in used]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="se_ms_output", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--full-scan", action="store_true",
                        help="check the scope of every accreditation, not only search candidates")
    parser.add_argument("--base-url", default=BASE, help=argparse.SUPPRESS)
    args = parser.parse_args()
    client = Client(args.base_url, max(args.delay, 0))
    out = Path(args.out)
    (out / "cases").mkdir(parents=True, exist_ok=True)

    aggs = client.get("/api", lang="en", page=1, pagesize=1, q="17021")["aggregations"]
    std_keys = uniq(s["key"] for s in aggs.get("standards", []) if s["key"].startswith("iso-17021-1"))
    if not std_keys:
        sys.exit("The standard ISO/IEC 17021-1 was not found in the site's search facets")

    candidates, by_filter = {}, {}
    for key in std_keys:
        by_filter[f"standard={key}"] = search_all(client, standard=key)
    by_filter[f"controlForm={MS_CONTROL_FORM}"] = search_all(client, controlForm=MS_CONTROL_FORM)
    by_filter['q="management system"'] = search_all(client, q='"management system"')
    by_filter['q="ledningssystem"'] = search_all(client, q='"ledningssystem"')
    for hits in by_filter.values():
        candidates.update(hits)
    if args.full_scan:
        for org in client.get("/api/org-list", lang="en"):
            candidates.setdefault(org["accNo"], org["orgName"])
    print(f"{len(candidates)} candidate accreditations", file=sys.stderr)

    headers_cache, cases, excluded = {}, [], []
    for acc_no in sorted(candidates, key=lambda a: (candidates[a].casefold(), a)):
        rows = client.get(f"/api/scope-rows/{acc_no}", lang="en")
        ms_rows = [r for r in rows if is_ms_row(r)]
        if not ms_rows:
            reason = "search hit, but no scope line under ISO/IEC 17021-1 or a management system type"
            excluded.append({"ident": acc_no, "company": candidates[acc_no], "reason": reason})
            continue
        case = fetch_case(client, acc_no, headers_cache)
        if any(is_17021(r) for r in ms_rows):
            case["matched_by"] = "standard"
        elif any(r.get("controlFormCode") == MS_CONTROL_FORM for r in ms_rows):
            case["matched_by"] = "control form"
        else:
            case["matched_by"] = "name"
        cases.append(case)
        write_json(out / "cases" / f"{acc_no}.json", case)
        print(f"  {acc_no} {candidates[acc_no]}: {len(ms_rows)}/{len(rows)} lines", file=sys.stderr)

    idents = {c["ident"] for c in cases}
    for name, hits in by_filter.items():
        if name.startswith(("standard=", "controlForm=")) and not set(hits) <= idents:
            sys.exit(f"{name} lists accreditations that were not collected: {set(hits) - idents}")

    reqdocs = client.get("/api/reqdocs", lang="en")
    used = {s for c in cases for r in c["scope_rows"]["en"] for s in r.get("requirementDocSlugs") or []}

    write_json(out / "all_cases.json", cases)
    write_csv(out / "bodies.csv", BODY_COLS, [body_row(c) for c in cases])
    write_csv(out / "scopes.csv", SCOPE_COLS, [r for c in cases for r in scope_rows(c)])
    write_csv(out / "contacts.csv", CONTACT_COLS, [r for c in cases for r in contact_rows(c)])
    write_csv(out / "addresses.csv", ADDRESS_COLS, [r for c in cases for r in address_rows(c)])
    write_csv(out / "scope_columns.csv", COLUMN_COLS, column_rows(headers_cache))
    write_csv(out / "requirement_docs.csv", REQDOC_COLS, reqdoc_rows(reqdocs, used))
    write_csv(out / "excluded_candidates.csv", EXCLUDED_COLS, excluded)
    print(f"Done: {len(cases)} accreditations, {len(excluded)} excluded, in {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
