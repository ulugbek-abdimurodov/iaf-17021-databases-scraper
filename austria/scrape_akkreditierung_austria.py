#!/usr/bin/env python3
"""Scrape certification bodies from the Akkreditierung Austria public register.

Default target: "Certification Body for Managementsystems" (program 928).
Standard library only. Requires Python 3.9+.

    python scrape_akkreditierung_austria.py
    python scrape_akkreditierung_austria.py --out data --delay 0.5
    python scrape_akkreditierung_austria.py --program-id 0     # every program

If you get a certificate error, run this once and try again:

    python -m pip install truststore

The script then checks certificates through your operating system, as your browser does.

Output:
    bodies.csv             one row per body
    scopes.csv             one row per accredited/applicable standard
    technical_fields.csv   technical fields per scope
    scope_attributes.csv   certification schemes, sectors, comments per scope
    contacts.csv           public phones, emails, websites per body
    addresses.csv          public addresses per body
    documents.csv          published documents, with local path
    documents/<body id>/   the downloaded documents
    json/bodies/<id>.json  each body with all its scopes
    json/scopes/<id>.json  each scope record
    programs.json          accreditation programs
    summary.json           counts and any errors

Only data the register displays publicly is saved. The API also returns attribute
values with no public attribute type, which the website does not show. These are
removed, along with internal audit metadata.
"""
import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://akkreditierung-austria.gv.at"
MANAGEMENT_SYSTEMS_PROGRAM = 928
PAGE_SIZE = 100
RETRIES = 4
USER_AGENT = "akkreditierung-register-scraper/1.0"


CERTIFICATE_HELP = """
Could not verify the site's HTTPS certificate: {error}

Python often fails this check when a server doesn't send its full certificate
chain, even though browsers accept the site. To fix it, run this once and try again:

    python -m pip install truststore

Or point to a PEM file containing the missing certificates:

    python scrape_akkreditierung_austria.py --ca-bundle path\\to\\certificates.pem
"""


def make_ssl_context(ca_bundle=None):
    """Always verifies certificates. Uses the OS trust store when truststore is installed."""
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class Client:
    def __init__(self, base_url, delay, timeout=60, ssl_context=None):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self.ssl_context = ssl_context

    def get(self, path, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=self.ssl_context) as response:
                    body = response.read()
                time.sleep(self.delay)
                return body
            except urllib.error.HTTPError as err:
                if err.code not in (429, 500, 502, 503, 504) or attempt == RETRIES:
                    raise
            except (urllib.error.URLError, TimeoutError) as err:
                # A certificate failure won't fix itself, so don't retry it
                if isinstance(getattr(err, "reason", None), ssl.SSLCertVerificationError):
                    raise err.reason
                if attempt == RETRIES:
                    raise
            time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def get_json(self, path, params=None):
        return json.loads(self.get(path, params))


def list_scopes(client, program_id, statuses):
    """Return every list record, following pagination and dropping duplicates."""
    records = {}
    page = 0
    while True:
        params = {"statusList": statuses, "sort": "documentNumber,asc",
                  "size": PAGE_SIZE, "page": page}
        if program_id:
            params["programId"] = program_id
        batch = client.get_json("/api/accreditationCabRevisions", params)
        new = [r for r in batch if r["cabScopeRevisionId"] not in records]
        for record in new:
            records[record["cabScopeRevisionId"]] = record
        print(f"  page {page}: {len(batch)} rows, {len(records)} unique", flush=True)
        if len(batch) < PAGE_SIZE or not new:
            return list(records.values())
        page += 1


def strip_audit(value):
    if isinstance(value, dict):
        return {k: strip_audit(v) for k, v in value.items() if k != "audit"}
    if isinstance(value, list):
        return [strip_audit(v) for v in value]
    return value


def public_only(scope):
    """Keep only what the register displays publicly."""
    scope = strip_audit(scope)
    types = [t for t in scope.get("attributeTypes") or [] if t.get("publicVisibility")]
    public_ids = {str(t["id"]) for t in types}
    scope["attributeTypes"] = types
    scope["attributeMap"] = {k: v for k, v in (scope.get("attributeMap") or {}).items()
                             if k in public_ids}
    for key in ("contacts", "addresses"):
        scope[key] = [c for c in scope.get(key) or [] if c.get("publicVisibility")]
    return scope


