#!/usr/bin/env python3
"""Download the Czech Accreditation Institute (CAI) register of certification
bodies certifying management systems, with their certificate and annex PDFs.

    pip install requests beautifulsoup4
    python cai_scraper.py

Output (default folder: cai_output/):
    bodies.csv        one row per register entry
    certificates.csv  one row per certificate
    files.csv         one row per PDF, with local path, size and SHA-256
    errors.csv        anything that failed (only written if something did)
    data.json         everything above, nested
    pdfs/<entry>/     the certificate and annex PDFs
    raw_html/         the detail page of each entry, as served

Re-running skips PDFs that are already complete, so an interrupted run resumes.
The exit code is 1 if anything failed. The default delay of 5 seconds between
requests follows the Crawl-delay in https://www.cai.cz/robots.txt.
"""

import argparse
import base64
import binascii
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.cai.cz"
PAGE_ID = "4499"
DEFAULT_CATEGORY = "certifikacni-organy-certifikujici-systemy"
USER_AGENT = "cai-register-scraper/1.0"
TIMEOUT = 120
RETRIES = 4
PDF_MAGIC = b"%PDF-"

BODY_COLUMNS = [
    "cab_number", "name", "entry_slug", "business_id", "body_type", "address",
    "website", "certificate_numbers", "authentication_links", "file_count",
]
CERT_COLUMNS = [
    "cab_number", "name", "entry_slug", "certificate_number", "issued",
    "valid_until", "scope_summary_cs",
]
FILE_COLUMNS = [
    "cab_number", "name", "entry_slug", "certificate_number", "kind", "language",
    "filename", "label", "url", "local_path", "bytes", "sha256", "status",
]
ERROR_COLUMNS = ["stage", "item", "error"]


