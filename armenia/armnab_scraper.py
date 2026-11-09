#!/usr/bin/env python3
"""Scrape ARMNAB's register of accredited management-system certification bodies.

Site: https://armnab.am/management-systems (Blazor Server, Armenian only).

The list page is server-rendered but only holds the first 15 rows; further pages
need a SignalR connection. Detail pages are plain HTML with sequential IDs, so the
scraper reads the list, then walks MS00000001 upward and checks the total against
the count printed on the list page.

Only this register is read. ISO/IEC 17025, 17020, 17065 and 17024 bodies live on
separate registers (/laboratories, /tech-control-bodies, /certification-bodies,
/physical-persons), so they never enter the output.

The site publishes no annex or certificate files today. The scope is text on the
detail page. --download-docs saves each detail page and any linked file, so
certificates are picked up automatically if ARMNAB ever adds them.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://armnab.am"
LIST_PATH = "/management-systems"
USER_AGENT = "CertiFindBot/1.0 (accreditation register research; python-requests)"
DELAY_SECONDS = 0.3
TIMEOUT_SECONDS = 30
RETRIES = 2
STOP_AFTER_MISSES = 5
DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx")
NOT_FOUND_TEXT = "Չի գտնվել"
CERT_NUMBER_RE = re.compile(r"\d{3}/[A-Z]-\d{3}")
TOTAL_RE = re.compile(r"Գտնվել է\s+(\d+)")

BODY_FIELDS = ["body_key", "name", "latest_status", "head", "phone", "fax", "email",
               "legal_address", "activity_address", "source_url", "record_count"]
ACCREDITATION_FIELDS = ["detail_id", "certificate_number", "body_name", "status",
                        "start_date", "end_date", "decision_number", "decision_date",
                        "form_number", "source_url"]

LABELS = {
    "registration": "Հավատարմագրման վկայագրի գրանցման համարը",
    "start": "Գործողության ժամկետը սկսած",
    "end": "Մինչև ներառյալ",
    "decision_number": "Որոշման համարը",
    "decision_date": "Որոշման ամսաթիվը",
    "form_number": "Ձևաթղթի համարը",
    "full_name": "Անվանումը (լրիվ)",
    "head": "Ղեկավար",
    "phone": "Հեռախոս",
    "fax": "Ֆաքս",
    "email": "Էլ․ հասցե",
    "legal_address": "Իրավաբանական անձի գտնվելու վայր",
    "activity_address": "Գործունեության իրականացման վայր",
}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def iso_date(value: str) -> str:
    """DD/MM/YYYY to YYYY-MM-DD; unknown formats come back unchanged."""
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", clean(value))
    return f"{match[3]}-{match[2]}-{match[1]}" if match else clean(value)


def blank_dash(value: str) -> str:
    return "" if clean(value) in {"", "-", "—"} else clean(value)


def body_key(name: str) -> str:
    """Identity of a body across records: the upper-cased text inside «»."""
    match = re.search(r"«([^»]+)»", name)
    return clean(match[1] if match else name).upper()


def parse_list(html: str) -> tuple[int | None, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    total = TOTAL_RE.search(soup.get_text(" "))
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = tr.find_all("td")
        link = tr.select_one('a[href*="/management-systems/MS"]')
        if len(cells) < 6 or link is None:
            continue
        rows.append({
            "detail_id": link["href"].rstrip("/").rsplit("/", 1)[-1],
            "status": clean(cells[0].get_text()),
            "registration": clean(cells[1].get_text()),
            "name": clean(cells[4].get_text()),
        })
    return (int(total[1]) if total else None), rows


def parse_detail(html: str, detail_id: str, url: str) -> dict | None:
    """Return the record, or None for the site's "not found" page (HTTP 200)."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".detail__title")
    if title is None:
        main = soup.select_one("main") or soup
        if NOT_FOUND_TEXT in main.get_text():
            return None
        raise ValueError("page has neither a detail title nor the not-found text")

    blocks = []
    for block in soup.select(".detail-block"):
        heading = block.select_one(".detail-block__title")
        entries, label = [], ""
        for element in block.find_all(["dt", "dd"]):
            if element.name == "dt":
                label = clean(element.get_text())
                continue
            lines = [clean(line) for line in element.get_text("\n").splitlines()]
            entries.append({"label": label, "lines": [line for line in lines if line]})
        blocks.append({"title": clean(heading.get_text()) if heading else "", "entries": entries})

    fields = {entry["label"]: " ".join(entry["lines"])
              for block in blocks for entry in block["entries"] if len(entry["lines"]) <= 3}
    get = lambda key: blank_dash(fields.get(LABELS[key], ""))
    registration = get("registration")
    badge = soup.select_one(".detail__head .badge") or soup.select_one(".badge")
    documents = []
    for link in (soup.select_one("main") or soup).select("a[href]"):
        href = urljoin(url, link["href"])
        if urlparse(href).path.lower().endswith(DOC_EXTENSIONS):
            documents.append(href)
    return {
        "detail_id": detail_id,
        "source_url": url,
        "status": clean(badge.get_text()) if badge else "",
        "name": clean(title.get_text()),
        "registration": registration,
        "certificate_numbers": CERT_NUMBER_RE.findall(registration),
        "start_date": iso_date(get("start")),
        "end_date": iso_date(get("end")),
        "decision_number": get("decision_number"),
        "decision_date": iso_date(get("decision_date")),
        "form_number": get("form_number"),
        "head": get("head"),
        "phone": get("phone"),
        "fax": get("fax"),
        "email": get("email"),
        "legal_address": get("legal_address"),
        "activity_address": get("activity_address"),
        "documents": sorted(set(documents)),
        "blocks": blocks,
    }


