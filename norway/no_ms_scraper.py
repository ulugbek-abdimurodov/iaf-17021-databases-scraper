#!/usr/bin/env python3
"""Scrape management system certification bodies from Norsk Akkreditering.

Registry: https://www.akkreditert.no/en/akkrediterte-organisasjoner/?scope=SysCert

Read-only. The site has no API: the listing and the per-standard filter are
ASP.NET WebForms pages and each scope is an HTML page. The per-standard filter
is a search form post, nothing on the site is changed.

    pip install requests beautifulsoup4
    python no_ms_scraper.py --out no_ms_output --delay 0.5
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.akkreditert.no"
LIST_PATH = "/en/akkrediterte-organisasjoner/"
RECORD_PATHS = {
    "en": "/en/akkrediterte-organisasjoner/system/?AkkId={id}",
    "no": "/akkrediterte-organisasjoner/system/?AkkId={id}",
}
OTHER_SCOPES = ["Inspection", "PersCert", "ProdCert", "Ets", "Glp", "Slp",
                "Labs", "Calibration", "MedLab", "BioBank"]
# Record pages of these scopes are opened to look for ISO/IEC 17021 text.
SCAN_RECORD_SCOPES = ["Inspection", "PersCert", "ProdCert", "Ets"]
STATUS = {"A": "Active"}  # the only code seen on the site; others kept raw
USER_AGENT = "no-ms-registry-scraper/1.0"
MAX_PAGES = 50


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


class Client:
    def __init__(self, delay, retries=4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = max(delay, 0.5)
        self.retries = retries

    def request(self, method, path, **kw):
        url = urljoin(BASE, path)
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.request(method, url, timeout=60, **kw)
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    time.sleep(self.delay)
                    return resp.text
                error = f"HTTP {resp.status_code}"
            except requests.HTTPError:
                raise
            except requests.RequestException as exc:
                error = str(exc)
            if attempt == self.retries:
                raise RuntimeError(f"{method} {url} failed: {error}")
            time.sleep(self.delay * 2 ** (attempt + 1))

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, data):
        return self.request("POST", path, data=data)


def parse_listing(html, marker="system/"):
    """Return {href: (code, name)} for the record links on a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for link in soup.select("a[href*='AkkId']"):
        href = link["href"]
        if marker in href:
            found.setdefault(href, []).append(clean(link.get_text()))
    return {h: (v[0], v[1] if len(v) > 1 else "") for h, v in found.items()}


def fetch_listing(client, scope):
    rows = {}
    for page in range(1, MAX_PAGES + 1):
        page_rows = parse_listing(
            client.get(f"{LIST_PATH}?scope={scope}&p={page}"), "AkkId")
        fresh = {h: v for h, v in page_rows.items() if h not in rows}
        if not fresh:
            return rows
        rows.update(fresh)
    raise RuntimeError(f"{scope}: more than {MAX_PAGES} listing pages")


def akk_id(href):
    match = re.search(r"AkkId=(\d+)", href)
    if not match:
        raise RuntimeError(f"No AkkId in link {href}")
    return match.group(1)


def fetch_by_standard(client):
    """Run the search once per standard, to catch records missing from the main list."""
    html = client.get(f"{LIST_PATH}?scope=SysCert")
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    select = soup.find("select", attrs={"name": re.compile(r"ddlStandards$")})
    if form is None or select is None:
        raise RuntimeError("Search form or standards dropdown not found")
    fields = {i["name"]: i.get("value", "")
              for i in form.select("input[type=hidden]") if i.get("name")}
    results = {}
    for option in select.find_all("option"):
        data = dict(fields, __EVENTTARGET=select["name"])
        data[select["name"]] = option["value"]
        rows = parse_listing(client.post(form.get("action") or LIST_PATH, data))
        results[option["value"]] = {"standard": clean(option.get_text()), "rows": rows}
    return results


def parse_date(raw):
    for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except (TypeError, ValueError):
            pass
    return raw or ""


