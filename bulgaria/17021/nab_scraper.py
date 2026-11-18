#!/usr/bin/env python3
"""Download Management system certification bodies from the BAS (nab-bas.bg) register.

Collects every body in the accreditation field (any status), its Bulgarian and
English details, offices, and all attached documents: certificate, accreditation
order and full-scope annex.

Setup:  pip install requests beautifulsoup4
Run:    python nab_scraper.py
        python nab_scraper.py --out data --delay 2
        python nab_scraper.py --no-files          (details only)

Output (default folder: nab_management_system_bodies):
    bodies.json   full structured data
    bodies.csv    one row per body
    files.csv     one row per document, with path, size and SHA-256
    errors.log    only if something failed
    bodies/<certificate> - <legal entity> [<id>]/
        page_bg.html, page_en.html, and the downloaded documents

Safe to re-run: documents already on disk are not downloaded again.
Exit code is 1 if any page or document failed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
import sys
import time
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.nab-bas.bg"
LIST_PATH = "/registar.html"
MANAGEMENT_SYSTEMS_FIELD = "6"
# Blank means "any"; the rest catch anything the unfiltered list might omit.
# 1 valid, 4 suspended, 5 withdrawn, 6 transferred.
STATUS_FILTERS = ["", "1", "4", "5", "6"]
MAX_PAGES = 200

META_KEYS = {
    "Валиден от": "valid_from",
    "Валиден до": "valid_to",
    "Статус": "status",
    "Сертификат №": "certificate_number",
    "Лице за контакт": "contact_person",
}
DETAIL_KEYS = {
    "Наименование на ООС": "name",
    "Юридическо лице": "legal_entity",
    "Дата на първоначална акредитация": "initial_accreditation_date",
    "Област": "field",
    "Обхват": "scope",
}
BODY_COLUMNS = [
    "id", "certificate_number", "name", "legal_entity", "status", "valid_from",
    "valid_to", "initial_accreditation_date", "field", "contact_person", "scope",
    "scope_en", "offices", "url_bg", "url_en",
]
FILE_COLUMNS = [
    "body_id", "certificate_number", "legal_entity", "language", "label", "file_id",
    "extension", "listed_size", "bytes", "sha256", "content_type",
    "original_filename", "path", "url", "result",
]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def safe_name(text: str, limit: int = 90) -> str:
    """Make text usable as a single file or folder name on any OS."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    return clean(text)[:limit].strip(" .") or "unnamed"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "nab-register-scraper/1.0 (python-requests)"
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