def text_of(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def field_content(row, name):
    return text_of(row.select_one(f".field.{name} .content"))


def to_iso(value):
    """Convert 'dd/mm/yyyy' or 'd. m. yyyy' to 'yyyy-mm-dd'; keep anything else."""
    match = re.fullmatch(r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", value.strip())
    if not match:
        return value.strip()
    day, month, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def clean_website(href):
    """The register emits a bare 'http://' for bodies with no website."""
    href = (href or "").strip()
    return href if urlsplit(href).netloc else ""


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unnamed"


def entry_slug(token):
    """Each entry's form token is a base64 slug such as '3137-ll-c-...-2'."""
    try:
        return safe_name(base64.b64decode(token, validate=True).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError):
        return safe_name(token)


def split_title(title):
    match = re.match(r"\s*(\d+)\s*[–—-]\s*(.+)", title)
    return (match.group(1), match.group(2).strip()) if match else ("", title.strip())


def parse_list_page(html):
    """Return (entries, has_next) for one page of the register listing."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for row in soup.select(".views-row"):
        token = row.select_one("input[name=cai_subjekt_b64]")
        if not token or not token.get("value"):
            continue
        lang = row.select_one("input[name=cai_lang]")
        entries.append({
            "token": token["value"],
            "lang": lang.get("value", "cs") if lang else "cs",
            "title": text_of(row.select_one(".subject-title-link")),
        })
    return entries, soup.select_one("a.next.page-numbers") is not None


def parse_certificate_field(field):
    contents = field.select(":scope > .content")
    number = text_of(contents[0]) if contents else ""

    def date_at(index):
        if index >= len(contents):
            return ""
        node = contents[index]
        dated = node.select_one(".js-subject-date-en") or node.select_one(".js-subject-date-cs")
        return to_iso(text_of(dated or node))

    return {
        "certificate_number": number,
        "issued": date_at(1),
        "valid_until": date_at(2),
        "scope_summary_cs": "",
        "files": [],
    }


def classify_file(filename, label):
    """Annexes are labelled 'Attachments' and their files are named P<no>_<year>_<lang>.pdf."""
    is_annex = re.search(r"attach|příloh|priloh", label, re.I) or re.match(r"P\d", filename)
    language = re.search(r"_([A-Za-z]{2})\.[A-Za-z0-9]+$", filename)
    return ("annex" if is_annex else "certificate", language.group(1).upper() if language else "")


def parse_file_field(field, page_url):
    label = text_of(field.select_one(".label")).rstrip(":")
    files = []
    for link in field.select("a[href]"):
        url = urljoin(page_url, link["href"])
        filename = Path(urlsplit(url).path).name
        kind, language = classify_file(filename, label)
        files.append({
            "kind": kind, "language": language, "filename": filename,
            "label": label, "url": url,
        })
    return files


def parse_detail_page(html, page_url):
    """Parse an entry's detail page.

    Only links inside '.field.priloha' count as the entry's documents: the same
    page also links a site-wide IAF leaflet that belongs to no certification body.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(".views-row")
    if not rows:
        raise ValueError("no register rows on the detail page")
    head = rows[0]
    website = head.select_one(".field.web a[href]")
    cab_number, name = split_title(text_of(head.select_one(".top-wrapper")))
    body = {
        "cab_number": cab_number,
        "name": name,
        "business_id": field_content(head, "ico"),
        "body_type": field_content(head, "doplnujici-nazev"),
        "address": field_content(head, "adresa"),
        "website": clean_website(website["href"]) if website else "",
        "certificates": [],
        "authentication_links": [],
    }
    for row in rows[1:]:
        current = None
        fields = row.select(".field")
        for field in fields:
            classes = field.get("class", [])
            if "osvedceni" in classes and field.select_one(":scope > .content"):
                current = parse_certificate_field(field)
                body["certificates"].append(current)
            elif "popis" in classes and current:
                current["scope_summary_cs"] = text_of(field)
            elif "priloha" in classes and current:
                current["files"].extend(parse_file_field(field, page_url))
        if current is None:  # e.g. the 'Authentication' row, which only links out
            for link in row.select("a[href]"):
                url = urljoin(page_url, link["href"])
                if url not in body["authentication_links"]:
                    body["authentication_links"].append(url)
    if not body["cab_number"] or not body["certificates"]:
        raise ValueError("detail page is missing the body number or a certificate")
    return body


class Client:
    def __init__(self, base_url, delay):
        self.endpoint = urljoin(base_url.rstrip("/") + "/", "en/")
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0

    def request(self, method, url, **kwargs):
        """Send a request politely; retry connection errors, 429 and 5xx."""
        for attempt in range(1, RETRIES + 1):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
                if response.status_code != 429 and response.status_code < 500:
                    response.raise_for_status()
                    return response
                error = f"HTTP {response.status_code}"
                response.close()
            except requests.exceptions.HTTPError:
                raise
            except requests.RequestException as exc:
                error = str(exc)
            if attempt == RETRIES:
                raise RuntimeError(f"gave up after {RETRIES} attempts: {error}")
            time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def list_entries(self, category):
        entries, page = [], 1
        while True:
            params = {"page_id": PAGE_ID, "kategorie_subjektu": category}
            if page > 1:
                params["paged"] = page
            response = self.request("GET", self.endpoint, params=params)
            found, has_next = parse_list_page(response.text)
            if not found:
                raise RuntimeError(f"listing page {page} contained no entries")
            entries.extend(found)
            print(f"  listing page {page}: {len(found)} entries", flush=True)
            if not has_next:
                return entries
            page += 1

    def detail(self, entry):
        response = self.request(
            "POST", self.endpoint, params={"page_id": PAGE_ID},
            data={"cai_subjekt_b64": entry["token"], "cai_lang": entry["lang"]},
        )
        return response.text, response.url

    def download(self, url, destination):
        """Stream a PDF to disk, keeping it only if it is complete and a real PDF."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        response = self.request("GET", url, stream=True)
        expected = response.headers.get("Content-Length")
        with response, open(partial, "wb") as handle:
            for chunk in response.iter_content(1024 * 256):
                handle.write(chunk)
        size = partial.stat().st_size
        with open(partial, "rb") as handle:
            is_pdf = handle.read(len(PDF_MAGIC)) == PDF_MAGIC
        if not is_pdf or (expected and int(expected) != size):
            partial.unlink()
            reason = "not a PDF" if not is_pdf else f"got {size} of {expected} bytes"
            raise ValueError(reason)
        os.replace(partial, destination)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_file(client, record, destination, output):
    """Download one PDF unless a complete copy exists, and fill in its record."""
    record["local_path"] = destination.relative_to(output).as_posix()
    if destination.exists():
        record["status"] = "already_present"
    else:
        client.download(record["url"], destination)
        record["status"] = "downloaded"
    record["bytes"] = destination.stat().st_size
    record["sha256"] = sha256_of(destination)


def write_csv(path, columns, rows):
    # utf-8-sig so Excel displays Czech characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(output, category, bodies, errors):
    body_rows, cert_rows, file_rows = [], [], []
    for body in bodies:
        ids = {key: body[key] for key in ("cab_number", "name", "entry_slug")}
        certificates = body["certificates"]
        body_rows.append({
            **body,
            "certificate_numbers": "; ".join(c["certificate_number"] for c in certificates),
            "authentication_links": "; ".join(body["authentication_links"]),
            "file_count": sum(len(c["files"]) for c in certificates),
        })
        for certificate in certificates:
            cert_rows.append({**ids, **certificate})
            for record in certificate["files"]:
                file_rows.append({
                    **ids, "certificate_number": certificate["certificate_number"], **record,
                })
    write_csv(output / "bodies.csv", BODY_COLUMNS, body_rows)
    write_csv(output / "certificates.csv", CERT_COLUMNS, cert_rows)
    write_csv(output / "files.csv", FILE_COLUMNS, file_rows)
    errors_path = output / "errors.csv"
    if errors:
        write_csv(errors_path, ERROR_COLUMNS, errors)
    elif errors_path.exists():
        errors_path.unlink()
    (output / "data.json").write_text(json.dumps({
        "source": "Czech Accreditation Institute (cai.cz), accredited bodies database",
        "category": category,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bodies": bodies,
        "errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(body_rows), len(cert_rows), file_rows


def run(args):
    output = Path(args.output)
    (output / "raw_html").mkdir(parents=True, exist_ok=True)
    client = Client(args.base_url, args.delay)
    errors, bodies = [], []

    print(f"Reading the register listing ({args.category})...", flush=True)
    entries = client.list_entries(args.category)
    print(f"{len(entries)} entries found.", flush=True)

    for index, entry in enumerate(entries, 1):
        slug = entry_slug(entry["token"])
        print(f"[{index}/{len(entries)}] {entry['title']}", flush=True)
        try:
            html, page_url = client.detail(entry)
            (output / "raw_html" / f"{slug}.html").write_text(html, encoding="utf-8")
            body = parse_detail_page(html, page_url)
        except Exception as exc:
            errors.append({"stage": "detail", "item": entry["title"], "error": str(exc)})
            print(f"    FAILED: {exc}", flush=True)
            continue
        body["entry_slug"] = slug
        bodies.append(body)

        records = [record for cert in body["certificates"] for record in cert["files"]]
        if not records:
            errors.append({"stage": "detail", "item": entry["title"], "error": "no documents listed"})
        if args.no_pdfs:
            continue
        for record in records:
            destination = output / "pdfs" / slug / safe_name(record["filename"])
            try:
                fetch_file(client, record, destination, output)
                print(f"    {record['status']}: {record['filename']}", flush=True)
            except Exception as exc:
                record["status"] = "failed"
                errors.append({"stage": "pdf", "item": record["url"], "error": str(exc)})
                print(f"    FAILED {record['filename']}: {exc}", flush=True)

    body_count, cert_count, file_rows = write_outputs(output, args.category, bodies, errors)
    fetched = sum(1 for row in file_rows if row.get("status") in ("downloaded", "already_present"))
    print(f"\nDone: {body_count}/{len(entries)} entries, {cert_count} certificates, "
          f"{fetched}/{len(file_rows)} PDFs, {len(errors)} errors. Output: {output.resolve()}")
    return 1 if errors or body_count != len(entries) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-o", "--output", default="cai_output", help="output folder")
    parser.add_argument("--category", default=DEFAULT_CATEGORY,
                        help="register category slug (the kategorie_subjektu value in the site's URL)")
    parser.add_argument("--delay", type=float, default=5.0,
                        help="seconds between requests (robots.txt asks for 5)")
    parser.add_argument("--no-pdfs", action="store_true", help="collect the data only")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
