#!/usr/bin/env python3
"""Download NAH (nah.gov.hu) accredited-body data and their PDF documents.

Default target: Management Systems Certification bodies. Requires Python 3.8+
and nothing else.

    python nah_scraper.py                      # writes to ./nah_output
    python nah_scraper.py --out D:/nah --no-pdfs
    python nah_scraper.py --category kalibralas--calibration   # another type

Output:
    organizations.csv / .json   one row per accreditation (NAH number)
    documents.csv               one row per PDF, with local path and SHA-256
    pdfs/<NAH number>_<name>/   the "Részletező Okirat" PDFs
    raw/                        untouched API responses
    errors.log                  only if something failed

Safe to re-run: PDFs already on disk are skipped.
"""
import argparse
import csv
import hashlib
import html
import html.parser
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://nah.gov.hu"
DEFAULT_CATEGORY = "iranyitasi-rendszertanusitas--management-systems-c"

# The search endpoint answers HTTP 500 without Accept-Language / X-metaData.
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "hu",
    "X-metaData": "false",
    "User-Agent": "nah-scraper/1.0",
}

# Status filter combinations. Each org's real status is read from its result.
SEARCHES = [
    {"valid": "true", "suspended": "true", "withdrawn": "false"},
    {"valid": "false", "suspended": "true", "withdrawn": "false"},
    {"valid": "false", "suspended": "false", "withdrawn": "true"},
]

ORG_FIELDS = [
    "nah_number", "name", "status", "valid_from", "valid_to", "schemes",
    "location", "phone", "email", "web", "contact", "contact_rank",
    "document_count", "current_document", "scope_and_notes", "page_url",
]
DOC_FIELDS = [
    "nah_number", "name", "title", "is_current", "url", "local_path",
    "size_bytes", "sha256", "download_status",
]


class TextExtractor(html.parser.HTMLParser):
    BLOCK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(markup):
    parser = TextExtractor()
    parser.feed(markup or "")
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def ascii_slug(text, max_len=60):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:max_len].rstrip("_") or "unnamed"


def parse_validity(value):
    """'2021. 10. 14. - 2026. 10. 14.' -> ('2021-10-14', '2026-10-14')."""
    found = re.findall(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", value or "")
    dates = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in found]
    return (dates + ["", ""])[0], (dates + ["", ""])[1]