def parse_record(html):
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.calscopepageview")
    if article is None:
        raise RuntimeError("Scope article not found")
    top = article.select_one("section.accreditatedscope-top")
    status = soup.select_one("[id$=hdnOrgAccStatus]")
    rec = {"status_code": status.get("value", "") if status else ""}

    heads = [clean(h.get_text()) for h in top.find_all("h3")]
    rec["ident"] = clean(top.find("h1").get_text())
    rec["company"] = heads[0] if heads else ""
    rec["company_extra"] = " ".join(h for h in heads[1:] if h)

    address = top.find("address")
    para = address.find("p") if address else None
    lines = [clean(s) for s in para.stripped_strings] if para else []
    rec["address_lines"] = lines
    rec["phone"] = rec["email"] = rec["website"] = ""
    for span in address.find_all("span") if address else []:
        if span.select_one(".icon-telephone"):
            strong = span.find("strong")
            if strong:
                strong.extract()
            rec["phone"] = clean(span.get_text())
        elif span.select_one(".icon-sendmail"):
            link = span.find("a")
            rec["email"] = clean(link.get_text()) if link else ""
        elif span.select_one(".icon-earth"):
            link = span.find("a")
            rec["website"] = link.get("href", "") if link else ""

    text = clean(top.get_text(" "))
    match = re.search(r"(?:meets the requirements in|tilfredsstiller kravene i)\s+(.+?)\s+"
                      r"(?:Accreditation was first|Akkreditering ble)", text)
    rec["standard"] = match.group(1) if match else ""
    match = re.search(r"(?:first granted|første gang innvilget):\s*(\S+)", text)
    rec["started"] = parse_date(match.group(1) if match else "")
    match = re.search(r"(?:valid to|gyldig til):\s*(\S+)", text)
    rec["expires"] = parse_date(match.group(1) if match else "")
    dates = article.select_one(".accreditationdates")
    rec["statement"] = clean(dates.get_text(" ")) if dates else ""

    rec["units"] = []
    for area in article.select(".scopetoparea"):
        parts = [", ".join(clean(t) for t in s.stripped_strings) for s in area.select("span.text-bold")]
        rec["units"].append({"name": parts[0] if parts else "",
                             "address": parts[1] if len(parts) > 1 else ""})

    rec["schemes"] = []
    current = None
    children = [child for table in article.select(".systemcertscope > .scopetable")
                for child in table.find_all("div", recursive=False)]
    for child in children:
        classes = child.get("class", [])
        if "tabledata" in classes:
            cells = [clean(c.get_text(" ")) for c in child.find_all(class_="tablecell", recursive=False)]
            cells += [""] * (3 - len(cells))
            current = {"standard": cells[0], "description": cells[1], "remarks": cells[2],
                       "codes_intro": "", "codes": []}
            rec["schemes"].append(current)
        elif "detailrow" in classes and current is not None:
            intro = child.select_one(".scopeinfotext")
            current["codes_intro"] = clean(intro.get_text(" ")) if intro else ""
            for row in child.select(".ets-table > .tabledata"):
                cells = [clean(c.get_text(" ")) for c in row.find_all(class_="tablecell", recursive=False)]
                cells += [""] * (2 - len(cells))
                current["codes"].append({"code": cells[0], "description": cells[1]})

    rec["pdf_links"] = sorted(set(re.findall(r"[^\"' ]+\.pdf", html, flags=re.I)))
    rec["scope_entries"] = sum(max(len(s["codes"]), 1) for s in rec["schemes"])
    return rec


