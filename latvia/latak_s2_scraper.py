#!/usr/bin/env python3
"""Scrape Latvian (LATAK) accredited bodies of one scope, by default
S2 = management system certification bodies (ISO/IEC 17021-1).

The site's tables load from a JSON endpoint and each body has one PDF that holds
the accreditation certificate (portrait pages) followed by its annex (landscape
pages). For every body this script saves the table data, the original PDF, the
PDF split into certificate and annex, and the extracted text and tables.

    pip install requests beautifulsoup4 pypdf pdfplumber
    python latak_s2_scraper.py                  # writes to ./latak_S2
    python latak_s2_scraper.py --scope S1 -o s1 # another scope, e.g. S1, S3, I, T

Output:
    bodies.json / bodies.csv     all bodies, with fields parsed from the certificate
    raw_tables/*.json            the unmodified JSON from the site
    <ID>/<ID>.pdf                original PDF
    <ID>/<ID>_certificate.pdf    certificate pages
    <ID>/<ID>_annex.pdf          annex pages
    <ID>/<ID>_text.txt           text of every page
    <ID>/<ID>_annex_tables.csv   annex tables, cell by cell

Exit code is 1 if any body or file failed; the run's problems are listed in
bodies.json under "errors".
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.latak.gov.lv"
# Listing page -> status. Table ids are read from these pages; the fallbacks are
# the ids seen on 2026-11-04, used only if the page markup changes.
LISTINGS = {
    "active": ("/lv/speka-esosas-akreditacijas", "2060"),
    "inactive": ("/lv/speka-neesosas-akreditacijas", "2084"),
}
TABLE_ENDPOINT = "/lv/ajax/interactive-table/{}"
TABLE_ID_RE = re.compile(r'data-paragraph-actions-id="(\d+)"')

# Header text on the site -> stable key. Active and inactive tables differ.
FIELD_KEYS = [
    ("inst.nr", "id"),
    ("reģ. nr", "id"),
    ("institūcijas nosaukums", "name"),
    ("juridiskā adrese", "addresses"),
    ("tālr", "phone"),
    ("akreditētā sfēra", "scope"),
    ("akr.termiņš", "valid_until"),
    ("apliecība", "certificate_column"),
    ("lēmuma datums", "decision_date"),
    ("piezīmes", "notes"),
]


def log(message):
    print(message, file=sys.stderr, flush=True)


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "latak-registry-scraper/1.0"
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(str(text), "html.parser").get_text(" ")).strip()


def field_key(header):
    lowered = re.sub(r"\s+", " ", header).strip().lower()
    for prefix, key in FIELD_KEYS:
        if lowered.startswith(prefix):
            return key
    return lowered


def extract_links(cell, base_url):
    soup = BeautifulSoup(str(cell), "html.parser")
    return [
        {"text": a.get_text(" ", strip=True), "url": urljoin(base_url + "/", a["href"])}
        for a in soup.find_all("a", href=True)
    ]


def discover_table_id(session, base_url, path, fallback):
    try:
        response = session.get(base_url + path, timeout=60)
        response.raise_for_status()
        found = TABLE_ID_RE.findall(response.text)
        if found:
            return found[0]
    except requests.RequestException as exc:
        log(f"  could not read {path} ({exc}); using table id {fallback}")
    return fallback


def fetch_table(session, base_url, table_id):
    response = session.get(base_url + TABLE_ENDPOINT.format(table_id), timeout=120)
    response.raise_for_status()
    table = response.json()  # a maintenance page is HTML and fails here
    if not isinstance(table.get("body"), list) or not isinstance(table.get("header"), list):
        raise ValueError(f"table {table_id}: unexpected JSON shape")
    return table


def rows_for_scope(table, scope, status, base_url, errors):
    headers = [h["value"] for h in table["header"]]
    pattern = re.compile(rf"^{re.escape(scope)}\s*-", re.IGNORECASE)
    bodies = []
    for row in table["body"]:
        if not pattern.match(clean(row[0])):
            continue
        if len(row) != len(headers):
            errors.append(f"{clean(row[0])}: {len(row)} cells, expected {len(headers)}")
        body = {"status": status}
        links = []
        for header, cell in zip(headers, row):
            links.extend(extract_links(cell, base_url))
            body[field_key(header)] = clean(cell)
        body["documents"] = [dict(link) for link in links]
        bodies.append(body)
    return bodies


def atomic_write(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def safe_name(value):
    return re.sub(r"[^\w.-]+", "_", value).strip("._") or "unknown"


def is_landscape(page):
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    if int(page.get("/Rotate", 0) or 0) % 180:
        width, height = height, width
    return width > height


def split_pdf(pdf_path, certificate_path, annex_path):
    """Certificate = leading portrait pages; annex = everything after them."""
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    cover_count = 0
    for page in reader.pages:
        if is_landscape(page):
            break
        cover_count += 1
    result = {"pages": total, "certificate_pages": cover_count, "annex_pages": total - cover_count}
    # All-portrait or all-landscape means the layout is not the expected one, so
    # leave the original whole instead of guessing where the annex starts.
    if cover_count == 0 or cover_count == total:
        result["split"] = "not split: no portrait-to-landscape change, check manually"
        return result
    for target, start, stop in ((certificate_path, 0, cover_count), (annex_path, cover_count, total)):
        writer = PdfWriter()
        for index in range(start, stop):
            writer.add_page(reader.pages[index])
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "wb") as handle:
            writer.write(handle)
        os.replace(tmp, target)
    result["split"] = "ok"
    return result


def parse_certificate(text):
    """Best-effort fields from the first page. Missing fields are simply left out."""
    text = re.sub(r"\s+", " ", text)
    patterns = {
        "registration_number": r"Reģistrācijas numurs:\s*([\d ]+\d)",
        "legal_address": r"Juridiskā adrese:\s*(.+?)\s*atbilst\b",
        "standard": r"atbilst standarta\s*(.+?)\s*prasībām",
        "accreditation_period": r"periods\s*(no .+?līdz .+?)\s*Lēmums",
        "decision": r"Lēmums pieņemts\s*(.+?),\s*Rīgā",
        "certificate_number": r"apliecība Nr\.\s*(.+?)\s*uz\s*\d",
    }
    fields = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            fields[key] = match.group(1).strip()
    if "registration_number" in fields:
        fields["registration_number"] = fields["registration_number"].replace(" ", "")
    if "certificate_number" in fields:
        number = re.sub(r"\s+", "", fields["certificate_number"])
        fields["certificate_number"] = re.sub(r"^(LATAK-)+", "LATAK-", number)
    return fields


def extract_pdf_content(pdf_path, text_path, tables_path, annex_start):
    pages_text = []
    table_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            pages_text.append(page.extract_text() or "")
            if number <= annex_start:
                continue
            for table_no, table in enumerate(page.extract_tables() or [], 1):
                for row_no, row in enumerate(table, 1):
                    cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
                    table_rows.append([number, table_no, row_no, *cells])
    body = "\n\n".join(f"--- page {i} ---\n{t}" for i, t in enumerate(pages_text, 1))
    atomic_write(text_path, body.encode("utf-8"))
    if table_rows:
        with open(tables_path, "w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerows([["page", "table", "row", "cells..."], *table_rows])
    return pages_text, len(table_rows)


def process_document(session, base_url, body, document, index, directory, errors):
    body_id = body["id"]
    host = urlparse(document["url"]).netloc
    if host != urlparse(base_url).netloc:
        document["skipped"] = f"external host {host}"
        errors.append(f"{body_id}: not downloaded, external link {document['url']}")
        return
    stem = safe_name(body_id) if index == 0 else f"{safe_name(body_id)}_doc{index + 1}"
    response = session.get(document["url"], timeout=180)
    response.raise_for_status()
    data = response.content
    document["content_type"] = response.headers.get("content-type", "")
    document["size_bytes"] = len(data)
    document["sha256"] = hashlib.sha256(data).hexdigest()
    disposition = response.headers.get("content-disposition", "")
    original = re.search(r'filename="?([^";]+)"?', disposition)
    if original:
        document["original_filename"] = original.group(1)

    if not data.startswith(b"%PDF-"):
        # Often a maintenance or error page: keep it visible as a failure.
        errors.append(f"{body_id}: {document['url']} is not a PDF ({document['content_type']})")
        return

    pdf_path = directory / f"{stem}.pdf"
    atomic_write(pdf_path, data)
    document["file"] = pdf_path.name
    try:
        split = split_pdf(pdf_path, directory / f"{stem}_certificate.pdf", directory / f"{stem}_annex.pdf")
        document.update(split)
        if split["split"] != "ok":
            errors.append(f"{body_id}: {split['split']}")
        pages_text, table_rows = extract_pdf_content(
            pdf_path,
            directory / f"{stem}_text.txt",
            directory / f"{stem}_annex_tables.csv",
            split["certificate_pages"],
        )
        document["annex_table_rows"] = table_rows
        if not any(t.strip() for t in pages_text):
            errors.append(f"{body_id}: no text layer in {pdf_path.name}, OCR needed")
        elif index == 0:
            body["certificate"] = parse_certificate(pages_text[0])
    except Exception as exc:  # a parsing problem must not lose the downloaded PDF
        errors.append(f"{body_id}: could not process {pdf_path.name}: {exc}")


def write_csv(path, bodies):
    columns = ["id", "status", "name", "addresses", "phone", "scope", "valid_until",
               "decision_date", "notes", "registration_number", "legal_address", "standard",
               "accreditation_period", "decision", "certificate_number", "pages",
               "certificate_pages", "annex_pages", "document_url", "file"]
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for body in bodies:
            first = body["documents"][0] if body["documents"] else {}
            row = {**body, **body.get("certificate", {}), **first, "document_url": first.get("url", "")}
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scope", default="S2", help="ID prefix to collect (default: S2)")
    parser.add_argument("-o", "--output", type=Path, help="output folder (default: ./latak_<scope>)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between downloads (default: 1)")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    out = args.output or Path(f"latak_{safe_name(args.scope)}")
    (out / "raw_tables").mkdir(parents=True, exist_ok=True)
    session = make_session()
    errors, bodies = [], []

    active_rows_seen = 0
    for status, (path, fallback) in LISTINGS.items():
        table_id = discover_table_id(session, base_url, path, fallback)
        try:
            table = fetch_table(session, base_url, table_id)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{status} table {table_id}: {exc}")
            log(f"{status}: FAILED ({exc})")
            continue
        write_json(out / "raw_tables" / f"{status}_{table_id}.json", table)
        found = rows_for_scope(table, args.scope, status, base_url, errors)
        log(f"{status}: table {table_id}, {len(table['body'])} rows, {len(found)} in scope {args.scope}")
        if status == "active":
            active_rows_seen = len(table["body"])
        bodies.extend(found)

    if not active_rows_seen:
        errors.append("active table returned no rows; site may be down for maintenance")

    for position, body in enumerate(bodies, 1):
        directory = out / safe_name(body["id"])
        directory.mkdir(exist_ok=True)
        log(f"[{position}/{len(bodies)}] {body['id']} {body.get('name', '')[:60]}")
        if body["status"] == "active" and not body["documents"]:
            errors.append(f"{body['id']}: no certificate link in the table")
        for index, document in enumerate(body["documents"]):
            try:
                process_document(session, base_url, body, document, index, directory, errors)
            except requests.RequestException as exc:
                errors.append(f"{body['id']}: download failed {document['url']}: {exc}")
            time.sleep(args.delay)
        write_json(directory / "metadata.json", body)

    write_json(out / "bodies.json", {
        "source": base_url,
        "scope": args.scope,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(bodies),
        "errors": errors,
        "bodies": bodies,
    })
    write_csv(out / "bodies.csv", bodies)

    log(f"\nDone: {len(bodies)} bodies in {out.resolve()}")
    if errors:
        log(f"{len(errors)} problem(s):")
        for error in errors:
            log(f"  - {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