class Scraper:
    def __init__(self, base_url: str, output: Path, delay: float, download_docs: bool):
        self.base_url = base_url.rstrip("/")
        self.output = output
        self.delay = delay
        self.download_docs = download_docs
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.errors: list[dict] = []
        self.failed_urls: list[str] = []
        self.counts = {"requests": 0, "documents_downloaded": 0, "documents_already_present": 0,
                       "pages_saved": 0, "pages_already_saved": 0, "ids_not_found": 0}

    def error(self, url: str, message: str) -> None:
        self.errors.append({"url": url, "error": message})
        if url and url not in self.failed_urls:
            self.failed_urls.append(url)
        print(f"ERROR {url}: {message}", file=sys.stderr)

    def get(self, url: str) -> requests.Response | None:
        last_error = ""
        for attempt in range(RETRIES + 1):
            time.sleep(self.delay)
            self.counts["requests"] += 1
            try:
                response = self.session.get(url, timeout=TIMEOUT_SECONDS)
                if response.status_code == 200:
                    return response
                last_error = f"HTTP {response.status_code}"
                if response.status_code < 500:
                    break
            except requests.RequestException as exc:
                last_error = str(exc)
        self.error(url, last_error)
        return None

    def save_documents(self, record: dict, html: str) -> None:
        folder = self.output / "scope_documents"
        folder.mkdir(parents=True, exist_ok=True)
        page = folder / f"{record['detail_id']}.html"
        if page.exists() and page.stat().st_size:
            self.counts["pages_already_saved"] += 1
        else:
            page.write_text(html, encoding="utf-8")
            self.counts["pages_saved"] += 1
        for url in record["documents"]:
            target = folder / f"{record['detail_id']}__{Path(urlparse(url).path).name}"
            if target.exists() and target.stat().st_size:
                self.counts["documents_already_present"] += 1
                continue
            response = self.get(url)
            if response is None:
                continue
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(response.content)
            partial.replace(target)
            self.counts["documents_downloaded"] += 1

    def fetch_record(self, detail_id: str) -> tuple[dict | None, bool]:
        """Return (record, fetched_ok); a not-found page is (None, True)."""
        url = f"{self.base_url}{LIST_PATH}/{detail_id}"
        response = self.get(url)
        if response is None:
            return None, False
        try:
            response.encoding = "utf-8"
            record = parse_detail(response.text, detail_id, url)
        except (ValueError, AttributeError, KeyError) as exc:
            self.error(url, f"parse failed: {exc}")
            return None, False
        if record is None:
            self.counts["ids_not_found"] += 1
            return None, True
        if not record["certificate_numbers"]:
            self.error(url, f"no certificate number in {record['registration']!r}")
        if self.download_docs:
            self.save_documents(record, response.text)
        return record, True

    def run(self) -> list[dict]:
        list_url = self.base_url + LIST_PATH
        stated_total, listed = None, []
        response = self.get(list_url)
        if response is not None:
            response.encoding = "utf-8"
            stated_total, listed = parse_list(response.text)
        self.stated_total = stated_total
        self.listed_rows = len(listed)

        highest = max((int(row["detail_id"][2:]) for row in listed), default=0)
        records, misses, number = [], 0, 0
        while number < highest or misses < STOP_AFTER_MISSES:
            number += 1
            record, ok = self.fetch_record(f"MS{number:08d}")
            if record is not None:
                records.append(record)
                misses = 0
            elif ok:
                misses += 1
        found = {record["detail_id"] for record in records}
        for row in listed:
            if row["detail_id"] not in found:
                self.error(f"{list_url}/{row['detail_id']}", "listed but not scraped")
        if stated_total is not None and stated_total != len(records):
            self.error(list_url, f"list page says {stated_total} records, scraped {len(records)}")
        return records


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def group_bodies(records: list[dict]) -> list[dict]:
    """One row per body, using contact details from its newest record."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(body_key(record["name"]), []).append(record)
    bodies = []
    for key, group in grouped.items():
        latest = max(group, key=lambda record: record["start_date"])
        bodies.append({
            "body_key": key, "name": latest["name"], "latest_status": latest["status"],
            "head": latest["head"], "phone": latest["phone"], "fax": latest["fax"],
            "email": latest["email"], "legal_address": latest["legal_address"],
            "activity_address": latest["activity_address"], "source_url": latest["source_url"],
            "record_count": len(group),
            "records": sorted((record["detail_id"] for record in group)),
        })
    return bodies


def accreditation_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        for number in record["certificate_numbers"] or [""]:
            rows.append({**record, "certificate_number": number, "body_name": record["name"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--delay", type=float, default=DELAY_SECONDS)
    parser.add_argument("--download-docs", action="store_true",
                        help="save detail pages and any linked files to output/scope_documents/")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    scraper = Scraper(args.base_url, args.output, args.delay, args.download_docs)
    records = scraper.run()
    bodies = group_bodies(records)
    rows = accreditation_rows(records)

    write_csv(args.output / "bodies.csv", BODY_FIELDS, bodies)
    write_csv(args.output / "accreditations.csv", ACCREDITATION_FIELDS, rows)
    (args.output / "bodies.json").write_text(
        json.dumps({"bodies": bodies, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    report = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "stated_total_on_list": scraper.stated_total,
        "listed_rows_on_first_page": scraper.listed_rows,
        "records": len(records),
        "bodies": len(bodies),
        "accreditation_rows": len(rows),
        "documents_linked_on_site": sum(len(record["documents"]) for record in records),
        **scraper.counts,
        "error_count": len(scraper.errors),
        "errors": scraper.errors,
        "failed_urls": scraper.failed_urls,
    }
    (args.output / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(records)} records, {len(bodies)} bodies, {len(scraper.errors)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
