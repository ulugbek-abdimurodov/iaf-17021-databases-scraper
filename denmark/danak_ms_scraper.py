#!/usr/bin/env python3
"""Scrape DANAK's public registry for management system certification bodies.

Source: the GraphQL API behind https://registry.danak.dk (the page that the
danak.org "Search for accredited companies" form leads to). No login needed.

The registry publishes accreditation scopes as structured data, not as PDF
certificates. Each "scheme" is one annex/scope entry of the accreditation.

Usage:
    pip install requests
    python danak_ms_scraper.py                 # writes to ./danak_ms_output
    python danak_ms_scraper.py --out somewhere --delay 1
    python danak_ms_scraper.py --all-areas     # every accredited company

Output:
    all_cases.json        everything, nested, one entry per accreditation
    cases/<ident>.json    the same, one file per accreditation
    bodies.csv            one row per accreditation (company, contact, dates)
    scopes.csv            one row per scope entry / annex line
    contacts.csv          all listed contact people
    addresses.csv         all listed locations
    method_lists.csv      detailed method list rows, where a case has any
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

API = os.environ.get("DANAK_API", "https://api.registry.danak.dk/graphql")
REGISTRY = "https://registry.danak.dk/registry"
ISO_17021_GROUP = 10          # DS/EN ISO/IEC 17021-1:2015
MS_IDENT_PREFIXES = ("01-5", "01-6")  # catches 01-5026, which has no standard set

ADDRESS = "addressId serial department street street2 postal city countryCode country"
CONTACT = "contactId serial contactTypeId name web email phone"

LIST_QUERY = "{ allCases { totalCount nodes { id ident accStd } } }"

CASE_QUERY = """
query($id: Int!) {
  allCases(condition: {id: $id}) { nodes {
    id customerId ident serial accStd state name title standardHeader
    createdAt startedAt renewedAt expireAt closedAt
    scheme_group { id name short title titleDa header headerDa eaMla iafMla ilacMla
                   preDescription preDescriptionDa postDescription postDescriptionDa
                   accAreaTitle accAreaTitleDa expireAt }
    customer { nodes { customerId contactId serial name department
      address { %(address)s contact { %(contact)s } }
      contacts { nodes { %(contact)s } } } }
    addresses { nodes { %(address)s contact { %(contact)s } } }
    schemes(orderBy: ORDINAL_ASC) { nodes {
      schemeId parentSchemeId serial formatValue title column1Header column2Header
      commentHeader publishedAt ordinal
      format { kind description columnCount }
      scheme_details { nodes { serial title preDescr descr comment preData postData } }
      scheme_items(orderBy: ORDINAL_ASC) { nodes { serial column1 column2 comment ordinal } }
    } }
    attributes { nodes { attributeId serial isMethodList isNote kind lang label description ordinal } }
    notes { nodes { attributeId lang serial label description ordinal } }
    method_lists { nodes { attributeId lang kindValue serial label description ordinal
      kind { kind name headers }
      items { nodes { id serial lang kindValue data ordinal } } } }
    tags { nodes { serial tag kind value } }
  } }
}
""" % {"address": ADDRESS, "contact": CONTACT}


class Client:
    def __init__(self, delay, retries=4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "danak-ms-scraper/1.0"
        self.delay = delay
        self.retries = retries

    def query(self, query, variables=None):
        for attempt in range(self.retries):
            try:
                resp = self.session.post(
                    API, json={"query": query, "variables": variables or {}}, timeout=60
                )
                resp.raise_for_status()
                body = resp.json()
                if body.get("errors"):
                    raise RuntimeError(f"GraphQL error: {body['errors'][0]['message']}")
                time.sleep(self.delay)
                return body["data"]
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                print(f"  retry in {wait}s: {exc}", file=sys.stderr)
                time.sleep(wait)


def decode(value):
    """Many API fields are JSON stored as strings, such as '{"da":"..","en":".."}'."""
    if isinstance(value, dict):
        # Connections are flattened so callers see plain lists.
        if set(value) == {"nodes"}:
            return [decode(v) for v in value["nodes"]]
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return decode(json.loads(value))
        except ValueError:
            return value
    return value


def text(value, lang="en"):
    """Plain text from a {da, en} field, falling back to the other language."""
    if isinstance(value, dict):
        value = value.get(lang) or value.get("en") or value.get("da") or ""
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(text(v, lang) for v in value)
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    value = re.sub(r"<br\s*/?>|</p>|</li>|</tr>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def join_address(addr):
    if not addr:
        return ""
    place = " ".join(x for x in (addr.get("postal"), addr.get("city")) if x)
    parts = (addr.get("department"), addr.get("street"), addr.get("street2"), place,
             addr.get("country"))
    return ", ".join(x for x in parts if x)


def main_contact(customer):
    """The contact the registry page shows; a company can have several."""
    contacts = customer.get("contacts") or []
    for contact in contacts:
        if contact.get("contactId") == customer.get("contactId"):
            return contact
    return (customer.get("address") or {}).get("contact") or (contacts[0] if contacts else {})


def website(customer, contact):
    if contact.get("web"):
        return contact["web"]
    return next((c["web"] for c in customer.get("contacts") or [] if c.get("web")), "")


def tag_value(case, name):
    wanted = f"<[{name}]>"
    for tag in case.get("tags") or []:
        if tag.get("tag") == wanted:
            return text(tag.get("value"))
    return ""


def body_row(case):
    customer = (case.get("customer") or [{}])[0]
    contact = main_contact(customer)
    group = case.get("scheme_group") or {}
    return {
        "ident": case["ident"],
        "url": f"{REGISTRY}/{case['serial']}",
        "company": text(customer.get("name")),
        "accreditation_name": text(case.get("name")),
        "state": text(case.get("state")),
        "standard": group.get("name") or text(case.get("title")),
        "cvr": tag_value(case, "CVR"),
        "address": join_address(customer.get("address")),
        "contact_name": contact.get("name") or "",
        "phone": contact.get("phone") or "",
        "email": contact.get("email") or "",
        "website": website(customer, contact),
        "started": (case.get("startedAt") or "")[:10],
        "renewed": (case.get("renewedAt") or "")[:10],
        "expires": (case.get("expireAt") or "")[:10],
        "scope_entries": len(case.get("schemes") or []),
    }


def scope_rows(case):
    company = text((case.get("customer") or [{}])[0].get("name"))
    for scheme in case.get("schemes") or []:
        base = {
            "ident": case["ident"],
            "company": company,
            "scheme_id": scheme["schemeId"],
            "parent_scheme_id": scheme.get("parentSchemeId") or "",
            "scheme_title": text(scheme.get("title")),
            "format": scheme.get("formatValue") or "",
            "scheme_url": f"{REGISTRY}/{case['serial']}/scheme/{case['serial']}-{scheme['schemeId']}",
            "published": (scheme.get("publishedAt") or "")[:10],
            "column1_header": text(scheme.get("column1Header")),
            "column2_header": text(scheme.get("column2Header")),
        }
        rows = []
        for detail in scheme.get("scheme_details") or []:
            rows.append({"row_type": "detail", "column1": text(detail.get("title")),
                         "column2": text(detail.get("descr")),
                         "comment": text(detail.get("comment"))})
        for item in scheme.get("scheme_items") or []:
            rows.append({"row_type": "item", "column1": text(item.get("column1")),
                         "column2": text(item.get("column2")),
                         "comment": text(item.get("comment"))})
        for row in rows or [{"row_type": "scheme", "column1": "", "column2": "", "comment": ""}]:
            yield {**base, **row}


def address_rows(case):
    company = text((case.get("customer") or [{}])[0].get("name"))
    for addr in case.get("addresses") or []:
        contact = addr.get("contact") or {}
        yield {"ident": case["ident"], "company": company,
               "department": addr.get("department") or "", "street": addr.get("street") or "",
               "street2": addr.get("street2") or "", "postal": addr.get("postal") or "",
               "city": addr.get("city") or "", "country": addr.get("country") or "",
               "contact_name": contact.get("name") or "", "email": contact.get("email") or "",
               "phone": contact.get("phone") or ""}


def contact_rows(case):
    customer = (case.get("customer") or [{}])[0]
    for contact in customer.get("contacts") or []:
        yield {"ident": case["ident"], "company": text(customer.get("name")),
               "name": contact.get("name") or "", "phone": contact.get("phone") or "",
               "email": contact.get("email") or "", "website": contact.get("web") or ""}


def method_rows(case):
    for mlist in case.get("method_lists") or []:
        for item in mlist.get("items") or []:
            yield {"ident": case["ident"], "lang": mlist.get("lang") or "",
                   "list_kind": mlist.get("kindValue") or "", "list_label": text(mlist.get("label")),
                   "serial": item.get("serial"),
                   "data": json.dumps(item.get("data"), ensure_ascii=False)}


def write_csv(path, rows):
    rows = list(rows)
    fields = []
    for row in rows:
        fields.extend(k for k in row if k not in fields)
    # utf-8-sig so Excel reads Danish characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def is_ms(case):
    return case["accStd"] == ISO_17021_GROUP or case["ident"].startswith(MS_IDENT_PREFIXES)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="danak_ms_output", type=Path)
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--all-areas", action="store_true",
                        help="scrape every accredited company, not only management systems")
    args = parser.parse_args()

    client = Client(args.delay)
    listing = client.query(LIST_QUERY)["allCases"]
    nodes = listing["nodes"]
    if len(nodes) != listing["totalCount"]:
        sys.exit(f"Listing incomplete: got {len(nodes)} of {listing['totalCount']}")
    chosen = sorted((c for c in nodes if args.all_areas or is_ms(c)), key=lambda c: c["ident"])
    print(f"{len(chosen)} of {len(nodes)} accreditations selected")

    (args.out / "cases").mkdir(parents=True, exist_ok=True)
    cases = []
    for number, stub in enumerate(chosen, 1):
        print(f"[{number}/{len(chosen)}] {stub['ident']}")
        case = decode(client.query(CASE_QUERY, {"id": stub["id"]})["allCases"])[0]
        cases.append(case)
        with open(args.out / "cases" / f"{case['ident']}.json", "w", encoding="utf-8") as handle:
            json.dump(case, handle, ensure_ascii=False, indent=2)

    with open(args.out / "all_cases.json", "w", encoding="utf-8") as handle:
        json.dump(cases, handle, ensure_ascii=False, indent=2)
    counts = {
        "bodies.csv": write_csv(args.out / "bodies.csv", map(body_row, cases)),
        "scopes.csv": write_csv(args.out / "scopes.csv", (r for c in cases for r in scope_rows(c))),
        "contacts.csv": write_csv(args.out / "contacts.csv", (r for c in cases for r in contact_rows(c))),
        "addresses.csv": write_csv(args.out / "addresses.csv", (r for c in cases for r in address_rows(c))),
        "method_lists.csv": write_csv(args.out / "method_lists.csv", (r for c in cases for r in method_rows(c))),
    }
    for name, count in counts.items():
        print(f"{name}: {count} rows")
    print(f"Done: {args.out.resolve()}")


if __name__ == "__main__":
    main()
