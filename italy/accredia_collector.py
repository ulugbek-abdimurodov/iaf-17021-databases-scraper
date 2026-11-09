#!/usr/bin/env python3
"""
ACCREDIA accredited-body collector
Source: https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310

Features:
- Keeps company/accreditation codes as strings (preserves leading zeros).
- Crawls every organization linked from the Accredia results table.
- Extracts contact details and accreditation sections from each detail page.
- Finds PDF/document links in hrefs and onclick attributes.
- Retries transient HTTP failures, validates downloaded PDFs, resumes existing valid files.
- Writes an Excel workbook with Companies, Accreditations, Documents, and Errors sheets.
- Saves raw HTML for pages where document links were not discovered, for diagnostics.

Use responsibly: conservative request rate, no login/captcha bypass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://services.accredia.it"
LIST_PATH = "/ppsearch/accredia_orgmask.jsp"
LIST_URL = f"{BASE}{LIST_PATH}?ID_LINK=1733&area=310"
# Match a normal desktop browser more closely. The old non-browser User-Agent could
# be treated differently by upstream protection, and the old URL omitted form fields.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")
PDF_RE = re.compile(r"""(?i)(?:https?://[^"'()\s]+|/[^"'()\s]+|[A-Za-z0-9_./?=&%-]+)\.pdf(?:\?[^"'()\s]*)?""")
URL_RE = re.compile(r"""(?i)(?:https?://[^"'()\s<>]+|/[A-Za-z0-9_./?=&%-]+)""")

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=3, connect=3, read=3, status=2,
        backoff_factor=1.5,
        # Do not hammer the site on HTTP 500; list fetching tries alternate official
        # URL variants and reports the status cleanly instead.
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def fetch_organization_list(session: requests.Session, timeout: int, local_html: str = "") -> tuple[BeautifulSoup, str]:
    """Fetch the organization list using multiple official URL variants.

    Some server/proxy paths return HTTP 500 for a minimal query string. We first
    establish a session, then try the full search-form query used by Accredia.
    If the site remains unavailable, an HTML file saved manually from the official
    browser page can be supplied via --list-html.
    """
    if local_html:
        html_path = Path(local_html).expanduser()
        if not html_path.is_file():
            raise FileNotFoundError(f"--list-html file does not exist: {html_path}")
        content = html_path.read_bytes()
        soup = BeautifulSoup(content, "html.parser")
        if not extract_company_rows(soup):
            raise RuntimeError(
                f"Loaded {html_path}, but found no company result links. "
                "Save the Accredia results page (not a company detail page) as HTML."
            )
        return soup, f"local file: {html_path}"

    # Warm up session/cookies. This can help with legacy Java/JSP applications.
    warmup_urls = [
        f"{BASE}/ppsearch/accredia_orgmask.jsp?ID_LINK=1733",
        f"{BASE}/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310",
        "https://www.accredia.it/banche-dati/",
    ]
    diagnostics = []
    for url in warmup_urls:
        try:
            r = session.get(
                url, timeout=timeout, allow_redirects=True,
                headers={"Referer": "https://www.accredia.it/banche-dati/"},
            )
            diagnostics.append(f"warm-up {r.status_code}: {r.url}")
            if r.status_code < 500:
                break
        except requests.RequestException as exc:
            diagnostics.append(f"warm-up error: {url}: {type(exc).__name__}: {exc}")

    form_params = {
        "ID_LINK": "1733",
        "area": "310",
        "PPSEARCH_ORG_SEARCH_MASK_ORG": "",
        "PPSEARCH_ORG_SEARCH_MASK_STANDARDS": "",
        "PPSEARCH_ORG_SEARCH_MASK_SCHEMI_ALTRI_STD": "",
        "PPSEARCH_ODC_SEARCH_MASK_SETTORE_ACCR": "",
        "PPSEARCH_ORG_SEARCH_MASK_CITTA": "",
        "PPSEARCH_ORG_SEARCH_MASK_PROVINCIA": "",
        "PPSEARCH_ORG_SEARCH_MASK_REGIONE": "",
        "PPSEARCH_ORG_SEARCH_MASK_STATO": "",
        "PPSEARCH_ORG_SEARCH_MASK_SCOPO": "",
        "PPSEARCH_ORG_SEARCH_MASK_PDFACCREDITAMENTO": "",
        "submitBtn": "Cerca",
    }
    candidates = [
        (f"{BASE}{LIST_PATH}?ID_LINK=1733&area=310", None),
        (f"{BASE}{LIST_PATH}?ID_LINK=1733", None),
        (f"{BASE}{LIST_PATH}", form_params),
        (f"{BASE}{LIST_PATH}?ID_LINK=1733&area=310", form_params),
    ]
    last_status = None
    for url, params in candidates:
        try:
            logging.info("Trying Accredia list endpoint: %s", url)
            r = session.get(
                url, params=params, timeout=timeout, allow_redirects=True,
                headers={
                    "Referer": f"{BASE}{LIST_PATH}?ID_LINK=1733&area=310",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            last_status = r.status_code
            diagnostics.append(f"list {r.status_code}: {r.url}")
            if r.status_code >= 500:
                logging.warning("Accredia returned HTTP %s for %s", r.status_code, r.url)
                time.sleep(1.5)
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            rows = extract_company_rows(soup)
            if rows:
                logging.info("List loaded successfully: %d company rows found", len(rows))
                return soup, r.url
            # Sometimes a 200 response is an error/landing page, not the results.
            logging.warning("HTTP 200 but no company result links found at %s", r.url)
            diagnostics.append("HTTP 200 but no organization result links found")
        except requests.RequestException as exc:
            diagnostics.append(f"request error: {url}: {type(exc).__name__}: {exc}")
            logging.warning("List endpoint failed: %s", exc)

    detail = "\n  - ".join(diagnostics)
    raise RuntimeError(
        "Could not retrieve the Accredia organization list after trying the official URL variants. "
        f"Last HTTP status: {last_status!r}.\n"
        "This is likely an upstream server/proxy response, not a Python syntax problem.\n"
        "Try opening the official list page in your browser. If it works there, save that results page "
        "as HTML and rerun with --list-html path\\to\\saved_page.html.\n"
        "Attempts:\n  - " + detail
    )

def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def safe_name(s: str, limit: int = 90) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", "_", s).strip("._ ")
    return (s or "unknown")[:limit]

def soup_text(soup: BeautifulSoup) -> str:
    return clean(soup.get_text(" ", strip=True))

def parse_date_near(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*:?\s*({DATE_RE.pattern})", text, re.I)
    return m.group(1) if m else ""

def get_detail_url(href: str) -> tuple[str, str]:
    # Accredia sometimes emits query-only links, and urljoin(BASE, href) drops
    # the required JSP path. Rebuild the detail URL from its company code.
    full = urljoin(f"{BASE}{LIST_PATH}", href)
    q = parse_qs(urlparse(full).query)
    # Keep the original identifier exactly as supplied by the official option/link.
    code = (q.get("PPSEARCH_ORG_SEARCH_MASK_ORG") or [""])[0]
    if code:
        from urllib.parse import urlencode
        full = f"{BASE}{LIST_PATH}?" + urlencode({
            "ID_LINK": "1733", "area": "310", "PPSEARCH_ORG_SEARCH_MASK_ORG": code
        })
    return full, code

def extract_company_rows(soup: BeautifulSoup) -> list[dict]:
    rows, seen = [], set()
    # The results table contains links to detail pages. Do not treat dropdown options
    # as result rows: options may include entities outside the current result set.
    for a in soup.select('a[href*="PPSEARCH_ORG_SEARCH_MASK_ORG="]'):
        href = a.get("href", "")
        full, code = get_detail_url(href)
        name = clean(a.get_text(" ", strip=True))
        if not code or not name or code in seen:
            continue
        seen.add(code)
        rows.append({
            "company_code": str(code),
            "company_name": name,
            "detail_url": full,
        })
    return rows

def label_value(text: str, labels: list[str]) -> str:
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s+(?:Tel(?:efono)?|Fax|Email|E-mail|Sito Web|Schema|Accreditamenti|Norma|Accreditamento N\.|Emesso il|$))", text, re.I)
        if m:
            value = clean(m.group(1))
            if value and len(value) < 500:
                return value
    return ""

def is_company_detail_page(soup: BeautifulSoup, company: dict) -> bool:
    """Reject a search/landing page even when it returned HTTP 200."""
    text = soup_text(soup).casefold()
    name = clean(company.get("company_name", "")).strip('"“”').casefold()
    return bool(name and name in text and "schema di accreditamento" in text
                and ("sedi accreditate" in text or "organismo accreditato" in text
                     or "laboratorio accreditato" in text))


def extract_contacts(soup: BeautifulSoup) -> dict:
    """Extract only the company's contact block, never Accredia's site footer."""
    text = soup_text(soup)
    start = re.search(r"Sito Web\s*:|Sedi Accreditate", text, re.I)
    if not start:
        return {k: "" for k in ("website", "email", "phone", "fax", "address")}
    end = re.search(r"\b(?:Schema\s*:|Accreditamenti)\b", text[start.start():], re.I)
    block = text[start.start():start.start() + end.start()] if end else text[start.start():]
    block = re.split(r"\b(?:Sede legale|Sede distaccata|Dipartimento)\b", block, maxsplit=1, flags=re.I)[0]

    def capture(pattern: str) -> str:
        m = re.search(pattern, block, re.I)
        return clean(m.group(1)).rstrip(" .;,") if m else ""

    website = capture(r"Sito Web\s*:\s*(\S+)")
    emails = []
    for a in soup.select('a[href^="mailto:"]'):
        email = a.get("href", "").split(":", 1)[-1].split("?", 1)[0].strip()
        if email and email.casefold() not in [e.casefold() for e in emails] and email.casefold() in block.casefold():
            emails.append(email)
    address = capture(r"Sedi Accreditate\s+(.*?)(?=\s+Tel\.?\s*:|$)")
    return {
        "website": website,
        "email": "; ".join(emails),
        "phone": capture(r"\bTel\.?\s*:?\s*([+()\d][+()\d ./-]{5,})"),
        "fax": capture(r"\bFax\s*:?\s*([+()\d][+()\d ./-]{5,})"),
        "address": address[:1200],
    }

def extract_accreditations(soup: BeautifulSoup, company: dict) -> list[dict]:
    # Parse text from each visible "Schema di accreditamento" block. Labels vary a little
    # between schemes, so retain a raw block for auditability.
    text = soup_text(soup)
    marker = re.compile(r"Schema di accreditamento\s*:", re.I)
    matches = list(marker.finditer(text))
    result = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        def find(label: str) -> str:
            mm = re.search(rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s+(?:Norma|Accreditamento N\.|Emesso il|Allegato|Certificato|Data Rev\.|Rev\.|$))", block, re.I)
            return clean(mm.group(1)) if mm else ""
        schema = find("Schema di accreditamento")
        standard = find("Norma")
        number = find("Accreditamento N.")
        issued = find("Emesso il")
        # Preserve the complete text to avoid losing multi-line scope/sector details.
        result.append({
            "company_code": company["company_code"],
            "company_name": company["company_name"],
            "schema": schema,
            "standard": standard,
            "accreditation_number": number,
            "issued_date": issued,
            "scope_sector_text": block[:6000],
            "detail_url": company["detail_url"],
        })
    if not result:
        result.append({
            "company_code": company["company_code"],
            "company_name": company["company_name"],
            "schema": "", "standard": "", "accreditation_number": "", "issued_date": "",
            "scope_sector_text": "", "detail_url": company["detail_url"],
        })
    return result

def find_document_candidates(soup: BeautifulSoup, page_url: str) -> list[dict]:
    candidates, seen = [], set()
    def add(raw_url: str, label: str, source_attr: str):
        raw_url = unquote(raw_url.strip().strip("'\"` ;,"))
        if not raw_url or raw_url.lower().startswith(("javascript:", "mailto:", "#")):
            return
        url = urljoin(page_url, raw_url)
        if not url.startswith(("http://", "https://")):
            return
        key = (url, clean(label))
        if key in seen:
            return
        seen.add(key)
        label = clean(label) or Path(urlparse(url).path).name or "document"
        # Restrict downloads to document-like links and likely document actions.
        path = urlparse(url).path.lower()
        is_pdf = path.endswith(".pdf") or ".pdf/" in path
        likely_doc = is_pdf or any(k in (label + " " + url).lower() for k in [
            "certificato", "certificato", "allegato", "download", "documento", "pdf", "scarica"
        ])
        if likely_doc:
            candidates.append({
                "document_label": label[:250],
                "document_url": url,
                "source_attribute": source_attr,
                "looks_like_pdf": is_pdf,
            })

    for a in soup.find_all(["a", "button"], href=True):
        href = a.get("href", "")
        label = clean(a.get_text(" ", strip=True)) or clean(a.get("title", ""))
        add(href, label, "href")
    for el in soup.find_all(True):
        for attr in ("onclick", "data", "data-url", "data-href", "data-file", "title"):
            val = el.get(attr)
            if not isinstance(val, str) or not val:
                continue
            # URLs in onclick and data attributes (including relative paths).
            for match in URL_RE.findall(val):
                add(match, clean(el.get_text(" ", strip=True)) or val[:120], attr)
            for match in PDF_RE.findall(val):
                add(match, clean(el.get_text(" ", strip=True)) or "PDF", attr)
    # Keep only URLs that look document-related or have a PDF extension.
    return candidates

def is_valid_pdf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 800:
            return False
        with path.open("rb") as f:
            head = f.read(2048)
        return b"%PDF-" in head
    except OSError:
        return False

def download_document(session: requests.Session, doc: dict, dest: Path, timeout: int) -> tuple[str, str, int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_valid_pdf(dest):
        return "already_downloaded_valid", str(dest), dest.stat().st_size, ""
    last_error = ""
    for attempt in range(1, 5):
        try:
            with session.get(doc["document_url"], timeout=timeout, stream=True, allow_redirects=True) as r:
                r.raise_for_status()
                content_type = r.headers.get("Content-Type", "").lower()
                temp = dest.with_suffix(dest.suffix + ".part")
                size = 0
                with temp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=128 * 1024):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size >= 800 and is_valid_pdf(temp):
                    temp.replace(dest)
                    return "downloaded", str(dest), size, ""
                # Some document endpoints return a PDF with a non-pdf filename.
                if size >= 800 and ("pdf" in content_type or b"%PDF-" in temp.read_bytes()[:2048]):
                    temp.replace(dest)
                    if is_valid_pdf(dest):
                        return "downloaded", str(dest), size, ""
                preview = temp.read_bytes()[:300].decode("utf-8", "replace")
                temp.unlink(missing_ok=True)
                last_error = f"Response was not a valid PDF (Content-Type={content_type}; preview={preview[:120]!r})"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < 4:
            time.sleep(1.5 * attempt)
    return "failed", "", 0, last_error

def main():
    parser = argparse.ArgumentParser(description="Collect Accredia accredited-body details and PDFs.")
    parser.add_argument("--out", default="accredia_output", help="Output folder")
    parser.add_argument("--limit", type=int, default=0, help="Limit organizations for a test run; 0 means all")
    parser.add_argument("--delay", type=float, default=0.8, help="Seconds between page requests")
    parser.add_argument("--timeout", type=int, default=35, help="HTTP timeout in seconds")
    parser.add_argument("--list-html", default="", help="Use a saved official Accredia results-page HTML file if the server returns 500")
    parser.add_argument("--diagnose-list", action="store_true", help="Only test/fetch the list page and print the number of company rows")
    parser.add_argument("--include-dropdown-only", action="store_true",
                        help="Also crawl IDs in the company dropdown that are not in current result rows")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    pdf_root = out / "pdfs"
    raw_root = out / "raw_html"
    out.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = make_session()
    errors, companies, accreditations, documents = [], [], [], []

    logging.info("Fetching Accredia organization list")
    try:
        list_soup, list_source = fetch_organization_list(session, args.timeout, args.list_html)
    except Exception as exc:
        logging.error("%s", exc)
        raise SystemExit(2)
    orgs = extract_company_rows(list_soup)
    logging.info("Organization list source: %s", list_source)
    logging.info("Organization rows found: %d", len(orgs))
    if args.diagnose_list:
        print(json.dumps({
            "list_source": list_source,
            "organization_rows_found": len(orgs),
            "sample": orgs[:3],
        }, ensure_ascii=False, indent=2))
        return
    if not orgs:
        logging.error("No organization rows found; refusing to create an empty report.")
        raise SystemExit(2)

    if args.include_dropdown_only:
        existing = {o["company_code"] for o in orgs}
        for opt in list_soup.select("select option[value]"):
            code = clean(opt.get("value"))
            name = clean(opt.get_text(" ", strip=True))
            if code and code not in existing and re.fullmatch(r"\d{1,8}", code) and name and name != "[...]":
                orgs.append({
                    "company_code": code, "company_name": name,
                    "detail_url": f"{BASE}/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG={code}",
                })
                existing.add(code)

    # Keep IDs as strings. Dedupe by code while preserving the first official list occurrence.
    unique = {}
    for org in orgs:
        unique.setdefault(str(org["company_code"]), org)
    orgs = list(unique.values())
    if args.limit > 0:
        orgs = orgs[:args.limit]
    logging.info("Organizations queued: %d", len(orgs))

    for idx, org in enumerate(orgs, 1):
        code = str(org["company_code"])
        logging.info("[%d/%d] %s (%s)", idx, len(orgs), org["company_name"], code)
        base = {
            "company_code": code,
            "company_name": org["company_name"],
            "detail_url": org["detail_url"],
            "website": "",
            "email": "",
            "phone": "",
            "fax": "",
            "address": "",
            "page_fetch_status": "pending",
            "detail_page_verified": False,
            "website_source_url": "", "email_source_url": "", "phone_source_url": "",
            "fax_source_url": "", "address_source_url": "",
            "page_fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            r = session.get(org["detail_url"], timeout=args.timeout)
            r.raise_for_status()
            page = BeautifulSoup(r.content, "html.parser")
            raw_path = raw_root / f"{safe_name(code)}_{safe_name(org['company_name'])}.html"
            raw_path.write_bytes(r.content)
            if not is_company_detail_page(page, org):
                base["page_fetch_status"] = "not_company_detail_page"
                companies.append(base)
                accreditations.extend(extract_accreditations(BeautifulSoup("", "html.parser"), org))
                errors.append({
                    "company_code": code, "company_name": org["company_name"],
                    "stage": "verify_detail_page",
                    "error": "Response did not contain the requested company's detail content; contact and accreditation fields left blank.",
                    "detail_url": r.url, "raw_html": str(raw_path),
                })
                time.sleep(max(0, args.delay))
                continue
            base.update(extract_contacts(page))
            base["page_fetch_status"] = "ok"
            base["detail_page_verified"] = True
            for field in ("website", "email", "phone", "fax", "address"):
                if base[field]:
                    base[f"{field}_source_url"] = r.url
            companies.append(base)
            accreditations.extend(extract_accreditations(page, org))
            candidates = find_document_candidates(page, org["detail_url"])
            if not candidates:
                errors.append({
                    "company_code": code, "company_name": org["company_name"],
                    "stage": "discover_documents", "error": "No document links discovered; inspect raw HTML",
                    "detail_url": org["detail_url"], "raw_html": str(raw_path),
                })
            for n, doc in enumerate(candidates, 1):
                label = doc["document_label"]
                ext = ".pdf" if doc["looks_like_pdf"] else ".bin"
                filename = f"{safe_name(code)}_{safe_name(org['company_name'], 45)}_{n:02d}_{safe_name(label, 55)}{ext}"
                target = pdf_root / safe_name(code) / filename
                status, local_path, size, err = download_document(session, doc, target, args.timeout)
                # If an endpoint returns a PDF without a .pdf URL extension, correct filename.
                if status == "downloaded" and local_path and not Path(local_path).suffix.lower() == ".pdf" and is_valid_pdf(Path(local_path)):
                    corrected = Path(local_path).with_suffix(".pdf")
                    Path(local_path).replace(corrected)
                    local_path = str(corrected)
                documents.append({
                    "company_code": code, "company_name": org["company_name"],
                    "document_label": label, "document_url": doc["document_url"],
                    "source_attribute": doc["source_attribute"], "status": status,
                    "local_path": local_path, "bytes": size, "error": err,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                })
                if status == "failed":
                    errors.append({
                        "company_code": code, "company_name": org["company_name"],
                        "stage": "download_document", "error": err,
                        "detail_url": doc["document_url"], "raw_html": str(raw_path),
                    })
            if not candidates:
                # Diagnostic snapshot is retained to improve selectors without re-fetching.
                pass
        except Exception as e:
            base["page_fetch_status"] = "failed"
            companies.append(base)
            errors.append({
                "company_code": code, "company_name": org["company_name"],
                "stage": "fetch_detail", "error": f"{type(e).__name__}: {e}",
                "detail_url": org["detail_url"], "raw_html": "",
            })
        time.sleep(max(0, args.delay))

    # Explicitly add a summary for official status: do not infer it from dates.
    company_df = pd.DataFrame(companies)
    accreditation_df = pd.DataFrame(accreditations)
    documents_df = pd.DataFrame(documents)
    errors_df = pd.DataFrame(errors)

    if not accreditation_df.empty:
        accreditation_df["official_status"] = "not_extracted_from_detail_page"
        accreditation_df["date_based_estimate"] = "unknown"
        accreditation_df["status_note"] = (
            "No official active/suspended/withdrawn status inferred. Confirm against Accredia's official register; "
            "a future expiry date alone does not prove current validity."
        )
    if not documents_df.empty:
        documents_df["is_valid_pdf"] = documents_df.apply(
            lambda row: bool(row.get("local_path")) and is_valid_pdf(Path(str(row["local_path"]))), axis=1
        )

    workbook = out / "accredia_report.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        (company_df if not company_df.empty else pd.DataFrame(columns=[
            "company_code", "company_name", "website", "email", "phone", "fax", "address",
            "detail_url", "detail_page_verified", "website_source_url", "email_source_url",
            "phone_source_url", "fax_source_url", "address_source_url", "page_fetch_status"
        ])).to_excel(writer, sheet_name="Companies", index=False)
        (accreditation_df if not accreditation_df.empty else pd.DataFrame(columns=[
            "company_code", "company_name", "schema", "standard", "accreditation_number",
            "issued_date", "scope_sector_text", "official_status", "date_based_estimate"
        ])).to_excel(writer, sheet_name="Accreditations", index=False)
        (documents_df if not documents_df.empty else pd.DataFrame(columns=[
            "company_code", "company_name", "document_label", "document_url", "status", "local_path", "error"
        ])).to_excel(writer, sheet_name="Documents", index=False)
        (errors_df if not errors_df.empty else pd.DataFrame(columns=[
            "company_code", "company_name", "stage", "error", "detail_url", "raw_html"
        ])).to_excel(writer, sheet_name="Errors", index=False)

        # Excel formatting: filters, frozen header, reasonable widths, and text format for IDs.
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                letter = col[0].column_letter
                max_len = max((len(str(c.value or "")) for c in col[:200]), default=10)
                ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 60)
            header = {cell.value: cell.column for cell in ws[1]}
            if "company_code" in header:
                for row in range(2, ws.max_row + 1):
                    cell = ws.cell(row, header["company_code"])
                    cell.number_format = "@"
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    if isinstance(cell.value, str) and len(cell.value) > 32000:
                        cell.value = cell.value[:31900] + " [TRUNCATED FOR EXCEL CELL LIMIT]"

    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "organizations_queued": len(orgs),
        "company_rows": len(companies),
        "accreditation_rows": len(accreditations),
        "document_rows": len(documents),
        "documents_downloaded": sum(d["status"] == "downloaded" for d in documents),
        "documents_already_valid": sum(d["status"] == "already_downloaded_valid" for d in documents),
        "documents_failed": sum(d["status"] == "failed" for d in documents),
        "errors": len(errors),
        "workbook": str(workbook),
        "note": "Accredia official status must be verified from an authoritative status/register source; dates are not status.",
    }
    (out / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Finished: %s", json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