class Scraper:
    def __init__(self, args):
        self.base = args.base_url.rstrip("/")
        self.host = urllib.parse.urlparse(self.base).netloc
        self.out = Path(args.out)
        self.category = args.category
        self.delay = args.delay
        self.download_pdfs = not args.no_pdfs
        self.errors = []
        (self.out / "raw").mkdir(parents=True, exist_ok=True)

    def error(self, message):
        self.errors.append(message)
        print(f"  ! {message}", file=sys.stderr)

    def fetch(self, url, headers):
        last = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = response.read()
                time.sleep(self.delay)
                return body
            except (urllib.error.URLError, OSError) as exc:
                last = exc
                # 4xx will not change on retry.
                if isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                    break
        raise RuntimeError(f"{url}: {last}")

    def api(self, path, raw_name):
        url = f"{self.base}/admin/api/content/{path}"
        body = self.fetch(url, HEADERS)
        (self.out / "raw" / f"{raw_name}.json").write_bytes(body)
        data = json.loads(body.decode("utf-8")).get("responseData") or {}
        return data

    def crawl_categories(self):
        """Return {org url: {name, nah_number, url, schemes}} walking the tree."""
        orgs, seen = {}, set()

        def walk(path, title, top):
            if path in seen:
                return
            seen.add(path)
            data = self.api(path, "category_" + ascii_slug(path.split("/")[-2], 80))
            payload = data.get("data") or {}
            for org in payload.get("organizations") or []:
                entry = orgs.setdefault(org["url"], {**org, "schemes": []})
                if not top and title and title not in entry["schemes"]:
                    entry["schemes"].append(title)
            for child in payload.get("categories") or []:
                print(f"  {child['title'].strip()} ({child.get('children_count')})")
                walk(child["url"], child["title"].strip(), False)

        walk(f"hu/kategoriak/{self.category}/", "", True)
        return orgs

    def search_statuses(self, orgs):
        """Merge in each org's status and scheme list from the search endpoint."""
        for flags in SEARCHES:
            query = urllib.parse.urlencode(
                {"search": "", **flags, "category_slug": self.category})
            label = "_".join(k for k, v in flags.items() if v == "true")
            try:
                data = self.api(f"szervezet-kereses?{query}", f"search_{label}")
            except (RuntimeError, ValueError) as exc:
                self.error(f"search {label} failed: {exc}")
                continue
            payload = data.get("data") or {}
            if payload.get("max_size_exceeded"):
                self.error(f"search {label}: site reported max_size_exceeded")
            for item in payload.get("results") or []:
                entry = orgs.setdefault(item["url"], {**item, "schemes": []})
                details = item.get("organizationDetails") or {}
                if details.get("status"):
                    entry["status"] = details["status"]
                entry["search_documents"] = details.get("documentResults") or []
                for scheme in item.get("categories") or []:
                    scheme = scheme.strip()
                    if scheme not in entry["schemes"]:
                        entry["schemes"].append(scheme)

    def fetch_org(self, entry):
        slug = ascii_slug(entry.get("nah_number") or entry["url"], 80)
        data = self.api(entry["url"], "org_" + slug + "_" + ascii_slug(entry["url"][-12:]))
        payload = data.get("data") or {}
        valid_from, valid_to = parse_validity(payload.get("valid"))
        documents, urls = [], set()
        for doc in (payload.get("documents") or []) + entry.get("search_documents", []):
            if doc.get("url") and doc["url"] not in urls:
                urls.add(doc["url"])
                documents.append(doc)
        current = [d["title"] for d in documents if "hat\u00e1lyos" in d.get("title", "").lower()]
        row = {
            "nah_number": payload.get("nah_number") or entry.get("nah_number", ""),
            "name": payload.get("name") or entry.get("name", ""),
            "status": entry.get("status", ""),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "schemes": " ; ".join(entry.get("schemes", [])),
            "location": payload.get("location", ""),
            "phone": payload.get("phone", ""),
            "email": payload.get("email", ""),
            "web": payload.get("web", ""),
            "contact": payload.get("contact", ""),
            "contact_rank": payload.get("contact_rank", ""),
            "document_count": len(documents),
            "current_document": " ; ".join(current),
            "scope_and_notes": html_to_text(payload.get("html", "")),
            "page_url": f"{self.base}/{entry['url']}",
        }
        return row, documents

    def save_document(self, row, doc, index):
        info = {
            "nah_number": row["nah_number"], "name": row["name"],
            "title": doc.get("title", ""),
            "is_current": "hat\u00e1lyos" in doc.get("title", "").lower(),
            "url": doc["url"], "local_path": "", "size_bytes": "", "sha256": "",
            "download_status": "skipped (--no-pdfs)",
        }
        if not self.download_pdfs:
            return info
        # URLs come from the remote site: stay on its host.
        url = urllib.parse.urljoin(self.base + "/", doc["url"])
        if urllib.parse.urlparse(url).netloc != self.host:
            info["download_status"] = "refused: other host"
            self.error(f"refused off-site document {url}")
            return info
        folder = self.out / "pdfs" / (
            ascii_slug(row["nah_number"], 30) + "_" + ascii_slug(row["name"], 50))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{index:02d}_{ascii_slug(doc.get('title'), 70)}.pdf"
        info["local_path"] = path.relative_to(self.out).as_posix()
        try:
            if path.exists() and path.stat().st_size and path.read_bytes()[:5] == b"%PDF-":
                body = path.read_bytes()
                info["download_status"] = "already on disk"
            else:
                body = self.fetch(urllib.parse.quote(url, safe=":/?=&%"), {
                    "User-Agent": HEADERS["User-Agent"], "Accept": "application/pdf,*/*"})
                if body[:5] != b"%PDF-":
                    raise RuntimeError("response is not a PDF")
                part = path.with_suffix(".part")
                part.write_bytes(body)
                part.replace(path)
                info["download_status"] = "downloaded"
            info["size_bytes"] = len(body)
            info["sha256"] = hashlib.sha256(body).hexdigest()
        except (RuntimeError, OSError) as exc:
            info["download_status"] = f"FAILED: {exc}"
            info["local_path"] = ""
            self.error(f"{row['nah_number']} {doc.get('title')}: {exc}")
        return info

    def write_csv(self, name, fields, rows):
        # utf-8-sig so Excel shows Hungarian characters correctly.
        with open(self.out / name, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def run(self):
        print(f"Categories under {self.category}:")
        orgs = self.crawl_categories()
        self.search_statuses(orgs)
        print(f"{len(orgs)} accreditations found. Fetching details...")
        rows, docs = [], []
        for number, entry in enumerate(orgs.values(), 1):
            print(f"[{number}/{len(orgs)}] {entry.get('nah_number')} {entry.get('name')}")
            try:
                row, documents = self.fetch_org(entry)
            except (RuntimeError, ValueError) as exc:
                self.error(f"{entry['url']}: {exc}")
                continue
            rows.append(row)
            for index, doc in enumerate(documents, 1):
                docs.append(self.save_document(row, doc, index))
        rows.sort(key=lambda r: (r["name"].casefold(), r["nah_number"]))
        self.write_csv("organizations.csv", ORG_FIELDS, rows)
        self.write_csv("documents.csv", DOC_FIELDS, docs)
        (self.out / "organizations.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.errors:
            (self.out / "errors.log").write_text("\n".join(self.errors), encoding="utf-8")
        statuses = {}
        for row in rows:
            statuses[row["status"] or "unknown"] = statuses.get(row["status"] or "unknown", 0) + 1
        saved = sum(1 for d in docs if d["sha256"])
        print(f"\nDone: {len(rows)} accreditations {statuses}; "
              f"{saved}/{len(docs)} PDFs on disk; {len(self.errors)} errors. Output: {self.out}")
        return 1 if self.errors else 0


def main():
    parser = argparse.ArgumentParser(description="Scrape NAH accredited bodies.")
    parser.add_argument("--out", default="nah_output", help="output folder")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="category slug")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--no-pdfs", action="store_true", help="metadata only")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=argparse.SUPPRESS)
    return Scraper(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())