class Scraper:
    def __init__(self, args: argparse.Namespace):
        self.base = args.base_url.rstrip("/")
        self.out = Path(args.out)
        self.delay = args.delay
        self.field = args.field
        self.download = not args.no_files
        self.session = make_session()
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)
        print(f"  ERROR: {message}", file=sys.stderr)

    def pause(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    def get(self, url: str, **kwargs) -> requests.Response:
        response = self.session.get(url, timeout=60, **kwargs)
        response.raise_for_status()
        response_time_pause = not kwargs.get("stream")
        if response_time_pause:
            self.pause()
        return response

    # ---- listing ---------------------------------------------------------

    def list_page(self, page: int, status: str) -> list[tuple[str, str]]:
        form = {
            "pn": str(page),
            "Filters.AccreditationFieldID": self.field,
            "Filters.CertificateNumber": "",
            "Filters.City": "",
            "Filters.Title": "",
            "Filters.AccreditationScope": "",
            "Filters.AccreditationStatusID": status,
        }
        response = self.session.post(self.base + LIST_PATH, data=form, timeout=60)
        response.raise_for_status()
        self.pause()
        soup = BeautifulSoup(response.text, "html.parser")
        return [(a["href"], clean(a.get_text())) for a in soup.select("a.result[href]")]

    def collect_listing(self) -> dict[str, str]:
        """Return {relative detail URL: listing title}, across every status filter."""
        found: dict[str, str] = {}
        for status in STATUS_FILTERS:
            seen_this_filter: set[str] = set()
            for page in range(1, MAX_PAGES + 1):
                rows = self.list_page(page, status)
                new = [r for r in rows if r[0] not in seen_this_filter]
                if not new:  # empty page, or the site repeating the last one
                    break
                seen_this_filter.update(r[0] for r in new)
                found.update(new)
            print(f"  status filter {status or 'any'}: {len(seen_this_filter)} bodies")
        return found

    # ---- detail page -----------------------------------------------------

    def parse_detail(self, html: str, page_url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1.page-title")
        meta = {}
        for item in soup.select(".meta__item"):
            key, value = item.select_one(".meta__title"), item.select_one(".meta__content")
            if key and value:
                meta[clean(key.get_text())] = clean(value.get_text())

        details: dict[str, str] = {}
        for paragraph in soup.select(".page-content p"):
            if paragraph.find("strong"):
                details.update(labeled_values(paragraph))

        files = []
        for link in soup.select("a.file[href]"):
            info = [clean(s.get_text()) for s in link.select(".file__meta span")]
            label_node = BeautifulSoup(str(link), "html.parser").a
            for extra in label_node.select(".file__meta, svg"):
                extra.decompose()
            url = urljoin(page_url, link["href"])
            files.append({
                "label": clean(label_node.get_text()),
                "extension": info[0].lower() if info else "",
                "listed_size": info[1] if len(info) > 1 else "",
                "url": url,
                "file_id": parse_qs(urlparse(url).query).get("id", [""])[0],
            })

        offices = []
        for office in soup.select(".office"):
            city = office.select_one(".office__city")
            name = office.select_one(".office__details h5")
            box = office.select_one(".office__details")
            values = labeled_values(box) if box else {}
            offices.append({
                "city": clean(city.get_text()) if city else "",
                "name": clean(name.get_text()) if name else "",
                "emails": sorted({
                    a["href"].split(":", 1)[1].split("?")[0]
                    for a in office.select('a[href^="mailto:"]')
                }),
                "contacts": {k: v.strip(" ,") for k, v in values.items()},
                "text": clean(box.get_text(" ")) if box else "",
            })

        english = soup.select_one('a[href*="/en/registers/"]')
        return {
            "title": clean(title.get_text()) if title else "",
            "meta": meta,
            "details": details,
            "files": files,
            "offices": offices,
            "english_url": urljoin(page_url, english["href"]) if english else "",
        }

    # ---- documents -------------------------------------------------------

    def fetch_file(self, spec: dict, folder: Path, used: set[str]) -> dict:
        label = safe_name(spec["label"] or f"file_{spec['file_id']}", 70)
        row = {**spec, "bytes": "", "sha256": "", "content_type": "",
               "original_filename": "", "path": "", "result": ""}
        if not self.download:
            row["result"] = "skipped"
            return row

        name = label + spec["extension"]
        if name.lower() in used:
            name = f"{label}_{spec['file_id']}{spec['extension']}"
        target = folder / name

        if spec["extension"] and target.exists() and target.stat().st_size:
            used.add(name.lower())
            row.update(path=str(target), result="already_downloaded")
            row.update(bytes=target.stat().st_size, sha256=sha256_of(target))
            return row

        try:
            with self.session.get(spec["url"], stream=True, timeout=120) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                row["content_type"] = content_type
                row["original_filename"] = header_filename(response.headers)
                if content_type.startswith("text/html"):
                    raise ValueError("server returned a web page instead of a document")
                if not spec["extension"]:
                    extension = Path(row["original_filename"]).suffix.lower() or (
                        mimetypes.guess_extension(content_type.split(";")[0]) or ".bin")
                    target = folder / (label + extension)
                    name = target.name
                part = target.with_name(target.name + ".part")
                digest = hashlib.sha256()
                with part.open("wb") as handle:
                    for chunk in response.iter_content(65536):
                        handle.write(chunk)
                        digest.update(chunk)
                if part.stat().st_size == 0:
                    part.unlink()
                    raise ValueError("empty document")
                part.replace(target)
        except (requests.RequestException, OSError, ValueError) as exc:
            row["result"] = "failed"
            self.error(f"document {spec['url']}: {exc}")
            return row
        finally:
            self.pause()

        used.add(name.lower())
        row.update(path=str(target), bytes=target.stat().st_size,
                   sha256=digest.hexdigest(), result="downloaded")
        return row

    # ---- orchestration ---------------------------------------------------

    def scrape_body(self, relative_url: str, listing_title: str) -> tuple[dict, list[dict]]:
        url_bg = urljoin(self.base + "/", relative_url.lstrip("/"))
        match = re.search(r"-(\d+)\.html$", urlparse(url_bg).path)
        body_id = match.group(1) if match else safe_name(Path(urlparse(url_bg).path).stem)

        html_bg = self.get(url_bg).text
        bg = self.parse_detail(html_bg, url_bg)

        en, html_en = None, None
        if bg["english_url"]:
            try:
                html_en = self.get(bg["english_url"]).text
                en = self.parse_detail(html_en, bg["english_url"])
            except requests.RequestException as exc:
                self.error(f"English page {bg['english_url']}: {exc}")

        meta, details = bg["meta"], bg["details"]
        record = {
            "id": body_id,
            "listing_title": listing_title,
            "name": details.get("Наименование на ООС") or bg["title"],
            "url_bg": url_bg,
            "url_en": bg["english_url"],
        }
        for source, keys in ((meta, META_KEYS), (details, DETAIL_KEYS)):
            for label, key in keys.items():
                if key != "name":
                    record[key] = source.get(label, "")
        record["scope_en"] = scope_en(en) if en else ""
        record["offices"] = bg["offices"]
        record["all_fields_bg"] = {**meta, **details}
        if en:
            record["all_fields_en"] = {**en["meta"], **en["details"]}
            record["offices_en"] = en["offices"]

        folder_name = safe_name(
            f"{record.get('certificate_number') or 'no-certificate'} - "
            f"{record.get('legal_entity') or record['name']}", 100)
        folder = self.out / "bodies" / f"{folder_name} [{body_id}]"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "page_bg.html").write_text(html_bg, encoding="utf-8")
        if html_en:
            (folder / "page_en.html").write_text(html_en, encoding="utf-8")

        # The two language pages can share documents, so fetch each id only once.
        file_rows, used, seen = [], set(), set()
        versions = [("bg", bg)] + ([("en", en)] if en else [])
        for language, version in versions:
            for spec in version["files"]:
                key = spec["file_id"] or spec["url"]
                if key in seen:
                    continue
                seen.add(key)
                row = self.fetch_file(spec, folder, used)
                row.update(
                    body_id=body_id, language=language,
                    certificate_number=record.get("certificate_number", ""),
                    legal_entity=record.get("legal_entity", ""),
                )
                file_rows.append(row)
        record["files"] = file_rows
        return record, file_rows

    def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        print("Reading the register list...")
        listing = self.collect_listing()
        print(f"Found {len(listing)} bodies.")
        if not listing:
            self.error("the list came back empty; the site layout may have changed")

        records, all_files = [], []
        for index, (url, title) in enumerate(sorted(listing.items()), 1):
            print(f"[{index}/{len(listing)}] {title}")
            try:
                record, file_rows = self.scrape_body(url, title)
            except (requests.RequestException, OSError) as exc:
                self.error(f"body {url}: {exc}")
                continue
            records.append(record)
            all_files.extend(file_rows)

        write_outputs(self.out, records, all_files)
        log = self.out / "errors.log"
        if self.errors:
            log.write_text("\n".join(self.errors) + "\n", encoding="utf-8")
        elif log.exists():
            log.unlink()

        got = sum(r["result"] in ("downloaded", "already_downloaded") for r in all_files)
        print(f"\nDone: {len(records)}/{len(listing)} bodies, "
              f"{got}/{len(all_files)} documents, {len(self.errors)} errors.")
        print(f"Saved to: {self.out.resolve()}")
        return 1 if self.errors or not records else 0


def labeled_values(node: Tag) -> dict[str, str]:
    """Turn '<strong>Label</strong>: value<br>more' into {'Label': 'value\\nmore'}.

    Commented-out markup is ignored; the live site keeps old fields in comments.
    """
    values: dict[str, list[str]] = {}
    current = None

    def walk(parent: Tag) -> None:
        nonlocal current
        for child in parent.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                if current:
                    values[current].append(str(child))
            elif child.name == "strong":
                current = clean(child.get_text()).rstrip(":")
                values.setdefault(current, [])
            elif child.name == "br":
                if current:
                    values[current].append("\n")
            elif child.name not in ("h5", "script", "style"):
                walk(child)

    walk(node)
    result = {}
    for key, parts in values.items():
        lines = [clean(line) for line in "".join(parts).split("\n")]
        text = "\n".join(line for line in lines if line)
        result[key] = re.sub(r"^:\s*", "", text)
    return result


def scope_en(version: dict) -> str:
    for key, value in version["details"].items():
        if "scope" in key.lower():
            return value
    return ""


def header_filename(headers) -> str:
    raw = headers.get("Content-Disposition", "")
    if not raw:
        return ""
    message = Message()
    message["Content-Disposition"] = raw
    name = message.get_filename() or ""
    try:  # HTTP clients expose UTF-8 header bytes as Latin-1
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return Path(name.replace("\\", "/")).name


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_offices(offices: list[dict]) -> str:
    return " | ".join(clean(f"{o['city']}: {o['text']}") for o in offices)


def write_outputs(out: Path, records: list[dict], files: list[dict]) -> None:
    (out / "bodies.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    # utf-8-sig makes Excel show Cyrillic correctly.
    with (out / "bodies.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, BODY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({**record, "offices": format_offices(record["offices"])})
    with (out / "files.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, FILE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="nab_management_system_bodies", help="output folder")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--no-files", action="store_true", help="skip document downloads")
    parser.add_argument("--field", default=MANAGEMENT_SYSTEMS_FIELD,
                        help="accreditation field id (default 6: management systems)")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    return Scraper(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
