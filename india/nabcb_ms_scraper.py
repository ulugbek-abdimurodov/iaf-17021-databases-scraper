#!/usr/bin/env python3
"""Scrape NABCB's public directory of Management System Certification Bodies.

Setup:   pip install requests beautifulsoup4 lxml openpyxl
Run:     python nabcb_ms_scraper.py --out nabcb_output

Collects
  * every accreditation in the 19 scheme tabs (EMS, QMS, ISMS, FSMS, ...)
  * each accreditation's detail page: address, contacts, validity, standards, scopes
  * withdrawn, expired and suspended management system accreditations
  * any certificate, annex or other file linked or embedded in a detail page
  * documents from the site's public media library (certificates, annexes,
    schedules, criteria, forms), sorted by a filename-based category

Output (in --out)
  nabcb_ms_bodies.xlsx          all tables below, one sheet each
  accreditations.csv            one row per accreditation
  bodies.csv                    one row per certification body
  scope_rows.csv                every scope table row
  withdrawn_suspended.csv       status-page rows
  documents_manifest.csv        every document found, with its download status
  all_data.json                 everything, including the parsed scope structure
  html/                         the original detail pages
  documents/                    downloaded files
  run_report.txt                counts and failures

Re-running resumes: saved pages and files are reused unless --refresh is given.
Exit code is 1 if anything failed; run_report.txt lists what.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://nabcb.qci.org.in"
LISTING_PATH = "/management-system-certification/"
WITHDRAWN_PATH = "/accreditations-withdrawn/"
SUSPENDED_PATH = "/suspended-bodies/"
MEDIA_PATH = "/wp-json/wp/v2/media"

USER_AGENT = "Mozilla/5.0 (compatible; nabcb-directory-scraper/1.0)"
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
SITE_CHROME_IMAGES = re.compile(r"trans\.gif|nabcb-footer|logo|emoji", re.I)
# The withdrawn page also has tables for these non-management-system bodies.
NON_MS_HEADING = re.compile(r"product certification|certification of persons|personnel|"
                            r"inspection bod|validation|verification", re.I)
CERT_NO = re.compile(r"^[A-Z]{2,5}\s*[-]?\s*\d{1,4}[A-Z]?$")

LABELS = {
    "address": "address",
    "contactperson": "contact_person",
    "designation": "designation",
    "tel": "tel", "telephone": "tel", "phone": "tel",
    "fax": "fax",
    "mobile": "mobile", "mobileno": "mobile", "mob": "mobile",
    "email": "email", "emailid": "email",
    "website": "website", "web": "website",
    "validfrom": "valid_from",
    "validupto": "valid_upto", "validtill": "valid_upto",
    "accreditationstandard": "accreditation_standards",
    "accreditationstandards": "accreditation_standards",
}
FIELDS = ["address", "contact_person", "designation", "tel", "mobile", "fax", "email",
          "website", "valid_from", "valid_upto", "accreditation_standards"]


def clean(text: str | None) -> str:
    text = (text or "").replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def cell_text(cell: Tag) -> str:
    return clean(cell.get_text(" "))


def normalise_url(base: str, href: str) -> str:
    """Absolute URL with duplicate slashes removed (the site links to //ems/em002/)."""
    href = href.strip()
    if re.match(r"//[^/.]+(/|$)", href):  # a path with a doubled slash, not a hostname
        href = href[1:]
    parts = urlsplit(urljoin(base + "/", href))
    return urlunsplit((parts.scheme, parts.netloc, re.sub(r"/{2,}", "/", parts.path), parts.query, ""))


def normalise_cert(text: str) -> str:
    return re.sub(r"[\s-]+", "", text).upper()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "file"


def body_key(name: str) -> str:
    """Key that treats 'Tuv India Pvt Ltd.' and 'TUV India Pvt. Ltd' as one body."""
    name = re.sub(r"\(.*?\)", " ", name).lower()
    name = re.sub(r"\b(pvt|private|ltd|limited|llp|llc|co|inc|the)\b", " ", name)
    return re.sub(r"[^a-z0-9]+", "", name)


# ---------------------------------------------------------------- HTTP

class Fetcher:
    def __init__(self, delay: float, timeout: int = 60, retries: int = 4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self._last = 0.0

    def get(self, url: str, **kwargs) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                    return resp
                last_error = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            except requests.HTTPError:
                raise  # other 4xx: retrying will not help
            except requests.RequestException as exc:
                last_error = exc
            if attempt < self.retries - 1:
                time.sleep(min(2 ** attempt * 2, 30))
        assert last_error is not None
        raise last_error

    def page(self, url: str) -> str:
        resp = self.get(url)
        resp.encoding = "utf-8"
        return resp.text

    def download(self, url: str, dest: Path, refresh: bool = False) -> tuple[str, int]:
        if dest.exists() and dest.stat().st_size > 0 and not refresh:
            return "already_present", dest.stat().st_size
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        with self.get(url, stream=True) as resp, part.open("wb") as fh:
            for chunk in resp.iter_content(1 << 16):
                fh.write(chunk)
        part.replace(dest)
        return "downloaded", dest.stat().st_size


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------- list pages

def table_rows(table: Tag) -> list[Tag]:
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


def preceding_heading(table: Tag) -> str:
    node: Tag | None = table
    while node is not None:
        for sib in node.find_previous_siblings():
            text = clean(sib.get_text(" "))
            if text:
                return text
        node = node.parent if isinstance(node.parent, Tag) else None
    return ""


def header_index(rows: list[Tag], pattern: str) -> int | None:
    for i, tr in enumerate(rows):
        if re.search(pattern, cell_text(tr), re.I):
            return i
    return None


def column(headers: list[str], *patterns: str) -> int | None:
    for pat in patterns:
        for i, head in enumerate(headers):
            if re.search(pat, head, re.I):
                return i
    return None


def parse_listing(html: str, base: str) -> list[dict]:
    records = []
    for table in soup_of(html).find_all("table"):
        rows = table_rows(table)
        head_at = header_index(rows, r"Certificate\s*No")
        if head_at is None:
            continue
        scheme = cell_text(rows[head_at - 1]) if head_at else preceding_heading(table)
        headers = [cell_text(c) for c in rows[head_at].find_all(["td", "th"], recursive=False)]
        col_cert = column(headers, r"Certificate\s*No")
        col_name = column(headers, r"Name")
        col_from = column(headers, r"Initial|Issue")
        col_to = column(headers, r"Valid")
        for tr in rows[head_at + 1:]:
            cells = tr.find_all(["td", "th"], recursive=False)
            texts = [cell_text(c) for c in cells]
            if col_cert is None or len(texts) <= col_cert or not texts[col_cert]:
                continue
            link = tr.find("a", href=True)
            get = lambda i: texts[i] if i is not None and i < len(texts) else ""
            records.append({
                "scheme": scheme,
                "certificate_no": normalise_cert(texts[col_cert]),
                "certificate_no_as_listed": texts[col_cert],
                "name": get(col_name),
                "initial_issue_date": get(col_from),
                "listing_valid_upto": get(col_to),
                "detail_url": normalise_url(base, link["href"]) if link else "",
                "status": "Active",
                "status_comments": "",
            })
    return records


def parse_withdrawn(html: str, base: str) -> tuple[list[dict], list[str]]:
    """Returns management system rows, plus the table headings that were skipped."""
    rows_out, skipped = [], []
    for table in soup_of(html).find_all("table"):
        rows = table_rows(table)
        head_at = header_index(rows, r"Name of the")
        if head_at is None:
            continue
        heading = preceding_heading(table)
        if NON_MS_HEADING.search(heading):
            skipped.append(heading)
            continue
        headers = [cell_text(c) for c in rows[head_at].find_all(["td", "th"], recursive=False)]
        col = {k: column(headers, p) for k, p in dict(
            name=r"Name", status=r"Status", valid=r"Valid", comments=r"Comment").items()}
        for tr in rows[head_at + 1:]:
            texts = [cell_text(c) for c in tr.find_all(["td", "th"], recursive=False)]
            get = lambda k: texts[col[k]] if col[k] is not None and col[k] < len(texts) else ""
            if not get("name"):
                continue
            link = tr.find("a", href=True)
            rows_out.append({
                "scheme": heading, "name": get("name"), "status": get("status") or "Withdrawn",
                "listing_valid_upto": get("valid"), "status_comments": get("comments"),
                "certificate_no": "", "source": "accreditations-withdrawn",
                "detail_url": normalise_url(base, link["href"]) if link else "",
            })
    return rows_out, skipped


def parse_suspended(html: str, base: str, ms_prefixes: set[str]) -> list[dict]:
    """The page mixes all body types, so keep certificate prefixes seen in the MS tables."""
    out = []
    for table in soup_of(html).find_all("table"):
        rows = table_rows(table)
        head_at = header_index(rows, r"Certificate\s*No")
        if head_at is None:
            continue
        headers = [cell_text(c) for c in rows[head_at].find_all(["td", "th"], recursive=False)]
        col_cert, col_name = column(headers, r"Certificate\s*No"), column(headers, r"Name")
        for tr in rows[head_at + 1:]:
            texts = [cell_text(c) for c in tr.find_all(["td", "th"], recursive=False)]
            if col_cert is None or col_cert >= len(texts) or not texts[col_cert]:
                continue
            cert = normalise_cert(texts[col_cert])
            if re.sub(r"\d.*$", "", cert) not in ms_prefixes:
                continue
            link = tr.find("a", href=True)
            extra = {h: t for i, (h, t) in enumerate(zip(headers, texts))
                     if i not in (col_cert, col_name) and h}
            out.append({
                "scheme": "", "certificate_no": cert, "status": "Suspended",
                "name": texts[col_name] if col_name is not None and col_name < len(texts) else "",
                "listing_valid_upto": "", "source": "suspended-bodies",
                "status_comments": "; ".join(f"{k}: {v}" for k, v in extra.items() if v),
                "detail_url": normalise_url(base, link["href"]) if link else "",
            })
    return out


# ---------------------------------------------------------------- detail page

def leaf_rows(soup: BeautifulSoup) -> list[list[str]]:
    """Rows containing no nested table, in document order, with rowspans filled in.

    Detail pages stack tables several levels deep, and real data rows sit at varying depths.
    """
    pending: dict[int, dict[int, list]] = {}  # table id -> column -> [rows left, text]
    out = []
    for tr in soup.find_all("tr"):
        if tr.find("table"):
            continue
        spans = pending.setdefault(id(tr.find_parent("table")), {})
        row: list[str] = []
        col = 0
        cells = tr.find_all(["td", "th"], recursive=False)
        idx = 0
        while idx < len(cells) or col in spans:
            if col in spans:
                left, text = spans[col]
                row.append(text)
                if left <= 1:
                    del spans[col]
                else:
                    spans[col][0] = left - 1
                col += 1
                continue
            cell = cells[idx]
            idx += 1
            text = cell_text(cell)
            rowspan = _span(cell, "rowspan")
            for offset in range(_span(cell, "colspan")):
                row.append(text if offset == 0 else "")
                if rowspan > 1:
                    spans[col] = [rowspan - 1, text if offset == 0 else ""]
                col += 1
        out.append(row)
    return out


def _span(cell: Tag, attr: str) -> int:
    try:
        return max(1, int(cell.get(attr, 1)))
    except (TypeError, ValueError):
        return 1


def parse_detail(html: str, page_url: str) -> dict:
    soup = soup_of(html)
    title = clean(soup.title.get_text()) if soup.title else ""
    for tag in soup(["script", "style", "header", "footer", "nav", "noscript"]):
        tag.decompose()

    result = {f: "" for f in FIELDS}
    result.update(certificate_no="", page_title=title, page_name="", page_scheme="", scope_heading="",
                  iaf_scope_codes="", other_fields={}, scope_rows=[], linked_files=[])

    for td in soup.find_all("td"):
        if not td.find("table") and CERT_NO.match(cell_text(td)):
            result["certificate_no"] = normalise_cert(cell_text(td))
            sibling = td.find_next_sibling("td")
            if sibling:
                result["page_name"] = cell_text(sibling)
            break
    if not result["certificate_no"]:
        match = re.match(r"([A-Z]{2,5}\s*-?\s*\d{1,4}[A-Z]?)\b", title)
        if match:
            result["certificate_no"] = normalise_cert(match.group(1))

    values: dict[str, list[str]] = {}
    last_key, seen_valid, in_scope, section, header = None, False, False, "", []
    codes: list[str] = []
    for raw in leaf_rows(soup):
        vals = [v for v in raw if v]
        if not vals or " ".join(vals) in ("Print", "Close", "Print Close"):
            continue
        joined = " ".join(vals)
        match = re.search(r"scopes? of accreditation\s*(.*)", joined, re.I)
        if match:
            in_scope = True
            section = match.group(1) or section
            result["scope_heading"] = result["scope_heading"] or joined
            continue

        key = re.sub(r"\d+$", "", re.sub(r"[^a-z0-9]", "", vals[0].lower()))
        field_name = LABELS.get(key)
        if not in_scope and field_name and len(vals) >= 1:
            value = " ".join(vals[1:])
            if value:
                values.setdefault(field_name, []).append(value)
            last_key = field_name
            seen_valid = seen_valid or field_name == "valid_upto"
            continue
        if not in_scope and not raw[0] and last_key:  # continuation under a blank label
            values[last_key].append(joined)
            continue
        if not in_scope and not seen_valid:
            if len(vals) == 1:
                if not result["page_scheme"]:
                    result["page_scheme"] = vals[0]
                elif not result["page_name"] and not CERT_NO.match(vals[0]):
                    result["page_name"] = vals[0]
            else:
                result["other_fields"][vals[0]] = " ".join(vals[1:])
            continue

        # Everything after validity details is scope content, heading or not:
        # some pages have no "Scopes of accreditation" title.
        in_scope = True
        if len(vals) == 1:
            # ISMS and QMS pages list scope as plain lines, FSMS pages use these as sub-headings.
            section = vals[0]
            header = []
            result["scope_rows"].append({"section": section, "row_type": "text", "cells": vals})
            continue
        is_header = bool(re.match(
            r"(iaf\s*scope|scope|s[il]\.?\s*n[o0]|cluster|category|standard|title|description)",
            vals[0], re.I)) and not any(re.fullmatch(r"\d+", v) for v in vals)
        if is_header:
            header = vals
        elif header and re.search(r"iaf", header[0], re.I) and re.fullmatch(r"\d{1,2}[a-z]?", vals[0], re.I):
            codes.append(vals[0])
        result["scope_rows"].append(
            {"section": section, "row_type": "header" if is_header else "data", "cells": vals})

    for name, items in values.items():
        result[name] = "; ".join(dict.fromkeys(items))
    result["iaf_scope_codes"] = ", ".join(dict.fromkeys(codes))
    if not result["scope_heading"]:
        node = soup.find(string=re.compile(r"scopes? of accreditation", re.I))
        result["scope_heading"] = clean(str(node)) if node else ""

    result["linked_files"] = find_files(soup, page_url)
    return result


def find_files(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Certificates or annexes attached to a page: links, embeds, and non-template images."""
    found: dict[str, dict] = {}
    def add(ref: str | None, label: str, kind: str) -> None:
        if not ref or re.match(r"(javascript|mailto|tel|#|data):?", ref, re.I):
            return
        url = urljoin(page_url, ref.strip())
        path = urlsplit(url).path
        ext = Path(path).suffix.lower()
        if ext in DOC_EXT or (ext in IMAGE_EXT and not SITE_CHROME_IMAGES.search(path)):
            found.setdefault(url, {"url": url, "label": label, "kind": kind})
    for a in soup.find_all("a", href=True):
        add(a["href"], cell_text(a), "link")
    for tag in soup.find_all(["iframe", "embed", "object"]):
        add(tag.get("src") or tag.get("data"), "", "embed")
    for img in soup.find_all("img"):
        add(img.get("src"), img.get("alt", ""), "image")
    return list(found.values())


# ---------------------------------------------------------------- media library

def media_category(filename: str) -> str:
    name = filename.lower()
    if re.search(r"annex", name):
        return "annexes"
    if re.search(r"certificate", name):
        return "certificates"
    if re.search(r"schedule|scope", name):
        return "schedules_scopes"
    if re.search(r"criteria|procedure|scheme|requirement|policy|guid", name):
        return "criteria_procedures"
    if re.search(r"form|checklist|application|agreement|template|report", name):
        return "forms_templates"
    return "other"


def media_body_type(filename: str) -> str:
    """A guess from the filename; check it before relying on it."""
    tokens = set(re.split(r"[^a-z0-9]+", filename.lower()))
    for token, label in (("ib", "Inspection"), ("pcb", "Product"), ("prcb", "Personnel"), ("vv", "Validation/Verification")):
        if token in tokens:
            return label
    return "Management system or general"


def list_media(fetcher: Fetcher, base: str) -> list[dict]:
    """Uses X-WP-TotalPages: pages can be short, so a short page does not mean the end."""
    items, page, total = [], 1, 1
    while page <= total:
        resp = fetcher.get(f"{base}{MEDIA_PATH}", params={
            "per_page": 100, "page": page, "_fields": "source_url,date,title"})
        total = int(resp.headers.get("X-WP-TotalPages", total))
        items.extend(resp.json())
        page += 1
    return items


# ---------------------------------------------------------------- output

@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"  ! {message}", file=sys.stderr)

    def add(self, message: str) -> None:
        self.lines.append(message)
        print(message)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, sheets: dict[str, tuple[list[str], list[dict]]]) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        return False
    illegal = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    wb = Workbook()
    wb.remove(wb.active)
    for name, (columns, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for i, row in enumerate(rows, start=2):
            for j, col in enumerate(columns, start=1):
                cell = ws.cell(row=i, column=j)
                cell.value = illegal.sub("", str(row.get(col, "") or ""))
                cell.data_type = "s"  # phone numbers and '=...' stay as text
        for j, col in enumerate(columns):
            longest = max([len(col)] + [len(str(r.get(col, "") or "")) for r in rows[:300]])
            ws.column_dimensions[ws.cell(row=1, column=j + 1).column_letter].width = min(longest + 2, 60)
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)
    return True


# ---------------------------------------------------------------- main

def fetch_detail(fetcher: Fetcher, url: str, out: Path, refresh: bool) -> str:
    slug = safe_name(urlsplit(url).path.strip("/").replace("/", "__")) + ".html"
    path = out / "html" / slug
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    html = fetcher.page(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def run(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.delay)
    report = Report()

    print("Fetching accreditation listing...")
    records = parse_listing(fetcher.page(base + LISTING_PATH), base)
    if not records:
        print("No accreditation tables found: the page layout may have changed.", file=sys.stderr)
        return 2
    report.add(f"Active accreditations listed: {len(records)} in {len({r['scheme'] for r in records})} schemes")
    prefixes = {re.sub(r"\d.*$", "", r["certificate_no"]) for r in records}

    status_rows: list[dict] = []
    try:
        withdrawn, skipped = parse_withdrawn(fetcher.page(base + WITHDRAWN_PATH), base)
        status_rows += withdrawn
        report.add(f"Withdrawn/expired management system rows: {len(withdrawn)} (skipped non-MS tables: {', '.join(skipped) or 'none'})")
    except requests.RequestException as exc:
        report.fail(f"withdrawn page: {exc}")
    try:
        suspended = parse_suspended(fetcher.page(base + SUSPENDED_PATH), base, prefixes)
        status_rows += suspended
        report.add(f"Suspended management system rows: {len(suspended)}")
    except requests.RequestException as exc:
        report.fail(f"suspended page: {exc}")

    suspended_certs = {r["certificate_no"] for r in status_rows if r["status"] == "Suspended"}
    for rec in records:
        if rec["certificate_no"] in suspended_certs:
            rec["status"] = "Suspended"
    listed_urls = {r["detail_url"] for r in records}
    for row in status_rows:
        if row["detail_url"] and row["detail_url"] not in listed_urls and row["status"] != "Suspended":
            listed_urls.add(row["detail_url"])
            records.append({
                "scheme": row["scheme"], "certificate_no": "", "certificate_no_as_listed": "",
                "name": row["name"], "initial_issue_date": "",
                "listing_valid_upto": row["listing_valid_upto"], "detail_url": row["detail_url"],
                "status": row["status"], "status_comments": row["status_comments"],
            })

    file_rows: list[dict] = []
    no_scope: list[str] = []
    for i, rec in enumerate(records, 1):
        url = rec["detail_url"]
        print(f"[{i}/{len(records)}] {rec['certificate_no'] or '-'} {rec['name'][:60]}")
        detail: dict = {}
        if url:
            try:
                detail = parse_detail(fetch_detail(fetcher, url, out, args.refresh), url)
            except Exception as exc:  # one bad page must not lose the whole run
                report.fail(f"{rec['certificate_no'] or rec['name']} {url}: {exc}")
        else:
            report.fail(f"{rec['certificate_no'] or rec['name']}: listing row has no detail link")
        rec["certificate_no"] = rec["certificate_no"] or detail.get("certificate_no", "")
        rec.update({k: v for k, v in detail.items() if k != "certificate_no"})
        rec["detail_parsed"] = bool(detail)
        rec["scope_row_count"] = sum(r["row_type"] != "header" for r in detail.get("scope_rows", []))
        if detail and not rec["scope_row_count"]:
            no_scope.append(rec["certificate_no"] or url)
        for item in detail.get("linked_files", []):
            file_rows.append({
                "source": "detail_page", "certificate_no": rec["certificate_no"], "scheme": rec["scheme"],
                "body_name": rec["name"], "category": media_category(urlsplit(item["url"]).path),
                "body_type_guess": "Management system", "label": item["label"], "url": item["url"],
                "dest": f"documents/by_accreditation/{safe_name(rec['certificate_no'] or rec['name'])}/"
                        f"{safe_name(unquote(Path(urlsplit(item['url']).path).name))}",
            })
    report.add(f"Detail pages parsed: {sum(r['detail_parsed'] for r in records)}/{len(records)}")
    report.add(f"Pages with no scope section: {len(no_scope)} ({', '.join(no_scope)})")
    report.add(f"Files attached to detail pages: {len(file_rows)}")

    if not args.no_media:
        print("Listing public media library...")
        cb_keys = {body_key(r["name"]): r["name"] for r in records if len(body_key(r["name"])) >= 5}
        try:
            media = list_media(fetcher, base)
            docs = 0
            for item in media:
                url = item.get("source_url", "")
                name = unquote(Path(urlsplit(url).path).name)
                if Path(name).suffix.lower() not in DOC_EXT:
                    continue
                docs += 1
                compact = re.sub(r"[^a-z0-9]", "", name.lower())
                category = media_category(name)
                body_type = media_body_type(name)
                match = next((n for k, n in cb_keys.items() if k in compact), "")
                folder = "not_management_system" if body_type != "Management system or general" else category
                file_rows.append({
                    "source": "media_library", "certificate_no": "", "scheme": "",
                    "body_name": match, "category": category, "body_type_guess": body_type,
                    "label": clean((item.get("title") or {}).get("rendered", "")),
                    "published": item.get("date", ""), "url": url,
                    "dest": f"documents/site_library/{folder}/{safe_name(name)}",
                })
            report.add(f"Media library: {len(media)} items, {docs} documents")
        except (requests.RequestException, ValueError) as exc:
            report.fail(f"media library: {exc}")

    host = urlsplit(base).netloc
    seen_dest: set[str] = set()
    for i, row in enumerate(file_rows, 1):
        dest = row["dest"]
        if dest in seen_dest:  # same filename in two upload months
            stem = Path(dest)
            dest = str(stem.with_name(f"{stem.stem}__{i}{stem.suffix}"))
            row["dest"] = dest
        seen_dest.add(dest)
        if args.no_downloads:
            row["download_status"] = "skipped"
        elif urlsplit(row["url"]).netloc != host:
            row["download_status"] = "external_not_downloaded"
        else:
            print(f"[file {i}/{len(file_rows)}] {Path(dest).name}")
            try:
                row["download_status"], row["bytes"] = fetcher.download(row["url"], out / dest, args.refresh)
            except requests.RequestException as exc:
                row["download_status"] = "failed"
                report.fail(f"file {row['url']}: {exc}")

    bodies: dict[str, dict] = {}
    for rec in records:
        body = bodies.setdefault(body_key(rec["name"]) or rec["name"], {
            "name": rec["name"], "schemes": [], "certificate_nos": [], "statuses": [],
            **{f: rec.get(f, "") for f in FIELDS if f not in ("valid_from", "valid_upto", "accreditation_standards")}})
        body["schemes"].append(rec["scheme"])
        body["certificate_nos"].append(rec["certificate_no"])
        body["statuses"].append(f"{rec['certificate_no']}: {rec['status']}")
        for f in ("address", "contact_person", "designation", "tel", "mobile", "fax", "email", "website"):
            body[f] = body[f] or rec.get(f, "")
    body_rows = [dict(b, schemes="; ".join(dict.fromkeys(b["schemes"])),
                      certificate_nos="; ".join(filter(None, b["certificate_nos"])),
                      statuses="; ".join(b["statuses"]),
                      accreditation_count=len(b["certificate_nos"])) for b in bodies.values()]

    scope_rows: list[dict] = []
    width = max((len(s["cells"]) for r in records for s in r.get("scope_rows", [])), default=1)
    for rec in records:
        for n, s in enumerate(rec.get("scope_rows", []), 1):
            row = {"certificate_no": rec["certificate_no"], "scheme": rec["scheme"], "body_name": rec["name"],
                   "row": n, "section": s["section"], "row_type": s["row_type"]}
            row.update({f"col{i + 1}": c for i, c in enumerate(s["cells"])})
            scope_rows.append(row)

    acc_cols = ["scheme", "certificate_no", "name", "status", "status_comments", "initial_issue_date",
                "listing_valid_upto", *FIELDS, "iaf_scope_codes", "scope_row_count", "scope_heading",
                "detail_url", "detail_parsed"]
    body_cols = ["name", "accreditation_count", "schemes", "certificate_nos", "statuses", "address",
                 "contact_person", "designation", "tel", "mobile", "fax", "email", "website"]
    scope_cols = ["certificate_no", "scheme", "body_name", "row", "section", "row_type",
                  *[f"col{i + 1}" for i in range(width)]]
    status_cols = ["source", "scheme", "certificate_no", "name", "status", "listing_valid_upto", "status_comments", "detail_url"]
    file_cols = ["source", "certificate_no", "scheme", "body_name", "category", "body_type_guess", "label",
                 "published", "url", "dest", "download_status", "bytes"]

    write_csv(out / "accreditations.csv", acc_cols, records)
    write_csv(out / "bodies.csv", body_cols, body_rows)
    write_csv(out / "scope_rows.csv", scope_cols, scope_rows)
    write_csv(out / "withdrawn_suspended.csv", status_cols, status_rows)
    write_csv(out / "documents_manifest.csv", file_cols, file_rows)
    (out / "all_data.json").write_text(json.dumps(
        {"accreditations": records, "bodies": body_rows, "status_pages": status_rows, "documents": file_rows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    if not write_xlsx(out / "nabcb_ms_bodies.xlsx", {
            "Bodies": (body_cols, body_rows), "Accreditations": (acc_cols, records),
            "Scopes": (scope_cols, scope_rows), "Withdrawn_Suspended": (status_cols, status_rows),
            "Documents": (file_cols, file_rows)}):
        report.add("openpyxl not installed: skipped the Excel workbook")

    report.add(f"Unique bodies: {len(body_rows)}")
    report.add(f"Scope rows: {len(scope_rows)}")
    report.add(f"Failures: {len(report.failures)}")
    (out / "run_report.txt").write_text("\n".join(report.lines + ["", "FAILURES:"] + report.failures) + "\n", encoding="utf-8")
    print(f"Done. Output in {out.resolve()}")
    return 1 if report.failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape NABCB management system certification bodies.")
    parser.add_argument("--out", default="nabcb_output", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    parser.add_argument("--refresh", action="store_true", help="re-fetch pages and files already saved")
    parser.add_argument("--no-media", action="store_true", help="skip the site-wide media library")
    parser.add_argument("--no-downloads", action="store_true", help="list documents without downloading them")
    parser.add_argument("--base", default=BASE_URL, help=argparse.SUPPRESS)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
