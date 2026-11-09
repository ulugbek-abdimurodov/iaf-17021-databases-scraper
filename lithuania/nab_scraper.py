#!/usr/bin/env python3
"""Download management system certification bodies from the Lithuanian NAB register.

Source: http://db.nab.lt/ais/accreditation
        (ISO/IEC 17021-1, accreditation certificates numbered LA.04.xxx)

For each body this saves the raw API record, the detail page, its labelled
fields and every attached document (certificate/scope PDFs). It also checks the
suspended and withdrawn lists for LA.04 entries.

Usage:  python3 nab_scraper.py [--out DIR] [--delay SECONDS]
Needs Python 3.8+ and nothing else. Re-running skips files already downloaded.

Output:
  DIR/bodies.csv                  one row per body
  DIR/bodies.json                 everything, including document paths and hashes
  DIR/<certificate>_<name>/
      record.json                 raw API record plus labelled detail-page fields
      page.html                   detail page as served
      <document name>.pdf
"""
import argparse
import csv
import http.client
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "http://db.nab.lt/ais"
PAGE_SIZE = 100
RETRIES = 4
TIMEOUT = 10
USER_AGENT = "nab-scraper/1.0"
CERT_PREFIX = "LA.04."

# (status label, searchType value used by the register's type dropdown)
LISTS = [
    ("active", "27155339-5a76-43d3-b389-57532a33bba0"),
    ("suspended", "540e989a-f976-4ec1-9490-59d68e03acff"),
    ("withdrawn", "403b229c-acbf-4987-be95-7788214e5f54"),
]


def fetch(url):
    """GET a URL, retrying on network errors and 5xx/429. Returns (bytes, content type)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise
            failure = error
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
            failure = error
        if attempt < RETRIES - 1:
            time.sleep(2 ** attempt)
    raise failure


def list_records(base, search_type, delay):
    """Return every record in one list, following the API's pagination."""
    records, start = [], 0
    while True:
        query = urllib.parse.urlencode(
            {"draw": 1, "start": start, "length": PAGE_SIZE, "searchType": search_type}
        )
        body, _ = fetch(f"{base}/rest/accreditation?{query}")
        page = json.loads(body)
        records.extend(page["data"])
        start += len(page["data"])
        if not page["data"] or start >= page["recordsFiltered"]:
            if start != page["recordsFiltered"]:
                raise RuntimeError(
                    f"expected {page['recordsFiltered']} records, got {start}"
                )
            return records
        time.sleep(delay)


class DetailPage(HTMLParser):
    """Collects label/value table rows and document links from a detail page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {}
        self.documents = {}
        self._cells = None
        self._cell = None
        self._doc_id = None
        self._doc_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cells = []
        elif tag in ("th", "td") and self._cells is not None:
            self._cell = [tag, []]
        elif tag == "a":
            match = re.search(r"/document/([0-9a-fA-F-]+)", dict(attrs).get("href") or "")
            if match:
                self._doc_id, self._doc_text = match.group(1), []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[1].append(data)
        if self._doc_id:
            self._doc_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._doc_id:
            self.documents[self._doc_id] = clean("".join(self._doc_text))
            self._doc_id = None
        elif tag in ("th", "td") and self._cell is not None:
            self._cells.append((self._cell[0], clean(" ".join(self._cell[1]))))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            labels = [text for kind, text in self._cells if kind == "th" and text]
            values = [text for kind, text in self._cells if kind == "td"]
            if labels and values:
                self.fields[labels[-1]] = " | ".join(values)
            self._cells = None


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def slug(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9.]+", "_", ascii_text).strip("_.") or "unnamed"


def safe_filename(name, doc_id):
    """Keep the register's file name, minus anything a filesystem would reject."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip(" .")
    name = re.sub(r"\.{2,}", ".", name)
    return name or doc_id


