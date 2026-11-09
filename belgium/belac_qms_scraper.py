#!/usr/bin/env python3
"""Download everything BELAC publishes about management system (QMS) certification bodies.

Source: https://weblist.economie.fgov.be/en/belac/list/qms

Setup:  pip install requests pypdf pdfplumber
Run:    python belac_qms_scraper.py [--out belac_qms_data] [--force] [--no-parse]

Output:
  bodies.json / bodies.csv        one record per body, with contact details and scope
  scope.csv                       one row per body + field + keyword
  annex_scope.csv                 all scope tables read from the annexes
  reference/                      fields, keywords and the official Excel export (EN/NL/FR/DE)
  bodies/<number>_<name>/
    info.json                     body details, scope, related accreditations, PDF metadata
    <number>.pdf                  original file: certificates and annex
    certificates.pdf, annex.pdf   the original split in two
    annex.txt, annex_tables.csv   text and tables extracted from the annex

Re-running only downloads PDFs that changed on the server. The exit code is 1 if anything failed.
"""

import argparse
import base64
import csv
import json
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = "https://weblist.economie.fgov.be/api"
PDF_BASE = "https://ng3.economie.fgov.be/NI/belac/QMS/scope_pdf"
PAGE_URL = "https://weblist.economie.fgov.be/en/belac/QMS"
LANGUAGES = ("en", "nl", "fr", "de")
TIMEOUT = 60

# The first annex page carries this phrase in four languages. Certificates come before it.
ANNEX_MARKER = re.compile(
    r"annexe au certificat|bijlage bij accreditatiecertificaat|"
    r"annex to the accreditation certificate|beilage zur akkreditierungs",
    re.I,
)
VERSION_RE = re.compile(r"Fassung\s*(\S+)", re.I)
VALIDITY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*[-–]\s*(\d{4}-\d{2}-\d{2})")

# The API returns only one field and keyword per body here. The full scope comes from /fields/<id>.
BODY_FIELDS = (
    "certificationNumber", "name", "enterpriseNumber", "street", "streetNumber", "postBox",
    "postCode", "municipality", "country", "contactPersonTitle", "contactPersonFirstName",
    "contactPersonFamilyName", "telephone", "fax", "email", "url",
)

log = logging.getLogger("belac")


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "belac-qms-scraper/1.0"
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def get_json(session, url, **params):
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, rows, fieldnames):
    # utf-8-sig so that Excel displays accented names correctly.
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def slug(text, limit=50):
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")[:limit].rstrip("-") or "unnamed"


def list_bodies(session, api):
    """Return all bodies, checked against the total reported by the paged search endpoint."""
    bodies = {}
    for row in get_json(session, f"{api}/qms/all"):
        bodies.setdefault(row["certificationNumber"], row)
    total = get_json(session, f"{api}/qms/search", page=0, size=1, sort="name")["totalElements"]
    if len(bodies) != total:
        raise RuntimeError(f"/qms/all returned {len(bodies)} bodies but /qms/search reports {total}")
    return [bodies[key] for key in sorted(bodies)]


def download_reference(session, api, out):
    ref = out / "reference"
    ref.mkdir(exist_ok=True)
    for name in ("fields", "keywords"):
        write_json(ref / f"{name}.json", get_json(session, f"{api}/qms/{name}"))
    for lang in LANGUAGES:
        payload = get_json(session, f"{api}/qms/excel/{lang}")
        (ref / f"QualitySystems_{lang}.xlsx").write_bytes(base64.b64decode(payload["_content"]))


def download_pdf(session, url, target, previous, force):
    """Download a PDF if it changed. Return (metadata, was_downloaded)."""
    head = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    head.raise_for_status()
    meta = {
        "url": url,
        "last_modified": head.headers.get("Last-Modified"),
        "size_bytes": int(head.headers.get("Content-Length") or 0) or None,
    }
    unchanged = (
        previous
        and target.exists()
        and previous.get("last_modified") == meta["last_modified"]
        and target.stat().st_size == previous.get("size_bytes")
    )
    if unchanged and not force:
        return previous, False

    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    if meta["size_bytes"] and len(content) != meta["size_bytes"]:
        raise ValueError(f"{url}: expected {meta['size_bytes']} bytes, got {len(content)}")
    meta["size_bytes"] = len(content)
    partial = target.with_suffix(".part")
    partial.write_bytes(content)
    partial.replace(target)
    return meta, True


def parse_pdf(pdf_path, folder, number):
    """Split certificates from the annex and extract annex text and tables."""
    import pdfplumber
    from pypdf import PdfReader, PdfWriter

    with pdfplumber.open(pdf_path) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
        annex_start = next((i for i, text in enumerate(texts) if ANNEX_MARKER.search(text)), None)
        info = {"page_count": len(texts), "annex_first_page": None, "certificate_pages": None,
                "annex_version": None, "valid_from": None, "valid_to": None}
        if annex_start is None:
            log.warning("%s: annex marker not found, leaving the PDF unsplit", number)
            return info, []

        rows = []
        for page_no in range(annex_start, len(texts)):
            tables = pdf.pages[page_no].extract_tables()
            for table_no, table in enumerate(tables, 1):
                for row_no, cells in enumerate(table, 1):
                    rows.append({
                        "certificationNumber": number, "page": page_no + 1, "table": table_no,
                        "row": row_no,
                        "cells": [" ".join((cell or "").split()) for cell in cells],
                    })

    cover = texts[annex_start]
    version = VERSION_RE.search(cover)
    validity = VALIDITY_RE.search(cover)
    info.update(
        annex_first_page=annex_start + 1,
        certificate_pages=annex_start,
        annex_version=version.group(1) if version else None,
        valid_from=validity.group(1) if validity else None,
        valid_to=validity.group(2) if validity else None,
    )

    reader = PdfReader(pdf_path)
    for name, pages in (("certificates.pdf", range(annex_start)),
                        ("annex.pdf", range(annex_start, len(reader.pages)))):
        writer = PdfWriter()
        for index in pages:
            writer.add_page(reader.pages[index])
        with (folder / name).open("wb") as handle:
            writer.write(handle)

    (folder / "annex.txt").write_text(
        "\n\n".join(f"--- page {i + 1} ---\n{texts[i]}" for i in range(annex_start, len(texts))),
        encoding="utf-8",
    )
    write_table_csv(folder / "annex_tables.csv", rows)
    return info, rows


