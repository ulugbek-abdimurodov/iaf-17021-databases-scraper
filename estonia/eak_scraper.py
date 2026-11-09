#!/usr/bin/env python3
"""Download the Estonian Accreditation Centre (EAK) register of management
system certification bodies: body details, contacts, scope and annex PDFs.

    pip install requests beautifulsoup4 lxml pdfplumber
    python eak_scraper.py --out eak_data

Output:
    bodies.json / bodies.csv     one record per certification body
    documents.csv                one row per annex PDF
    scope_tables.csv             tables extracted from the annex PDFs
    errors.json                  anything that failed (only written on failure)
    bodies/<certificate>_<name>/
        page.html                the register page as served
        info.json                the record for this body
        annexes/<annex>.pdf      the original PDF
        annexes/<annex>.txt      text extracted from the PDF

Re-running overwrites earlier files, so the output always matches the register.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

log = logging.getLogger("eak")

DEFAULT_BASE_URL = "https://eak.ee/"
DEFAULT_LIST_PAGE_ID = 33  # "Management system certification bodies" (English)
USER_AGENT = "eak-register-scraper/1.0 (python-requests)"
SITE_ENCODING = "windows-1252"  # the pages' declared charset

# Label fragments as they appear on the page. The site spells "Address" as
# "Aaddress", so matching is on a fragment and not the whole label.
HEADER_FIELDS = {
    "registration": "registration_no",
    "certificate no": "certificate_no",
    "effective date": "accreditation_effective",
    "valid until": "accreditation_valid_until",
}
CONTACT_FIELDS = {
    "ddress": "address",
    "contact person": "contact_person",
    "phone": "phone",
    "fax": "fax",
    "e-mail": "email",
}
BODY_CSV_FIELDS = [
    "certificate_no", "name", "registration_no", "accreditation_effective",
    "accreditation_valid_until", "address", "contact_person", "phone", "fax",
    "email", "description", "annex_count", "source_url",
]
DOCUMENT_CSV_FIELDS = [
    "certificate_no", "body_name", "annex", "url", "local_path", "size_bytes",
    "sha256", "last_modified", "pages", "annex_valid_from", "annex_valid_to",
    "scope_statements",
]


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def iso_date(value: str) -> str:
    """Convert dd.mm.yyyy to yyyy-mm-dd; leave anything else as it is."""
    try:
        return datetime.strptime(value, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return value


def safe_name(value: str) -> str:
    return re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._") or "unnamed"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_html(raw: bytes) -> BeautifulSoup:
    return BeautifulSoup(raw, "lxml", from_encoding=SITE_ENCODING)


def parse_list(raw: bytes, page_url: str) -> list[dict]:
    """Return the rows of the Nr / Name / Date table."""
    soup = parse_html(raw)
    for table in soup.select("table.mainPage"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [clean(c.get_text()).lower() for c in rows[0].find_all("td")]
        if header[:3] != ["nr", "name", "date"]:
            continue
        entries = []
        for row in rows[1:]:
            cells = row.find_all("td")
            link = row.find("a", href=True)
            if len(cells) < 3 or link is None:
                continue
            url = urljoin(page_url, link["href"])
            entries.append({
                "certificate_no": clean(cells[0].get_text()),
                "name": clean(cells[1].get_text()),
                "date": iso_date(clean(cells[2].get_text())),
                "url": url,
                "register_id": parse_qs(urlparse(url).query).get("id", [""])[0],
            })
        return entries
    raise ValueError(f"No Nr/Name/Date table found at {page_url}")


def section_cell(table, heading: str):
    """Return the cell below a one-cell heading row, such as 'Description'."""
    rows = table.find_all("tr")
    if rows and clean(rows[0].get_text()).lower() == heading and len(rows) > 1:
        return rows[1].find("td")
    return None


def parse_detail(raw: bytes, page_url: str) -> dict:
    soup = parse_html(raw)
    record = {
        "name": "", "registration_no": "", "certificate_no": "",
        "accreditation_effective": "", "accreditation_valid_until": "",
        "address": "", "contact_person": "", "phone": "", "fax": "", "email": "",
        "description": "", "annexes": [],
    }
    firm = soup.select_one("td.akr_det_firm")
    if firm:
        record["name"] = clean(firm.get_text())

    pdf_urls: dict[str, str] = {}
    for table in soup.select("table.mainPage"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            # "Registration no. <b>10459567</b>"
            if len(cells) == 1 and cells[0].find("b") and cells[0].get("colspan"):
                label = clean(cells[0].get_text()).lower()
                value = clean(cells[0].find("b").get_text())
                for fragment, field in HEADER_FIELDS.items():
                    if fragment in label and value:
                        record[field] = value
            # "Phone | +372 ..."
            if len(cells) == 2:
                label = clean(cells[0].get_text()).lower()
                for fragment, field in CONTACT_FIELDS.items():
                    if fragment in label:
                        record[field] = clean(cells[1].get_text())
                        break
        description = section_cell(table, "description")
        if description:
            record["description"] = clean(description.get_text())
        # Every PDF in the content tables is collected, so a certificate would
        # be picked up too if the site starts publishing one here.
        for link in table.find_all("a", href=True):
            if urlparse(link["href"]).path.lower().endswith(".pdf"):
                pdf_urls.setdefault(urljoin(page_url, link["href"]), clean(link.get_text()))

    record["accreditation_effective"] = iso_date(record["accreditation_effective"])
    record["accreditation_valid_until"] = iso_date(record["accreditation_valid_until"])
    record["annexes"] = [{"label": label, "url": url} for url, label in pdf_urls.items()]
    return record


def download_pdf(session: requests.Session, url: str, target: Path) -> dict:
    response = session.get(url, timeout=120)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Not a PDF ({response.headers.get('Content-Type')})")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "last_modified": response.headers.get("Last-Modified", ""),
    }


def extract_pdf(path: Path) -> tuple[dict, list[dict]]:
    """Save the PDF's text beside it and return its metadata and table rows."""
    pages_text, rows = [], []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, 1):
            pages_text.append(page.extract_text() or "")
            for table_no, table in enumerate(page.extract_tables(), 1):
                for row_no, row in enumerate(table, 1):
                    rows.append({
                        "page": page_no, "table": table_no, "row": row_no,
                        "cells": [clean(cell) for cell in row],
                    })
    text = "\n\n".join(pages_text)
    path.with_suffix(".txt").write_text(text, encoding="utf-8")
    if not text.strip():
        log.warning("No text in %s; it may be a scan that needs OCR", path.name)

    flat = clean(text)
    validity = re.search(
        r"annex is valid from\s+(\d{2}\.\d{2}\.\d{4})\s+to\s+(\d{2}\.\d{2}\.\d{4})",
        flat, re.I)
    statements = re.findall(r"Accreditation scope is (.+?)(?:\s+as given below)?\s*:(?=\s|$)", flat)
    return {
        "pages": page_count,
        "annex_valid_from": iso_date(validity.group(1)) if validity else "",
        "annex_valid_to": iso_date(validity.group(2)) if validity else "",
        "scope_statements": list(dict.fromkeys(clean(s) for s in statements)),
    }, rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    # utf-8-sig so Excel displays characters such as Ü correctly.
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def scrape(base_url: str, list_page_id: int, out: Path, delay: float) -> int:
    session = make_session()
    out.mkdir(parents=True, exist_ok=True)
    errors: list[dict] = []
    base_host = urlparse(base_url).netloc

    def fetch(url: str) -> bytes:
        time.sleep(delay)
        response = session.get(url, timeout=60)
        response.raise_for_status()
        return response.content

    list_url = urljoin(base_url, f"index_eng.php?pageId={list_page_id}")
    log.info("Reading list: %s", list_url)
    entries = parse_list(fetch(list_url), list_url)
    if not entries:
        raise ValueError(f"The list at {list_url} has no bodies; has the site changed?")
    log.info("Found %d bodies", len(entries))

    bodies, documents, scope_rows = [], [], []
    for entry in entries:
        log.info("%s  %s", entry["certificate_no"], entry["name"])
        try:
            raw = fetch(entry["url"])
            record = parse_detail(raw, entry["url"])
        except Exception as exc:
            log.error("  page failed: %s", exc)
            errors.append({"url": entry["url"], "error": str(exc)})
            continue

        missing = [f for f in ("name", "certificate_no", "accreditation_valid_until")
                   if not record[f]]
        if missing:
            errors.append({"url": entry["url"], "error": f"Fields not found: {missing}"})
        if record["certificate_no"] and record["certificate_no"] != entry["certificate_no"]:
            errors.append({"url": entry["url"], "error":
                           f"List says {entry['certificate_no']}, "
                           f"page says {record['certificate_no']}"})
        if not record["annexes"]:
            errors.append({"url": entry["url"], "error": "No annex links found"})

        cert = record["certificate_no"] or entry["certificate_no"]
        name = record["name"] or entry["name"]
        folder = out / "bodies" / safe_name(f"{cert}_{name}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "page.html").write_bytes(raw)
        record.update(register_id=entry["register_id"], source_url=entry["url"],
                      list_date=entry["date"], annex_count=len(record["annexes"]))

        for annex in record["annexes"]:
            url = annex["url"]
            if urlparse(url).netloc != base_host:
                errors.append({"url": url, "error": "Skipped: not on the register's site"})
                continue
            filename = safe_name(unquote(Path(urlparse(url).path).name))
            target = folder / "annexes" / filename
            try:
                time.sleep(delay)
                annex.update(download_pdf(session, url, target))
                annex["local_path"] = target.relative_to(out).as_posix()
                log.info("  %s (%d bytes)", filename, annex["size_bytes"])
            except Exception as exc:
                log.error("  %s failed: %s", url, exc)
                errors.append({"url": url, "error": str(exc)})
                continue
            if pdfplumber is not None:
                try:
                    metadata, rows = extract_pdf(target)
                    annex.update(metadata)
                    scope_rows.extend(
                        {"certificate_no": cert, "annex": annex["label"], **row}
                        for row in rows)
                except Exception as exc:
                    log.error("  %s: extraction failed: %s", filename, exc)
                    errors.append({"url": url, "error": f"PDF extraction: {exc}"})
            documents.append({
                **annex, "certificate_no": cert, "body_name": name,
                "annex": annex["label"],
                "scope_statements": " | ".join(annex.get("scope_statements", [])),
            })

        write_json(folder / "info.json", record)
        bodies.append(record)

    write_json(out / "bodies.json", {
        "source": list_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(bodies),
        "bodies": bodies,
    })
    write_csv(out / "bodies.csv", BODY_CSV_FIELDS, bodies)
    write_csv(out / "documents.csv", DOCUMENT_CSV_FIELDS, documents)

    width = max((len(r["cells"]) for r in scope_rows), default=0)
    columns = [f"col{i + 1}" for i in range(width)]
    write_csv(
        out / "scope_tables.csv",
        ["certificate_no", "annex", "page", "table", "row", *columns],
        [{**r, **dict(zip(columns, r["cells"]))} for r in scope_rows],
    )

    errors_path = out / "errors.json"
    if errors:
        write_json(errors_path, errors)
    elif errors_path.exists():
        errors_path.unlink()

    log.info("Done: %d/%d bodies, %d PDFs, %d table rows, %d problems. Output: %s",
             len(bodies), len(entries), len(documents), len(scope_rows), len(errors),
             out.resolve())
    if pdfplumber is None:
        log.warning("pdfplumber is not installed: PDFs saved, but no text or tables extracted")
    if errors:
        log.warning("See %s", errors_path)
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("eak_data"), help="output folder")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to wait between requests (default: 1)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--list-page-id", type=int, default=DEFAULT_LIST_PAGE_ID,
                        help="pageId of the list to scrape (default: 33)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return scrape(args.base_url, args.list_page_id, args.out, args.delay)
    except (requests.RequestException, ValueError) as exc:
        log.error("Stopped: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
