#!/usr/bin/env python3
"""Download accreditation data from the Croatian Accreditation Agency register.

Source: https://akreditacija.gov.hr/frontend/registar-akreditacija

By default this fetches the management system certification bodies (scheme
"Certifikacijska tijela za certifikaciju sustava upravljanja"), and saves:

    haa_data/
      bodies.csv                     one row per body (opens cleanly in Excel)
      bodies.json                    all fields, plus file names and checksums
      4184_bureau-veritas-.../
        record.json                  the full register record
        certificate.pdf              accreditation certificate with its annex
        document_text.txt            the register's text copy of the document

Needs Python 3.8+ and nothing else.

    python haa_scraper.py                     # management system bodies
    python haa_scraper.py --scheme "proizvoda"  # any scheme, by regex
    python haa_scraper.py --all               # all 458 register entries
    python haa_scraper.py --list-schemes      # scheme names and counts

Re-running skips PDFs already on disk; use --force to fetch them again.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

BASE_URL = "https://akreditacija.gov.hr/backend"
DEFAULT_SCHEME = r"certifikaciju sustava upravljanja"
PAGE_SIZE = 100
RETRIES = 4
TIMEOUT = 60
HEADERS = {"User-Agent": "haa-register-scraper/1.0", "Accept": "*/*"}

# Register field -> CSV column.
CSV_FIELDS = {
    "BrojPotvrde": "certificate_number",
    "AkreditornoTijelo": "body",
    "UlicaKucniBroj": "street",
    "Mjesto": "city",
    "Telefon": "phone",
    "WebAdresa": "website",
    "ImePrezime": "contact_person",
    "Norma": "standard",
    "AkreditacijskaShema": "scheme",
    "Podrucje": "scope",
    "DatumIsteka": "expiry_date",
    "ID": "id",
}
# The register's search index holds the document text; it gets its own file.
TEXT_FIELD = "PretragaKljucnaRijec"


def request(url, method="GET"):
    """Return (body, content_type), retrying temporary failures with backoff."""
    req = urllib.request.Request(url, method=method, headers=HEADERS)
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            # 4xx will not fix itself, so fail straight away.
            if exc.code < 500 or attempt == RETRIES:
                raise
            problem = f"HTTP {exc.code}"
        except OSError as exc:
            if attempt == RETRIES:
                raise
            problem = str(exc)
        wait = 2 ** attempt
        print(f"  {problem}; retrying in {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise AssertionError("unreachable")


def fetch_register(base_url, delay):
    """Fetch every register record, page by page."""
    records, total = [], None
    while total is None or len(records) < total:
        query = urllib.parse.urlencode({
            "culture": "hr",
            "sort": "AkreditornoTijelo asc",
            "top": PAGE_SIZE,
            "skip": len(records),
        })
        url = f"{base_url}/Rest/Akreditacija/RegistarBrowse/RecordsAndTotalCount?{query}"
        data = json.loads(request(url)[0])
        page, total = data["Records"], data["TotalCount"]
        if not page:
            break
        records.extend(page)
        print(f"Register: {len(records)}/{total}")
        if len(records) < total:
            time.sleep(delay)
    if len(records) != total:
        raise RuntimeError(f"Register reports {total} records, got {len(records)}")
    return records


def fetch_pdf(base_url, record):
    # Must be the record's ID: PotvrdaDokumentID returns HTTP 500 for some bodies.
    url = f"{base_url}/api/Registar/DohvatiDokument/{record['ID']}?culture=hr"
    body, content_type = request(url, method="POST")
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"not a PDF (Content-Type: {content_type})")
    return body


def slugify(text, limit=60):
    """Make a safe folder name from a body name (ASCII only, no path characters)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].rstrip("-") or "body"


def clean_date(value):
    """Reduce an ISO timestamp to its date; leave anything else unchanged."""
    match = re.match(r"\d{4}-\d{2}-\d{2}", value or "")
    return match.group(0) if match else value