def display_status(scope):
    """Label shown by the website. Type N rows show Accredited, others Applicable."""
    status = scope.get("status")
    if status != "VALID":
        return (status or "").capitalize()
    return "Accredited" if scope.get("type") == "N" else "Applicable"


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "document").strip(" .")
    return name[:180] or "document"


def download_documents(client, scope, out_dir, errors):
    rows = []
    for item in scope.get("additionalDocuments") or []:
        doc_id = item["cabAdditionalDocumentId"]
        info = item.get("document") or {}
        folder = out_dir / "documents" / safe_name(scope["cabPsid"])
        path = folder / f"{doc_id}_{safe_name(info.get('fileName'))}"
        expected = info.get("contentSize")
        try:
            if not (path.exists() and path.stat().st_size == expected):
                data = client.get(f"/api/shared/cabAdditionalDocument/{doc_id}")
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            saved = str(path.relative_to(out_dir))
        except Exception as err:  # keep going and report at the end
            errors.append(f"document {doc_id}: {err}")
            saved = ""
        rows.append({"body_id": scope["cabPsid"],
                     "scope_id": scope["cabScopeRevisionId"],
                     "standard": scope.get("docNr"),
                     "document_id": doc_id,
                     "title": info.get("title"),
                     "file_name": info.get("fileName"),
                     "size_bytes": expected,
                     "local_path": saved})
    return rows


def write_csv(path, columns, rows):
    # utf-8-sig so Excel displays umlauts correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def unique_by(rows, keys):
    seen = {}
    for row in rows:
        seen.setdefault(tuple(row[k] for k in keys), row)
    return list(seen.values())


def build_tables(scopes):
    tables = defaultdict(list)
    for s in scopes:
        body, scope_id = s["cabPsid"], s["cabScopeRevisionId"]
        program = s.get("programDTO") or {}
        tables["scopes"].append({
            "body_id": body, "body_name": s.get("cabName"), "scope_id": scope_id,
            "organization": s.get("orgName"), "standard": s.get("docNr"),
            "standard_title": s.get("docTitle"), "issue_date": s.get("issueDate"),
            "display_status": display_status(s), "status": s.get("status"),
            "type": s.get("type"), "program": program.get("nameEn"),
            "program_de": program.get("nameDe"),
            "accreditation_standard": s.get("programStandard"),
            "initial_accreditation": s.get("cabStartDate"),
            "last_decision": s.get("lastDecisionDate"),
            "on_site_inspection": s.get("onSiteInspection"),
            "flexible": s.get("flexible"),
            "url": f"{BASE_URL}/overview/{scope_id}"})
        for field in s.get("icsDTOs") or []:
            tables["fields"].append({
                "body_id": body, "scope_id": scope_id, "standard": s.get("docNr"),
                "field_number": field.get("icsNumber"), "title_en": field.get("titleEn"),
                "title_de": field.get("titleDe"), "notified_body": field.get("notifiedBody")})
        for attr in sorted(s.get("attributeTypes") or [], key=lambda a: a.get("sortKey") or 0):
            value = s["attributeMap"].get(str(attr["id"]))
            if value not in (None, ""):
                tables["attributes"].append({
                    "body_id": body, "scope_id": scope_id, "standard": s.get("docNr"),
                    "attribute_en": attr.get("nameEn"), "attribute_de": attr.get("name"),
                    "value": value})
        for contact in s.get("contacts") or []:
            tables["contacts"].append({"body_id": body, "body_name": s.get("cabName"),
                                       "type": contact.get("type"),
                                       "value": contact.get("value")})
        for addr in s.get("addresses") or []:
            tables["addresses"].append({"body_id": body, "body_name": s.get("cabName"),
                                        "type": addr.get("type"), "street": addr.get("street"),
                                        "postal_code": addr.get("postalCode"),
                                        "city": addr.get("city"), "country": addr.get("country")})
    tables["contacts"] = unique_by(tables["contacts"], ["body_id", "type", "value"])
    tables["addresses"] = unique_by(tables["addresses"],
                                    ["body_id", "type", "street", "postal_code", "city"])
    return tables


