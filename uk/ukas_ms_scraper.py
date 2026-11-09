#!/usr/bin/env python3
"""Collect UKAS Management Systems certification body data.

What it collects
  * Body details from the ukas.com category listings (parent category and all
    Management Systems sub-categories): accreditation number, name, address,
    phone, email, website, categories.
  * Each body's accreditation schedule PDF, plus its extracted text, tables,
    standards, issue details, annex headings and hyperlinks.
  * Participation status and country from CertCheck's public body list.

What it deliberately does not collect
  * Certificates issued to companies (CertCheck /certification/ and
    /certified-entity/, which CertCheck's robots.txt disallows).

Note: ukas.com's robots.txt disallows "/*cat=*", which covers the listing pages
this script reads. Keep the request rate low. On HTTP 401/403 the run stops
rather than trying to get around the block.

Usage
  pip install requests beautifulsoup4 pdfplumber
  python ukas_ms_scraper.py --max-bodies 3     # small trial first
  python ukas_ms_scraper.py                    # full run, safe to re-run

Output (default ./ukas_ms_data)
  bodies.json, bodies.csv     one record per certification body
  body_categories.csv         one row per body/category pair
  certcheck_bodies.csv        the full CertCheck list
  schedules/                  downloaded PDFs
  schedule_text/, schedule_tables/   extracted content
  raw_listings/               saved listing HTML, reused on re-runs
  run_summary.json            counts, warnings and failures
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PARENT_CATEGORY = "2567"
LISTING_PATH = "/find-an-organisation/browse-by-category/"
MAX_PDF_BYTES = 100 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}


class Blocked(Exception):
    """The site refused access; stop instead of working around it."""


class Client:
    def __init__(self, delay: float, contact: str | None):
        self.delay = delay
        self.last = 0.0
        self.session = requests.Session()
        agent = "ukas-ms-scraper/1.0 (python-requests)"
        if contact:
            agent += f" contact: {contact}"
        self.session.headers["User-Agent"] = agent

    def _wait(self) -> None:
        target = self.delay * (1 + random.random() * 0.3)
        remaining = target - (time.monotonic() - self.last)
        if remaining > 0:
            time.sleep(remaining)
        self.last = time.monotonic()

    def get(self, url: str, stream: bool = False) -> requests.Response:
        error = "no attempt made"
        for attempt in range(5):
            self._wait()
            try:
                r = self.session.get(url, timeout=60, stream=stream)
            except requests.RequestException as exc:
                error = str(exc)
                time.sleep(self.delay * 2 ** attempt)
                continue
            if r.status_code in (401, 403):
                raise Blocked(f"HTTP {r.status_code} for {url}")
            if r.status_code in RETRY_STATUSES:
                error = f"HTTP {r.status_code}"
                retry_after = r.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else self.delay * 2 ** (attempt + 1)
                r.close()
                time.sleep(min(wait, 300))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"{url}: gave up after retries ({error})")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def slugify(text: str, limit: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:limit] or "unnamed"


def parse_card(card, base_url: str) -> dict | None:
    title = card.select_one("h3 a")
    number = card.select_one("strong.meta span")
    if not title or not number:
        return None
    para = card.select_one(".content p") or card.select_one("p")
    text = clean(para.get_text(" ")) if para else ""
    address = clean(re.split(r"\b(?:Telephone|Email|Web)\b", text)[0]).rstrip(",")
    phone = re.search(r"\bTelephone\s+(.*?)(?=\s+(?:Email|Web)\b|$)", text)
    email = web = ""
    if para:
        for a in para.select("a[href]"):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                email = email or href[7:].split("?")[0]
            elif not web:
                web = href
    return {
        "accreditation_number": clean(number.get_text()),
        "name": clean(title.get_text()),
        "address": address,
        "telephone": clean(phone.group(1)) if phone else "",
        "email": email,
        "website": web,
        "schedule_url": urljoin(base_url, title.get("href", "")),
        "listing_post_id": card.get("id", ""),
        "listing_status_code": card.get("data-status", ""),
    }


def parse_listing(html: str, base_url: str) -> tuple[list[dict], int, dict[str, str]]:
    """Return the cards, highest page number linked, and category links."""
    soup = BeautifulSoup(html, "html.parser")
    cards = [c for c in (parse_card(x, base_url) for x in soup.select("div.listing div.signpost")) if c]
    last_page = 1
    categories: dict[str, str] = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        match = re.search(r"/page/(\d+)/", href)
        if match and "cat=" in href:
            last_page = max(last_page, int(match.group(1)))
        cat = re.search(r"[?&]cat=(\d+)", href)
        name = clean(a.get_text())
        if cat and not match and name and not name.isdigit() and name.lower() not in ("next", "prev", "previous"):
            categories[cat.group(1)] = name
    return cards, last_page, categories


def fetch_listing_page(client, base, out, cat, page, refresh) -> str:
    path = out / "raw_listings" / f"cat{cat}_page{page}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    prefix = f"{LISTING_PATH}page/{page}/" if page > 1 else LISTING_PATH
    html = client.get(f"{base}{prefix}?cat={cat}").text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def crawl_category(client, base, out, cat, refresh) -> tuple[list[dict], dict[str, str]]:
    cards: list[dict] = []
    seen: set[str] = set()
    categories: dict[str, str] = {}
    page, last = 1, 1
    while page <= last:
        html = fetch_listing_page(client, base, out, cat, page, refresh)
        page_cards, linked_last, page_categories = parse_listing(html, base)
        categories.update(page_categories)
        last = max(last, linked_last)
        new = [c for c in page_cards if c["accreditation_number"] not in seen]
        if not new:
            break
        seen.update(c["accreditation_number"] for c in new)
        cards.extend(new)
        page += 1
    return cards, categories


def crawl_listings(client, base, out, refresh, warnings) -> dict[str, dict]:
    print("Reading the parent Management Systems category...")
    parent_cards, categories = crawl_category(client, base, out, PARENT_CATEGORY, refresh)
    bodies: dict[str, dict] = {}
    for card in parent_cards:
        bodies[card["accreditation_number"]] = {**card, "categories": []}
    subcats = {k: v for k, v in categories.items() if k != PARENT_CATEGORY}
    if not parent_cards:
        warnings.append("Parent listing returned no bodies; the page layout may have changed.")
    if not subcats:
        warnings.append("No sub-categories found; body categories will be empty.")
    for i, (cat, name) in enumerate(sorted(subcats.items(), key=lambda x: x[1]), 1):
        print(f"  [{i}/{len(subcats)}] {name}")
        cards, _ = crawl_category(client, base, out, cat, refresh)
        if not cards:
            warnings.append(f"Sub-category returned no bodies: {name} ({cat})")
        for card in cards:
            number = card["accreditation_number"]
            if number not in bodies:
                bodies[number] = {**card, "categories": []}
                warnings.append(f"Body {number} is in {name} but not in the parent listing.")
            bodies[number]["categories"].append(name)
    return bodies


def download_schedule(client, base, out, body, refresh) -> dict:
    url = body["schedule_url"]
    if urlparse(url).netloc != urlparse(base).netloc:
        raise RuntimeError(f"Unexpected schedule host: {url}")
    number = slugify(body["accreditation_number"], 20)
    path = out / "schedules" / f"{number}_{slugify(body['name'])}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta: dict = {}
    if refresh or not path.exists():
        temp = path.with_suffix(".part")
        size = 0
        with client.get(url, stream=True) as r, temp.open("wb") as f:
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise RuntimeError(f"{url}: larger than {MAX_PDF_BYTES} bytes")
                f.write(chunk)
            meta["schedule_last_modified"] = r.headers.get("Last-Modified", "")
        with temp.open("rb") as f:
            if f.read(5) != b"%PDF-":
                temp.unlink()
                raise RuntimeError(f"{url}: response is not a PDF")
        temp.replace(path)
    data = path.read_bytes()
    meta.update(
        schedule_file=str(path.relative_to(out)),
        schedule_bytes=len(data),
        schedule_sha256=hashlib.sha256(data).hexdigest(),
    )
    return meta


def parse_schedule(pdf_path: Path, out: Path, stem: str) -> dict:
    import pdfplumber

    pages, tables, links = [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            pages.append(page.extract_text() or "")
            for table in page.extract_tables():
                tables.append({"page": number, "rows": table})
            for link in page.hyperlinks or []:
                uri = link.get("uri")
                if uri and uri not in links:
                    links.append(uri)
    text = "\n".join(pages)
    (out / "schedule_text").mkdir(exist_ok=True)
    (out / "schedule_tables").mkdir(exist_ok=True)
    (out / "schedule_text" / f"{stem}.txt").write_text(
        "\n\n".join(f"--- page {i} ---\n{p}" for i, p in enumerate(pages, 1)), encoding="utf-8"
    )
    (out / "schedule_tables" / f"{stem}.json").write_text(
        json.dumps(tables, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    accredited = re.search(r"Accredited to\s+((?:BS\s+|EN\s+)*ISO(?:/IEC)?\s*[\d-]+(?::\d{4})?)", text, re.I)
    issue_no = re.search(r"Issue\s*(?:No\.?|Number)\s*:?\s*(\d+)", text, re.I)
    issue_date = re.search(r"Issue\s*date\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, re.I)
    standards = sorted({clean(s) for s in re.findall(r"\bISO(?:/IEC|/TS)?\s*\d{4,5}(?:-\d+)?(?::\d{4})?", text)})
    annexes = list(dict.fromkeys(
        clean(line) for line in text.splitlines()
        if re.match(r"\s*(Annex|Appendix)\b\s*[\w.-]*", line, re.I) and len(line) < 150
    ))
    return {
        "schedule_pages": len(pages),
        "schedule_tables": len(tables),
        "schedule_empty_text": not text.strip(),
        "accredited_to": clean(accredited.group(1)) if accredited else "",
        "schedule_issue_no": issue_no.group(1) if issue_no else "",
        "schedule_issue_date": clean(issue_date.group(1)) if issue_date else "",
        "standards_mentioned": standards,
        "annex_headings": annexes,
        "schedule_links": links,
    }


def fetch_certcheck(client, api_base) -> list[dict]:
    rows, seen, page, total_pages = [], set(), 0, 1
    while page < total_pages:
        url = f"{api_base}/api/v1/g/cb?limit=20&offset={page}"
        payload = client.get(url).json()
        total_pages = int(payload.get("meta", {}).get("total_pages") or 1)
        for row in payload.get("data", []):
            if row.get("certification_bodies_id") not in seen:
                seen.add(row.get("certification_bodies_id"))
                rows.append(row)
        page += 1
    return rows


def normalise_name(name: str) -> str:
    name = re.split(r"\bt/a\b|\btrading as\b|\bdba\b", name.lower())[0]
    name = re.sub(r"\(.*?\)", " ", name).replace("limited", "ltd")
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def attach_certcheck(bodies: dict[str, dict], certcheck: list[dict]) -> None:
    index = {normalise_name(r.get("certification_bodies_name", "")): r for r in certcheck}
    keys = list(index)
    for body in bodies.values():
        key = normalise_name(body["name"])
        method = "exact" if key in index else ""
        if not method:
            close = difflib.get_close_matches(key, keys, n=1, cutoff=0.92)
            if close:
                key, method = close[0], "fuzzy"
        row = index.get(key) if method else None
        body.update(
            certcheck_match=method or "none",
            certcheck_name=(row or {}).get("certification_bodies_name", ""),
            certcheck_status=(row or {}).get("participation_status", ""),
            certcheck_country=(row or {}).get("country_name", ""),
        )


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                c: " | ".join(row[c]) if isinstance(row.get(c), list) else row.get(c, "")
                for c in columns
            })


BODY_COLUMNS = [
    "accreditation_number", "name", "address", "telephone", "email", "website", "categories",
    "certcheck_match", "certcheck_name", "certcheck_status", "certcheck_country",
    "schedule_url", "schedule_file", "schedule_bytes", "schedule_sha256", "schedule_last_modified",
    "schedule_pages", "schedule_tables", "schedule_empty_text", "accredited_to", "schedule_issue_no",
    "schedule_issue_date", "standards_mentioned", "annex_headings", "schedule_links", "error",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect UKAS Management Systems certification body data.")
    parser.add_argument("--out", type=Path, default=Path("ukas_ms_data"))
    parser.add_argument("--delay", type=float, default=3.0, help="seconds between requests (minimum 1)")
    parser.add_argument("--max-bodies", type=int, help="only download this many schedules (for a trial)")
    parser.add_argument("--refresh", action="store_true", help="fetch again instead of reusing saved files")
    parser.add_argument("--skip-certcheck", action="store_true")
    parser.add_argument("--no-parse", action="store_true", help="download PDFs without extracting content")
    parser.add_argument("--contact", help="contact detail to include in the User-Agent")
    parser.add_argument("--base-url", default="https://www.ukas.com", help=argparse.SUPPRESS)
    parser.add_argument("--api-url", default="https://api.certcheck.ukas.com", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.delay < 1:
        parser.error("--delay must be at least 1 second")
    if not args.no_parse:
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            parser.error("pdfplumber is not installed; install it or use --no-parse")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    client = Client(args.delay, args.contact)
    warnings: list[str] = []
    failures: list[dict] = []
    bodies: dict[str, dict] = {}
    certcheck: list[dict] = []
    stopped = ""

    def save() -> None:
        ordered = sorted(bodies.values(), key=lambda b: b["accreditation_number"])
        (out / "bodies.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
        write_csv(out / "bodies.csv", ordered, BODY_COLUMNS)
        write_csv(
            out / "body_categories.csv",
            [{"accreditation_number": b["accreditation_number"], "name": b["name"], "category": c}
             for b in ordered for c in b["categories"]],
            ["accreditation_number", "name", "category"],
        )
        (out / "run_summary.json").write_text(json.dumps({
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "stopped_early": stopped,
            "bodies": len(bodies),
            "schedules_saved": sum(1 for b in bodies.values() if b.get("schedule_file")),
            "schedules_without_text": [
                b["accreditation_number"] for b in ordered if b.get("schedule_empty_text")],
            "certcheck_rows": len(certcheck),
            "certcheck_match_counts": {
                m: sum(1 for b in ordered if b.get("certcheck_match") == m)
                for m in ("exact", "fuzzy", "none")},
            "warnings": warnings,
            "failures": failures,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        bodies = crawl_listings(client, base, out, args.refresh, warnings)
        print(f"Found {len(bodies)} bodies.")

        if not args.skip_certcheck:
            print("Reading the CertCheck body list...")
            try:
                certcheck = fetch_certcheck(client, args.api_url.rstrip("/"))
                (out / "certcheck_bodies.json").write_text(
                    json.dumps(certcheck, ensure_ascii=False, indent=1), encoding="utf-8")
                write_csv(out / "certcheck_bodies.csv", certcheck, [
                    "certification_bodies_id", "certification_bodies_name", "certification_bodies_acronym",
                    "participation_status", "country_name", "country_code"])
                attach_certcheck(bodies, certcheck)
            except (RuntimeError, ValueError, requests.RequestException) as exc:
                warnings.append(f"CertCheck list not collected: {exc}")

        selected = sorted(bodies.values(), key=lambda b: b["accreditation_number"])[:args.max_bodies]
        for i, body in enumerate(selected, 1):
            print(f"  [{i}/{len(selected)}] {body['accreditation_number']} {body['name']}")
            try:
                body.update(download_schedule(client, base, out, body, args.refresh))
                if not args.no_parse:
                    pdf_path = out / body["schedule_file"]
                    body.update(parse_schedule(pdf_path, out, pdf_path.stem))
            except Blocked:
                raise
            except Exception as exc:  # one bad document should not end the run
                body["error"] = str(exc)
                failures.append({"accreditation_number": body["accreditation_number"], "error": str(exc)})
            save()
    except Blocked as exc:
        stopped = f"{exc}. The site refused access, so the run stopped. Contact UKAS about access."
        print(f"STOPPED: {stopped}", file=sys.stderr)

    save()
    print(f"\nBodies: {len(bodies)} | Failures: {len(failures)} | Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  warning: {warning}")
    print(f"Output: {out.resolve()}")
    return 1 if stopped or failures else 0


if __name__ == "__main__":
    sys.exit(main())