def cross_check_other_scopes(client):
    """Look for ISO/IEC 17021 or management system records listed under other scopes."""
    review = []
    for scope in OTHER_SCOPES:
        rows = fetch_listing(client, scope)
        for href, (code, name) in rows.items():
            entry = {"scope": scope, "code": code, "name": name, "url": urljoin(BASE, href),
                     "name_match": bool(re.search(r"management system|ledelsessystem", name, re.I)),
                     "text_17021": None, "text_management_system": None}
            if scope in SCAN_RECORD_SCOPES:
                text = BeautifulSoup(client.get(href), "html.parser").get_text(" ")
                entry["text_17021"] = "17021" in text
                entry["text_management_system"] = bool(
                    re.search(r"management system|ledelsessystem", text, re.I))
            if entry["name_match"] or entry["text_17021"] or entry["text_management_system"]:
                review.append(entry)
    return review


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(out, cases, review):
    (out / "cases").mkdir(parents=True, exist_ok=True)
    (out / "all_cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), "utf-8")
    bodies, scopes, contacts, addresses = [], [], [], []
    for case in cases:
        name = case["ident"].replace(" ", "-")
        (out / "cases" / f"{name}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2), "utf-8")
        en = case["en"]
        bodies.append({
            "ident": case["ident"], "url": case["url"], "company": en["company"],
            "accreditation_name": "Management Systems", "state": case["state"],
            "standard": en["standard"], "cvr": "",  # no company number on the site
            "address": ", ".join(en["address_lines"]), "contact_name": "",
            "phone": en["phone"], "email": en["email"], "website": en["website"],
            "started": en["started"], "renewed": "", "expires": en["expires"],
            "scope_entries": en["scope_entries"],
        })
        contacts.append({"ident": case["ident"], "company": en["company"], "phone": en["phone"],
                         "email": en["email"], "website": en["website"]})
        for unit in en["units"] or [{"name": "", "address": ""}]:
            addresses.append({"ident": case["ident"], "company": en["company"],
                              "postal_address": ", ".join(en["address_lines"]),
                              "unit": unit["name"], "unit_address": unit["address"]})
        for scheme in en["schemes"]:
            common = {"ident": case["ident"], "company": en["company"],
                      "scheme_title": scheme["standard"], "scheme_url": case["url"], "published": ""}
            scopes.append(dict(common, row_type="standard", column1=scheme["description"],
                               column2="", comment=scheme["remarks"]))
            for code in scheme["codes"]:
                scopes.append(dict(common, row_type="scope_code", column1=code["code"],
                                   column2=code["description"], comment=""))
    write_csv(out / "bodies.csv", ["ident", "url", "company", "accreditation_name", "state", "standard",
                                   "cvr", "address", "contact_name", "phone", "email", "website",
                                   "started", "renewed", "expires", "scope_entries"], bodies)
    write_csv(out / "scopes.csv", ["ident", "company", "scheme_title", "scheme_url", "published",
                                   "row_type", "column1", "column2", "comment"], scopes)
    write_csv(out / "contacts.csv", ["ident", "company", "phone", "email", "website"], contacts)
    write_csv(out / "addresses.csv", ["ident", "company", "postal_address", "unit", "unit_address"], addresses)
    write_csv(out / "other_scope_review.csv",
              ["scope", "code", "name", "url", "name_match", "text_17021", "text_management_system"], review)
    return len(bodies), len(scopes)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="no_ms_output", type=Path)
    parser.add_argument("--delay", default=0.5, type=float, help="seconds between requests (minimum 0.5)")
    parser.add_argument("--skip-cross-check", action="store_true",
                        help="do not review other scopes for 17021 records")
    args = parser.parse_args()
    client = Client(args.delay)

    listing = parse_listing(client.get(f"{LIST_PATH}?scope=SysCert"))
    paged = {h: v for h, v in fetch_listing(client, "SysCert").items() if "system/" in h}
    listing.update(paged)
    by_standard = fetch_by_standard(client)
    union = {}
    for result in by_standard.values():
        union.update(result["rows"])
    print(f"Listing: {len(listing)} records. Standards search: {len(union)} across {len(by_standard)} standards.")
    if not listing:
        sys.exit("Listing is empty, stopping.")
    listed_ids = {akk_id(h) for h in listing}
    extra = {h: v for h, v in union.items() if akk_id(h) not in listed_ids}
    missing = listed_ids - {akk_id(h) for h in union}
    if extra or missing:
        sys.exit(f"Incomplete listing: only in standards search {extra}, only in main list {missing}")

    cases = []
    for href, (code, name) in sorted(listing.items(), key=lambda kv: kv[1][0]):
        record_id = akk_id(href)
        en = parse_record(client.get(RECORD_PATHS["en"].format(id=record_id)))
        no = parse_record(client.get(RECORD_PATHS["no"].format(id=record_id)))
        if en["ident"] != code:
            sys.exit(f"Record {record_id}: page says {en['ident']}, listing says {code}")
        cases.append({
            "ident": code, "akk_id": record_id, "listed_name": name,
            "url": urljoin(BASE, RECORD_PATHS["en"].format(id=record_id)),
            "state": STATUS.get(en["status_code"], en["status_code"] or "Unknown"),
            "en": en, "no": no,
        })
        print(f"  {code}: {en['company']} ({en['scope_entries']} scope entries)")

    review = [] if args.skip_cross_check else cross_check_other_scopes(client)
    bodies, scopes = write_outputs(args.out, cases, review)
    pdfs = sum(len(c["en"]["pdf_links"]) for c in cases)
    print(f"Done: {bodies} bodies, {scopes} scope rows, {pdfs} PDF links, "
          f"{len(review)} records for other-scope review. Output in {args.out}")


if __name__ == "__main__":
    main()