def write_table_csv(path, rows):
    # Scope tables differ in width, so each row is padded to the widest one.
    width = max((len(row["cells"]) for row in rows), default=0)
    columns = [f"col{i + 1}" for i in range(width)]
    flat = [
        {**{k: row[k] for k in ("certificationNumber", "page", "table", "row")},
         **dict(zip(columns, row["cells"]))}
        for row in rows
    ]
    write_csv(path, flat, ["certificationNumber", "page", "table", "row", *columns])


def process_body(session, args, row, out):
    number = row["certificationNumber"]
    folder = out / "bodies" / f"{number}_{slug(row.get('name'))}"
    folder.mkdir(parents=True, exist_ok=True)
    info_path = folder / "info.json"
    previous = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}

    record = {key: row.get(key) for key in BODY_FIELDS}
    record["detail_page"] = f"{PAGE_URL}/{number}"
    record["scope"] = get_json(session, f"{args.api_base}/qms/fields/{number}")

    enterprise = (row.get("enterpriseNumber") or "").strip()
    record["all_belac_accreditations"] = (
        get_json(session, f"{args.api_base}/belacfirms/{enterprise}") if enterprise else []
    )

    pdf_path = folder / f"{number}.pdf"
    record["pdf"], downloaded = download_pdf(
        session, f"{args.pdf_base}/{number}.pdf", pdf_path, previous.get("pdf"), args.force
    )

    tables_path = folder / "annex_tables.csv"
    annex_rows = []
    if args.no_parse:
        record["pdf_details"] = previous.get("pdf_details")
    elif downloaded or args.force or not previous.get("pdf_details"):
        record["pdf_details"], annex_rows = parse_pdf(pdf_path, folder, number)
    else:
        record["pdf_details"] = previous["pdf_details"]
        if tables_path.exists():
            with tables_path.open(newline="", encoding="utf-8-sig") as handle:
                for saved in csv.DictReader(handle):
                    cells = [saved[k] for k in saved if k.startswith("col")]
                    annex_rows.append({
                        "certificationNumber": number, "page": saved["page"],
                        "table": saved["table"], "row": saved["row"], "cells": cells,
                    })

    write_json(info_path, record)
    return record, annex_rows, downloaded


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("belac_qms_data"))
    parser.add_argument("--force", action="store_true", help="download and parse all PDFs again")
    parser.add_argument("--no-parse", action="store_true", help="download PDFs without splitting them")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between bodies")
    parser.add_argument("--api-base", default=API_BASE, help=argparse.SUPPRESS)
    parser.add_argument("--pdf-base", default=PDF_BASE, help=argparse.SUPPRESS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    session = make_session()
    failures = []

    bodies = list_bodies(session, args.api_base)
    log.info("Found %d bodies", len(bodies))

    try:
        download_reference(session, args.api_base, args.out)
    except (requests.RequestException, ValueError, KeyError) as exc:
        failures.append(("reference", str(exc)))
        log.error("reference files: %s", exc)

    records, annex_rows, downloads = [], [], 0
    for index, row in enumerate(bodies, 1):
        number = row["certificationNumber"]
        try:
            record, rows, downloaded = process_body(session, args, row, args.out)
        except Exception as exc:  # One bad body must not stop the others.
            failures.append((number, str(exc)))
            log.error("[%d/%d] %s failed: %s", index, len(bodies), number, exc)
            continue
        records.append(record)
        annex_rows.extend(rows)
        downloads += downloaded
        log.info("[%d/%d] %s %s (%s)", index, len(bodies), number, row.get("name"),
                 "downloaded" if downloaded else "unchanged")
        time.sleep(args.delay)

    write_json(args.out / "bodies.json", records)
    summary_rows = [
        {**record,
         "scope_fields": " | ".join(record["scope"]),
         "pdf_url": record["pdf"]["url"],
         "pdf_last_modified": record["pdf"]["last_modified"],
         **(record.get("pdf_details") or {})}
        for record in records
    ]
    write_csv(args.out / "bodies.csv", summary_rows, [
        *BODY_FIELDS, "scope_fields", "annex_version", "valid_from", "valid_to", "page_count",
        "pdf_url", "pdf_last_modified", "detail_page",
    ])
    write_csv(args.out / "scope.csv", [
        {"certificationNumber": record["certificationNumber"], "name": record["name"],
         "field": field, "keyword": keyword}
        for record in records
        for field, keywords in record["scope"].items()
        for keyword in (keywords or [""])
    ], ["certificationNumber", "name", "field", "keyword"])
    if annex_rows:
        write_table_csv(args.out / "annex_scope.csv", annex_rows)

    log.info("Done: %d of %d bodies saved, %d PDFs downloaded, in %s",
             len(records), len(bodies), downloads, args.out.resolve())
    if failures:
        for name, reason in failures:
            log.error("FAILED %s: %s", name, reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