def build_bodies(scopes, tables):
    grouped = defaultdict(list)
    for s in scopes:
        grouped[s["cabPsid"]].append(s)
    rows = []
    for body_id, items in sorted(grouped.items()):
        first = items[0]
        contacts = [c for c in tables["contacts"] if c["body_id"] == body_id]
        values = lambda kind: "; ".join(c["value"] for c in contacts if c["type"] == kind)
        decisions = [s.get("lastDecisionDate") for s in items if s.get("lastDecisionDate")]
        rows.append({
            "body_id": body_id, "name": first.get("cabName"),
            "legal_entity": first.get("orgName"), "street": first.get("orgBusinessStreetAndNr"),
            "postal_code": first.get("orgBusinessPostCode"), "city": first.get("orgBusinessCity"),
            "country": first.get("orgBusinessCountry"), "website": first.get("orgBusinessWebsite"),
            "phones": values("PHONE_BUSINESS"), "emails": values("EMAIL_BUSINESS"),
            "initial_accreditation": first.get("cabStartDate"),
            "latest_decision": max(decisions, key=lambda d: datetime.strptime(d, "%d.%m.%Y"),
                                   default=""),
            "accredited_standards": sum(display_status(s) == "Accredited" for s in items),
            "applicable_documents": sum(display_status(s) == "Applicable" for s in items),
            "published_documents": sum(len(s.get("additionalDocuments") or []) for s in items)})
    return rows, grouped


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="akkreditierung_output", type=Path)
    parser.add_argument("--program-id", type=int, default=MANAGEMENT_SYSTEMS_PROGRAM,
                        help="accreditation program, 0 for all (default: 928)")
    parser.add_argument("--statuses", default="VALID,REVOKED,SUSPENDED")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between requests")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--ca-bundle", help="PEM file of certificates to trust")
    args = parser.parse_args()

    client = Client(args.base_url, args.delay, ssl_context=make_ssl_context(args.ca_bundle))
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    errors = []

    try:
        programs = client.get_json("/api/programs")
    except ssl.SSLCertVerificationError as err:
        print(CERTIFICATE_HELP.format(error=err.verify_message), file=sys.stderr)
        return 2
    write_json(out / "programs.json", strip_audit(programs))

    print("Listing scopes...", flush=True)
    listed = list_scopes(client, args.program_id, args.statuses)

    print(f"Fetching {len(listed)} scope details...", flush=True)
    scopes, document_rows = [], []
    for index, record in enumerate(listed, 1):
        scope_id = record["cabScopeRevisionId"]
        try:
            detail = client.get_json(f"/api/accreditationCabRevisions/{scope_id}")
        except Exception as err:
            errors.append(f"scope {scope_id}: {err}; used the list record instead")
            detail = record
        scope = public_only(detail)
        scopes.append(scope)
        write_json(out / "json" / "scopes" / f"{scope_id}.json", scope)
        document_rows += download_documents(client, scope, out, errors)
        if index % 25 == 0 or index == len(listed):
            print(f"  {index}/{len(listed)}", flush=True)

    tables = build_tables(scopes)
    bodies, grouped = build_bodies(scopes, tables)
    for body in bodies:
        write_json(out / "json" / "bodies" / f"{safe_name(body['body_id'])}.json",
                   {**body, "scopes": grouped[body["body_id"]]})

    write_csv(out / "bodies.csv", list(bodies[0]) if bodies else ["body_id"], bodies)
    write_csv(out / "scopes.csv",
              list(tables["scopes"][0]) if tables["scopes"] else ["scope_id"], tables["scopes"])
    write_csv(out / "technical_fields.csv",
              ["body_id", "scope_id", "standard", "field_number", "title_en", "title_de",
               "notified_body"], tables["fields"])
    write_csv(out / "scope_attributes.csv",
              ["body_id", "scope_id", "standard", "attribute_en", "attribute_de", "value"],
              tables["attributes"])
    write_csv(out / "contacts.csv", ["body_id", "body_name", "type", "value"], tables["contacts"])
    write_csv(out / "addresses.csv",
              ["body_id", "body_name", "type", "street", "postal_code", "city", "country"],
              tables["addresses"])
    write_csv(out / "documents.csv",
              ["body_id", "scope_id", "standard", "document_id", "title", "file_name",
               "size_bytes", "local_path"], document_rows)

    summary = {"scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "program_id": args.program_id, "bodies": len(bodies), "scopes": len(scopes),
               "documents": len(document_rows), "errors": errors}
    write_json(out / "summary.json", summary)
    print(f"Done: {len(bodies)} bodies, {len(scopes)} scopes, {len(document_rows)} documents, "
          f"{len(errors)} errors. Saved to {out}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())