
from __future__ import annotations

import json
import re
import time
import hashlib
from collections import deque
from pathlib import Path
from urllib.parse import (
    urljoin, urlparse, parse_qs, urlencode, urlunparse
)

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://services.accredia.it"
START_URL = (
    "https://services.accredia.it/accredia_labsearch.jsp"
    "?ID_LINK=1734&area=310&dipartimento=L&submit1=Tutti"
)

OUTPUT_DIR = Path("accredia_output")
PDF_DIR = OUTPUT_DIR / "documents"
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"

OUTPUT_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

REQUEST_DELAY = 1.0
TIMEOUT = 40

# Set False if you only want company information and test data.
DOWNLOAD_PDFS = True

# Maximum pages protects against accidental crawling loops.
MAX_LIST_PAGES = 5000

# Set True to print more diagnostic information.
DEBUG = True


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

retry = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)

session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
})


def get_page(url, params=None):
    """Fetch a page and return its HTML and final URL."""
    time.sleep(REQUEST_DELAY)

    response = session.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()

    if DEBUG:
        print(f"[GET {response.status_code}] {response.url}")

    return response.text, response.url


def clean(value):
    """Normalize whitespace in scraped text."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(url):
    """Remove fragments and normalize a URL."""
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",
    ))


def is_accredia_url(url):
    parsed = urlparse(url)
    return (
        parsed.scheme in ("http", "https")
        and parsed.netloc.lower() == "services.accredia.it"
    )


def stable_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


# ============================================================
# CHECKPOINTS
# ============================================================

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(
                CHECKPOINT_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            print("[WARN] Checkpoint unreadable; starting fresh.")

    return {
        "visited_list_pages": [],
        "detail_urls": [],
        "processed_detail_urls": [],
        "companies": {},
        "tests": [],
        "documents": [],
        "errors": [],
    }


state = load_checkpoint()


def save_checkpoint():
    CHECKPOINT_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# HTML EXTRACTION
# ============================================================

def get_tables(soup, source_url):
    """Extract all HTML tables without assuming fixed column names."""
    tables = []

    for table_index, table in enumerate(soup.find_all("table")):
        rows = []

        for tr in table.find_all("tr"):
            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["th", "td"])
            ]

            if any(cells):
                rows.append(cells)

        if not rows:
            continue

        headers = rows[0]
        data_rows = rows[1:] if table.find("th") else rows

        for row_index, row in enumerate(data_rows):
            record = {
                "source_url": source_url,
                "table_index": table_index,
                "row_index": row_index,
                "row_text": " | ".join(row),
            }

            for i, value in enumerate(row):
                header = (
                    headers[i]
                    if i < len(headers) and headers[i]
                    else f"column_{i + 1}"
                )
                record[f"field_{i + 1}_{header}"] = value

            rows_record = record
            tables.append(rows_record)

    return tables


def get_label_values(soup):
    """
    Extract common label/value layouts:
    - <th>Label</th><td>Value</td>
    - <dt>Label</dt><dd>Value</dd>
    - adjacent label/value table cells.
    """
    result = {}

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)

        if len(cells) >= 2:
            label = clean(cells[0].get_text(" ", strip=True))
            value = clean(
                " ".join(c.get_text(" ", strip=True) for c in cells[1:])
            )
            if label and value:
                result[label.rstrip(":")] = value

    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            label = clean(dt.get_text(" ", strip=True))
            value = clean(dd.get_text(" ", strip=True))
            if label and value:
                result[label.rstrip(":")] = value

    return result


def extract_documents(soup, page_url, company_id):
    """Find linked PDF and other document resources."""
    documents = []

    for link in soup.find_all("a", href=True):
        href = urljoin(page_url, link["href"])
        text = clean(link.get_text(" ", strip=True))

        if not is_accredia_url(href):
            continue

        parsed_path = urlparse(href).path.lower()
        looks_like_pdf = (
            parsed_path.endswith(".pdf")
            or ".pdf" in parsed_path
            or "pdf" in text.lower()
            or "certificat" in text.lower()
            or "prove accreditate" in text.lower()
            or "elenco prove" in text.lower()
            or "allegato" in text.lower()
        )

        if looks_like_pdf:
            documents.append({
                "company_id": company_id,
                "document_title": text,
                "document_url": href,
                "source_page": page_url,
            })

    # Also detect direct PDF URLs in embedded frames.
    for tag in soup.find_all(["iframe", "embed"]):
        src = tag.get("src")
        if not src:
            continue

        href = urljoin(page_url, src)
        if is_accredia_url(href) and ".pdf" in href.lower():
            documents.append({
                "company_id": company_id,
                "document_title": clean(tag.get("title")) or "Embedded PDF",
                "document_url": href,
                "source_page": page_url,
            })

    unique = {}
    for doc in documents:
        unique[doc["document_url"]] = doc

    return list(unique.values())


# ============================================================
# DISCOVER LIST PAGES AND LABORATORY LINKS
# ============================================================

def is_laboratory_detail_url(url):
    """
    ACCREDIA laboratory detail URLs commonly include numeroaccr.
    Keep this test conservative to avoid misclassifying search pages.
    """
    params = parse_qs(urlparse(url).query)

    return (
        "numeroaccr" in params
        and params.get("dipartimento", ["L"])[0] == "L"
    )


def crawl_search_pages():
    queue = deque([START_URL])
    queued = {normalize_url(START_URL)}
    visited = set()
    detail_urls = set(state.get("detail_urls", []))

    while queue and len(visited) < MAX_LIST_PAGES:
        current = normalize_url(queue.popleft())

        if current in visited:
            continue

        visited.add(current)

        try:
            html, final_url = get_page(current)
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            state["errors"].append({
                "url": current,
                "stage": "listing",
                "error": str(exc),
            })
            save_checkpoint()
            continue

        if is_laboratory_detail_url(final_url):
            detail_urls.add(normalize_url(final_url))

        # Search results, pagination links, and detail links.
        for a in soup.find_all("a", href=True):
            href = normalize_url(urljoin(final_url, a["href"]))

            if not is_accredia_url(href):
                continue

            path = urlparse(href).path.lower()

            if "accredia_labsearch.jsp" not in path:
                continue

            if is_laboratory_detail_url(href):
                detail_urls.add(href)
                continue

            # Follow only same-search-page links. A query may contain
            # pagination, filters, or a different result page.
            if href not in visited and href not in queued:
                queue.append(href)
                queued.add(href)

        # Some classic JSP pages paginate with GET forms.
        for form in soup.find_all("form"):
            action = urljoin(final_url, form.get("action") or final_url)

            if not is_accredia_url(action):
                continue

            if "accredia_labsearch.jsp" not in urlparse(action).path:
                continue

            form_params = {}

            for field in form.find_all(["input", "select"]):
                name = field.get("name")
                if not name or field.has_attr("disabled"):
                    continue

                if field.name == "select":
                    selected = field.find("option", selected=True)
                    if selected:
                        form_params[name] = selected.get("value", "")
                else:
                    value = field.get("value", "")
                    if field.get("type", "").lower() not in (
                        "submit", "button", "reset", "file"
                    ):
                        form_params[name] = value

            # Queue a GET variant only when it differs from the page
            # and has a useful search/pagination parameter.
            if form_params and (
                any("page" in k.lower() for k in form_params)
                or any("start" in k.lower() for k in form_params)
                or any("offset" in k.lower() for k in form_params)
            ):
                candidate = normalize_url(
                    action + "?" + urlencode(form_params)
                )
                if candidate not in visited and candidate not in queued:
                    queue.append(candidate)
                    queued.add(candidate)

        state["visited_list_pages"] = sorted(visited)
        state["detail_urls"] = sorted(detail_urls)
        save_checkpoint()

        print(
            f"[DISCOVERY] Listing pages: {len(visited)} | "
            f"Detail URLs: {len(detail_urls)}"
        )

    if queue:
        print(
            "[WARN] Page limit reached. Some listing pages may remain. "
            "Inspect checkpoint.json before continuing."
        )

    return sorted(detail_urls)


# ============================================================
# LABORATORY DETAIL PAGES
# ============================================================

def extract_company(soup, page_url):
    labels = get_label_values(soup)

    title = ""
    for selector in ["h1", "h2", "title"]:
        node = soup.find(selector)
        if node:
            title = clean(node.get_text(" ", strip=True))
            if title:
                break

    params = parse_qs(urlparse(page_url).query)

    company = {
        "company_id": stable_id(page_url),
        "laboratory_name": title,
        "accreditation_number": params.get("numeroaccr", [""])[0],
        "classification": params.get("classification", [""])[0],
        "detail_url": page_url,
        "page_title": clean(soup.title.get_text()) if soup.title else "",
        "page_text": clean(soup.get_text(" ", strip=True)),
    }

    # Preserve all extracted labels instead of losing fields whose
    # Italian names vary across page layouts.
    company["label_values_json"] = json.dumps(
        labels, ensure_ascii=False
    )

    # Map common Italian and English labels where available.
    mappings = {
        "address": ["Indirizzo", "Sede", "Indirizzo sede"],
        "city": ["Comune", "Città", "Località"],
        "province": ["Provincia"],
        "region": ["Regione"],
        "postal_code": ["CAP"],
        "phone": ["Telefono", "Tel.", "Phone"],
        "fax": ["Fax"],
        "email": ["Email", "E-mail", "Posta elettronica"],
        "pec": ["PEC"],
        "website": ["Sito web", "Web", "Website"],
        "standard": [
            "Norma", "Norma di accreditamento",
            "Standard", "Riferimento normativo"
        ],
        "status": ["Stato", "Status"],
        "issue_date": ["Data emissione", "Data di emissione"],
        "expiry_date": ["Data scadenza", "Data di scadenza"],
    }

    normalized_labels = {
        clean(key).lower(): value for key, value in labels.items()
    }

    for field, alternatives in mappings.items():
        company[field] = ""

        for alternative in alternatives:
            value = normalized_labels.get(alternative.lower())
            if value:
                company[field] = value
                break

    # If the detail page includes mailto or website links, preserve them.
    emails = []
    websites = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if href.lower().startswith("mailto:"):
            emails.append(href[7:].split("?")[0])
        elif href.lower().startswith("http"):
            if not is_accredia_url(href):
                websites.append(href)

    company["emails_found"] = "; ".join(sorted(set(emails)))
    company["websites_found"] = "; ".join(sorted(set(websites)))

    return company


def download_document(doc):
    """Download a linked document while avoiding duplicate filenames."""
    url = doc["document_url"]

    if not DOWNLOAD_PDFS:
        return ""

    filename = Path(urlparse(url).path).name
    if not filename:
        filename = stable_id(url) + ".pdf"

    # Include a URL hash to prevent same-name documents overwriting.
    suffix = Path(filename).suffix or ".pdf"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem)
    filename = f"{safe_name}_{stable_id(url)[:8]}{suffix}"

    output_path = PDF_DIR / filename

    if output_path.exists() and output_path.stat().st_size > 0:
        return str(output_path)

    try:
        time.sleep(REQUEST_DELAY)
        response = session.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        with output_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        # Detect obvious HTML error pages saved as PDFs.
        with output_path.open("rb") as f:
            signature = f.read(5)

        if not signature.startswith(b"%PDF-"):
            output_path.unlink(missing_ok=True)
            print(f"[WARN] Not a PDF: {url}")
            return ""

        print(f"[PDF] {output_path.name}")
        return str(output_path)

    except Exception as exc:
        print(f"[PDF ERROR] {url}: {exc}")
        return ""


def scrape_detail(url):
    html, final_url = get_page(url)
    soup = BeautifulSoup(html, "lxml")

    company = extract_company(soup, final_url)
    company_id = company["company_id"]

    table_rows = get_tables(soup, final_url)

    # Store each table row independently. This includes sector/test
    # information even when the table uses unexpected Italian headers.
    for row in table_rows:
        row["company_id"] = company_id
        row["laboratory_name"] = company["laboratory_name"]
        state["tests"].append(row)

    documents = extract_documents(soup, final_url, company_id)

    for doc in documents:
        doc["local_path"] = download_document(doc)
        state["documents"].append(doc)

    state["companies"][final_url] = company
    state["processed_detail_urls"].append(url)
    save_checkpoint()

    print(
        f"[LAB] {company['laboratory_name'] or '(name not detected)'} "
        f"| Accreditation: {company['accreditation_number']} "
        f"| Tables: {len(table_rows)} "
        f"| Documents: {len(documents)}"
    )


# ============================================================
# EXPORT
# ============================================================

def export_results():
    companies = list(state["companies"].values())
    tests = state["tests"]
    documents = state["documents"]
    errors = state["errors"]

    pd.DataFrame(companies).to_csv(
        OUTPUT_DIR / "laboratories.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(tests).to_csv(
        OUTPUT_DIR / "technical_details.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(documents).to_csv(
        OUTPUT_DIR / "documents.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(errors).to_csv(
        OUTPUT_DIR / "errors.csv",
        index=False,
        encoding="utf-8-sig",
    )

    with pd.ExcelWriter(
        OUTPUT_DIR / "accredia_database.xlsx",
        engine="openpyxl",
    ) as writer:
        pd.DataFrame(companies).to_excel(
            writer, sheet_name="Laboratories", index=False
        )

        pd.DataFrame(tests).to_excel(
            writer, sheet_name="Technical Details", index=False
        )

        pd.DataFrame(documents).to_excel(
            writer, sheet_name="Documents", index=False
        )

        pd.DataFrame(errors).to_excel(
            writer, sheet_name="Errors", index=False
        )

    print("\n========== EXPORT COMPLETE ==========")
    print(f"Laboratories: {len(companies)}")
    print(f"Technical table rows: {len(tests)}")
    print(f"Documents: {len(documents)}")
    print(f"Errors: {len(errors)}")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")


def main():
    print("ACCREDIA laboratory scraper")
    print(f"Starting URL: {START_URL}")

    detail_urls = crawl_search_pages()

    processed = set(state.get("processed_detail_urls", []))

    for index, url in enumerate(detail_urls, start=1):
        if url in processed:
            continue

        print(f"\n[{index}/{len(detail_urls)}] Scraping detail page")

        try:
            scrape_detail(url)
        except Exception as exc:
            state["errors"].append({
                "url": url,
                "stage": "detail",
                "error": str(exc),
            })
            save_checkpoint()
            print(f"[ERROR] {url}: {exc}")

    export_results()


if __name__ == "__main__":
    main()
