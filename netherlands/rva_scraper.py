#!/usr/bin/env python3
"""Scrape accredited bodies from the Dutch Accreditation Council (RvA, rva.nl).

Default target: management system certification bodies (ISO/IEC 17021-1).
For each body it saves the listing data, company details, raw detail page,
and every published scope PDF ("Annex to declaration of accreditation").
It also pulls text, tables and key dates out of each PDF.

Setup:   pip install requests beautifulsoup4 pdfplumber
Run:     python rva_scraper.py
Options: python rva_scraper.py --help

Output (default folder: rva_output/):
    bodies.csv / bodies.json   one row per accredited body
    documents.csv              one row per PDF, with dates and file details
    documents.json             the same, plus tables extracted from the PDF
    files/<ID>/<ID>-sce.pdf    annex in English (-scn.pdf = Dutch)
    files/<ID>/<ID>-sce.txt    text extracted from that PDF
    files/<ID>/<ID>.html       raw detail page

Re-running is safe: PDFs that have not changed on the server are skipped.
The exit code is 1 if anything failed; failures are listed in errors.json.
"""
from __future__ import annotations

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

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

DEFAULT_BASE = "https://www.rva.nl"
MANAGEMENT_SYSTEM_FILTER = "norm:17021-1"
RETRY_STATUS = {429, 500, 502, 503, 504}
DATE = r"\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"

BODY_FIELDS = [
    "id", "title", "discipline", "tag", "department", "extended",
    "org_names", "street", "address", "country", "business_number",
    "phone", "email", "website", "org_url", "org_accreditation_count",
    "related_ids", "has_scope_nl", "has_scope_en", "url", "other_sections",
    "scraped_at",
]
DOC_FIELDS = [
    "id", "language", "url", "file", "bytes", "sha256", "last_modified",
    "etag", "download_status", "pages", "registration_number",
    "normative_document", "valid_from", "valid_until", "replaces_annex_dated",
    "trading_name",
]


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class Client:
    """HTTP session with a delay between requests and retries with backoff."""

    def __init__(self, delay: float, retries: int = 4, timeout: int = 60):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "rva-scope-scraper/1.0"
        self._last = 0.0

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException:
                if attempt == self.retries:
                    raise
            else:
                if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                    resp.raise_for_status()
                    return resp
            time.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")


def fetch_listing(client: Client, base: str, filters: str) -> list[dict]:
    """Return all listing rows, checking the total the API reports."""
    posts: list[dict] = []
    page, expected = 1, 0
    while True:
        data = client.request(
            "GET",
            urljoin(base, "/wp-json/rva/search-org"),
            params={"search": "", "sort": "ASC;rva_Accrnr", "filters": filters,
                    "page": page, "lang": ""},
        ).json()
        posts.extend(data["posts"])
        expected = data["results_total"]
        if page >= data["max_page"]:
            break
        page += 1
    if len(posts) != expected:
        raise RuntimeError(f"listing returned {len(posts)} rows, API reports {expected}")
    return posts


def parse_detail(html: str, page_url: str) -> dict:
    """Parse a detail page, e.g. /alle-geaccrediteerden/c248/."""
    section = BeautifulSoup(html, "html.parser").select_one("section.scope")
    if section is None:
        raise ValueError("no section.scope on detail page")

    # Left column: labelled parts such as Discipline, Verlengd and Downloads.
    sections: dict[str, str] = {}
    for part in section.select(".scope__part"):
        label = part.select_one(".scope__subtitle")
        content = part.select_one(".scope__content")
        if label and content:
            sections[clean(label.get_text())] = clean(content.get_text(" "))

    def org_text(name: str) -> str:
        return " | ".join(clean(p.get_text()) for p in section.select(f".org-data__{name}"))

    def org_link(name: str, prefix: str = "") -> str:
        link = section.select_one(f".org-data__{name} a[href]")
        return link["href"].removeprefix(prefix).strip() if link else ""

    documents = []
    seen = set()
    for link in section.select("a.btn--download[href], .scope__content--downloads a[href]"):
        url = urljoin(page_url, link["href"]).split("?")[0]  # drop ?time=... cache buster
        if url not in seen:
            seen.add(url)
            documents.append({"url": url, "language": link.get("data-lang", "")})

    org_url, org_count, related = "", "", []
    for link in section.select("a.org-scopes__link[href]"):
        href = urljoin(page_url, link["href"])
        text = clean(link.get_text())
        if "/organisaties/" in href:
            org_url = href
            match = re.search(r"\((\d+)\)\s*$", text)
            org_count = match.group(1) if match else ""
        else:
            related.append(text)

    known = {"Discipline", "Downloads", "Verlengd"}
    return {
        "discipline": sections.get("Discipline", ""),
        "extended": sections.get("Verlengd", ""),
        "other_sections": {k: v for k, v in sections.items() if k not in known},
        "org_names": org_text("name"),
        "street": org_text("street"),
        "address": org_text("adress"),  # the site's own spelling
        "country": org_text("country"),
        "business_number": org_text("business-number"),
        "phone": org_link("tel", "tel:"),
        "email": org_link("mail", "mailto:"),
        "website": org_link("site"),
        "org_url": org_url,
        "org_accreditation_count": org_count,
        "related_ids": related,
        "documents": documents,
    }