def folder_name(record, shared_number):
    """Name a body's folder. A few entries share a certificate number, so add the ID."""
    name = f"{record['BrojPotvrde']}_{slugify(record.get('AkreditornoTijelo') or 'body')}"
    return f"{name}_{record['ID'][:8]}" if shared_number else name


def save_body(record, out_dir, base_url, force, shared_number=False):
    """Save one body's files. Returns its summary, including any download error."""
    folder = out_dir / folder_name(record, shared_number)
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    text = record.get(TEXT_FIELD)
    if text:
        (folder / "document_text.txt").write_text(text, encoding="utf-8")

    summary = {k: v for k, v in record.items() if k != TEXT_FIELD}
    summary["folder"] = folder.name
    summary["pdf_error"] = None

    pdf_path = folder / "certificate.pdf"
    downloaded = False
    if force or not pdf_path.exists():
        try:
            pdf_path.write_bytes(fetch_pdf(base_url, record))
            downloaded = True
        except (OSError, RuntimeError) as exc:
            summary["pdf_error"] = str(exc)
    if pdf_path.exists():
        pdf = pdf_path.read_bytes()
        summary["pdf_bytes"] = len(pdf)
        summary["pdf_sha256"] = hashlib.sha256(pdf).hexdigest()
    return summary, downloaded


def write_summaries(summaries, out_dir):
    (out_dir / "bodies.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = list(CSV_FIELDS.values()) + ["folder", "pdf_bytes", "pdf_error"]
    # utf-8-sig so Excel displays Croatian characters correctly.
    with open(out_dir / "bodies.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for s in summaries:
            row = {column: s.get(field) for field, column in CSV_FIELDS.items()}
            row["expiry_date"] = clean_date(s.get("DatumIsteka"))
            row.update({k: s.get(k) for k in ("folder", "pdf_bytes", "pdf_error")})
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download data and certificates from the HAA accreditation register."
    )
    parser.add_argument("--out", type=Path, default=Path("haa_data"), help="output folder")
    parser.add_argument("--scheme", default=DEFAULT_SCHEME, help="regex matched against the scheme name")
    parser.add_argument("--all", action="store_true", help="download every scheme")
    parser.add_argument("--list-schemes", action="store_true", help="print schemes and exit")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--force", action="store_true", help="download PDFs again")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()
    records = fetch_register(args.base_url, args.delay)

    if args.list_schemes:
        counts = Counter(r.get("AkreditacijskaShema") or "(none)" for r in records)
        for scheme, count in sorted(counts.items()):
            print(f"{count:4}  {scheme}")
        return 0

    if not args.all:
        pattern = re.compile(args.scheme, re.IGNORECASE)
        records = [r for r in records if pattern.search(r.get("AkreditacijskaShema") or "")]
    if not records:
        print("No records match. Try --list-schemes.", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Saving {len(records)} bodies to {args.out}")
    summaries = []
    number_counts = Counter(r["BrojPotvrde"] for r in records)
    for i, record in enumerate(records, 1):
        print(f"[{i}/{len(records)}] {record['BrojPotvrde']} {record.get('AkreditornoTijelo')}")
        shared_number = number_counts[record["BrojPotvrde"]] > 1
        summary, downloaded = save_body(record, args.out, args.base_url, args.force, shared_number)
        if summary["pdf_error"]:
            print(f"  FAILED: {summary['pdf_error']}", file=sys.stderr)
        summaries.append(summary)
        if downloaded and i < len(records):
            time.sleep(args.delay)
    write_summaries(summaries, args.out)

    failed = [s for s in summaries if s["pdf_error"]]
    print(f"Done: {len(summaries) - len(failed)}/{len(summaries)} PDFs saved in {args.out}")
    for s in failed:
        print(f"  Missing: {s['BrojPotvrde']} {s.get('AkreditornoTijelo')}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