def download_document(base, doc_id, name, folder, used_names):
    """Download one document unless already present. Returns its manifest entry."""
    filename = safe_filename(name, doc_id)
    if filename.lower() in used_names:
        filename = f"{Path(filename).stem}_{doc_id[:8]}{Path(filename).suffix}"
    used_names.add(filename.lower())
    target = folder / filename
    entry = {
        "id": doc_id,
        "name": name,
        "url": f"{base}/document/{doc_id}",
        "file": str(target),
    }
    if target.exists() and target.stat().st_size:
        data, entry["skipped_existing"] = target.read_bytes(), True
    else:
        data, content_type = fetch(entry["url"])
        if "pdf" in content_type.lower() and not data.startswith(b"%PDF"):
            raise ValueError(f"{entry['url']} is labelled PDF but is not one")
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.replace(target)
    entry["bytes"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    return entry


def scrape_body(base, record, status, out, delay):
    """Save one body's page, record and documents. Returns its manifest entry."""
    certificate = record.get("certificate") or record["id"]
    folder = out / f"{slug(certificate)}_{slug(record.get('holder') or '')}"
    folder.mkdir(parents=True, exist_ok=True)

    html, _ = fetch(f"{base}/accreditation/{record['id']}")
    (folder / "page.html").write_bytes(html)
    page = DetailPage()
    page.feed(html.decode("utf-8", "replace"))

    # The API and the page should list the same files; take the union in case not.
    wanted = {d["id"]: d.get("name") for d in record.get("documents") or []}
    for doc_id, name in page.documents.items():
        wanted.setdefault(doc_id, name)

    documents, errors, used_names = [], [], set()
    for doc_id, name in wanted.items():
        time.sleep(delay)
        try:
            documents.append(download_document(base, doc_id, name, folder, used_names))
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, ValueError) as error:
            errors.append({"id": doc_id, "name": name, "error": str(error)})

    entry = {
        "status": status,
        "folder": str(folder),
        "detail_url": f"{base}/accreditation/{record['id']}",
        "record": record,
        "detail_fields": page.fields,
        "documents": documents,
        "document_errors": errors,
    }
    (folder / "record.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def write_csv(path, bodies):
    """One row per body: fixed columns, API scalars, then the page's labelled fields."""
    rows, api_keys, page_keys = [], [], []
    for body in bodies:
        scalars = {
            k: v
            for k, v in body["record"].items()
            if isinstance(v, (str, int, float, bool)) or v is None
        }
        row = {
            "status": body["status"],
            "type": (body["record"].get("type") or {}).get("name"),
            "detail_url": body["detail_url"],
            "folder": body["folder"],
            "document_names": "; ".join(d["name"] or "" for d in body["documents"]),
            "document_urls": "; ".join(d["url"] for d in body["documents"]),
            **scalars,
            **body["detail_fields"],
        }
        rows.append(row)
        api_keys += [k for k in scalars if k not in api_keys]
        page_keys += [k for k in body["detail_fields"] if k not in page_keys]
    columns = ["status", "type", "detail_url", "folder", "document_names", "document_urls"]
    columns += api_keys + [k for k in page_keys if k not in api_keys]
    # utf-8-sig so Excel displays Lithuanian characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="nab_ms_bodies", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--base", default=BASE, help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    bodies = []
    for status, search_type in LISTS:
        records = list_records(args.base, search_type, args.delay)
        # The suspended and withdrawn lists mix all accreditation types.
        matches = [
            r for r in records
            if status == "active" or (r.get("certificate") or "").startswith(CERT_PREFIX)
        ]
        print(f"{status}: {len(matches)} body/bodies (of {len(records)} listed)")
        for record in matches:
            time.sleep(args.delay)
            print(f"  {record.get('certificate')}  {record.get('holder')}")
            bodies.append(scrape_body(args.base, record, status, out, args.delay))

    (out / "bodies.json").write_text(
        json.dumps(bodies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(out / "bodies.csv", bodies)

    document_count = sum(len(b["documents"]) for b in bodies)
    failures = [(b["record"].get("certificate"), e) for b in bodies for e in b["document_errors"]]
    print(f"\nSaved {len(bodies)} bodies and {document_count} documents to {out}/")
    for certificate, error in failures:
        print(f"FAILED {certificate}: {error['name']}: {error['error']}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