def parse_annex_text(text: str) -> dict:
    """Extract header fields from annex text. Handles English and Dutch wording."""
    flat = clean(text)

    def find(pattern: str) -> str:
        match = re.search(pattern, flat, re.I)
        return clean(match.group(1)) if match else ""

    validity = re.search(
        rf"(?:valid from|geldig van(?:af)?)\s*:?\s*({DATE})"
        rf"(?:\s*(?:-|–|—|to|until|tot(?: en met)?|t/m)\s*({DATE}))?",
        flat, re.I,
    )
    return {
        "registration_number": find(r"(?:registration number|registratienummer)\s*:?\s*([A-Z]\s?\d{3})").replace(" ", ""),
        "normative_document": find(
            r"(?:normative document|normatief document)\s*:?\s*(.+?)"
            r"\s*(?:registration number|registratienummer)"
        ),
        "valid_from": validity.group(1) if validity else "",
        "valid_until": (validity.group(2) or "") if validity else "",
        "replaces_annex_dated": find(rf"(?:replaces annex dated|vervangt bijlage d\.?d\.?)\s*:?\s*({DATE})"),
        "trading_name": find(
            r"(?:handelend onder de naam|trading (?:as|under the name))\s+(.+?)"
            r"\s*(?:this annex|deze bijlage)"
        ),
    }


def analyse_pdf(path: Path) -> dict:
    """Return page count, header fields, tables and full text for a PDF."""
    with pdfplumber.open(path) as pdf:
        pages, tables = [], []
        for number, page in enumerate(pdf.pages, 1):
            pages.append(page.extract_text() or "")
            for table in page.extract_tables():
                tables.append({"page": number, "rows": table})
    text = "\n\n".join(pages)
    return {"pages": len(pages), "text": text, "tables": tables, **parse_annex_text(text)}


def safe_filename(url: str, base_host: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname != base_host:
        raise ValueError(f"refusing to download from another host: {url}")
    name = os.path.basename(parsed.path)
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.pdf", name):
        raise ValueError(f"unexpected file name in {url}")
    return name


def download_pdf(client: Client, url: str, dest: Path, previous: dict | None, force: bool) -> dict:
    """Download a PDF unless the local copy is current. Returns file details."""
    info = previous or {}
    head = client.request("HEAD", url).headers
    remote = (head.get("Last-Modified", ""), head.get("ETag", ""))
    unchanged = remote == (info.get("last_modified"), info.get("etag")) and any(remote)
    if dest.exists() and unchanged and not force:
        return {"download_status": "unchanged", "bytes": dest.stat().st_size,
                "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                "last_modified": remote[0], "etag": remote[1]}

    resp = client.request("GET", url)
    if not resp.content.startswith(b"%PDF"):
        raise ValueError(f"response is not a PDF: {url}")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.replace(dest)  # a failed run never leaves a half-written PDF
    return {"download_status": "downloaded", "bytes": len(resp.content),
            "sha256": hashlib.sha256(resp.content).hexdigest(),
            "last_modified": resp.headers.get("Last-Modified", remote[0]),
            "etag": resp.headers.get("ETag", remote[1])}


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    def cell(value):
        return "; ".join(value) if isinstance(value, list) else (
            json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value)

    # utf-8-sig so Excel displays names like "TÜV" correctly
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: cell(row.get(k, "")) for k in fields} for row in rows)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args) -> int:
    out = Path(args.out)
    (out / "files").mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/") + "/"
    host = urlparse(base).hostname
    client = Client(args.delay)
    parse_pdfs = pdfplumber is not None and not args.no_pdf_parse
    if pdfplumber is None and not args.no_pdf_parse:
        print("pdfplumber is not installed: downloading PDFs without reading them.", file=sys.stderr)

    documents_path = out / "documents.json"
    previous = {}
    if documents_path.exists():
        previous = {d["url"]: d for d in json.loads(documents_path.read_text(encoding="utf-8"))}

    listing = fetch_listing(client, base, args.filter)
    if args.limit:
        listing = listing[: args.limit]
    print(f"{len(listing)} bodies to process")

    bodies, documents, errors = [], [], []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for index, item in enumerate(listing, 1):
        body_id = item["id"]
        print(f"[{index}/{len(listing)}] {body_id} {item['title']}")
        folder = out / "files" / re.sub(r"[^A-Za-z0-9_-]", "_", body_id)
        folder.mkdir(exist_ok=True)
        try:
            page = client.request("GET", item["url"]).text
            (folder / f"{folder.name}.html").write_text(page, encoding="utf-8")
            detail = parse_detail(page, item["url"])
        except Exception as exc:  # keep going; failures are reported at the end
            errors.append({"id": body_id, "step": "detail", "url": item["url"], "error": str(exc)})
            print(f"  ERROR {exc}", file=sys.stderr)
            continue

        docs = detail.pop("documents")
        bodies.append({
            "id": body_id, "title": item["title"], "tag": item.get("tag", ""),
            "department": item.get("department", ""), "url": item["url"],
            "has_scope_nl": item.get("scopeNL"), "has_scope_en": item.get("scopeEN"),
            "scraped_at": now, **detail,
        })
        for doc in docs:
            record = {"id": body_id, **doc}
            try:
                name = safe_filename(doc["url"], host)
                dest = folder / name
                prior = previous.get(doc["url"])
                record["file"] = dest.relative_to(out).as_posix()
                record.update(download_pdf(client, doc["url"], dest, prior, args.force))
                if parse_pdfs:
                    if record["download_status"] == "unchanged" and prior and prior.get("pages"):
                        record.update({k: prior.get(k, "") for k in DOC_FIELDS[9:]})
                        record["tables"] = prior.get("tables", [])
                    else:
                        analysis = analyse_pdf(dest)
                        dest.with_suffix(".txt").write_text(analysis.pop("text"), encoding="utf-8")
                        record.update(analysis)
            except Exception as exc:
                errors.append({"id": body_id, "step": "pdf", "url": doc["url"], "error": str(exc)})
                print(f"  ERROR {exc}", file=sys.stderr)
            documents.append(record)

    write_json(out / "bodies.json", bodies)
    write_csv(out / "bodies.csv", BODY_FIELDS, bodies)
    write_json(documents_path, documents)
    write_csv(out / "documents.csv", DOC_FIELDS, documents)
    write_json(out / "errors.json", errors)

    saved = sum(1 for d in documents if d.get("download_status"))
    print(f"\nBodies: {len(bodies)}/{len(listing)}   PDFs: {saved}/{len(documents)}   Errors: {len(errors)}")
    if parse_pdfs:
        undated = [d["file"] for d in documents if d.get("pages") and not d.get("valid_from")]
        if undated:
            print(f"No validity date recognised in {len(undated)} PDF(s); check them by hand: " + ", ".join(undated))
    print(f"Saved to {out.resolve()}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape accredited bodies and scope PDFs from rva.nl")
    parser.add_argument("--out", default="rva_output", help="output folder (default: %(default)s)")
    parser.add_argument("--filter", default=MANAGEMENT_SYSTEM_FILTER,
                        help='site filter (default: %(default)s, management systems). '
                             'Use "" for all 805 accredited bodies.')
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=0, help="only process the first N bodies (for a trial run)")
    parser.add_argument("--force", action="store_true", help="download PDFs again even if unchanged")
    parser.add_argument("--no-pdf-parse", action="store_true", help="download PDFs without extracting their contents")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=argparse.SUPPRESS)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())