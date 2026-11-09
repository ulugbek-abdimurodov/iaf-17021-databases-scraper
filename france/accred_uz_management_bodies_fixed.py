from pathlib import Path

import argparse
import csv
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://akkred.uz/uz/reestr"
TYPE_STD = "20"
SITE_ROOT = "https://akkred.uz"
PDF_HOSTS = ("akkred.uz", "api-e.akkred.uz")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("akkred-uz-scraper")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_filename(value: str, max_length: int = 110) -> str:
    value = unquote(value or "").strip()
    value = re.sub(r"[^\w.\- ]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value)
    return (value[:max_length].strip("._") or "document")


def get_registry_table(page):
    """Find the main registry table by its column headings."""
    for table in page.locator("table").all():
        try:
            text = clean(table.inner_text(timeout=1500))
            if "Ro" in text and "MB va MX" in text and "Akkreditatsiya" in text:
                return table
        except Exception:
            continue
    raise RuntimeError("Could not find the registry table. The website layout may have changed.")


def registry_rows(table):
    """Return rows containing O'ZAK.MT registry numbers."""
    found = []
    for row in table.locator("tr").all():
        try:
            text = clean(row.inner_text(timeout=1000))
            match = re.search(r"O['’]ZAK\.MT\.\d+", text, re.I)
            if match:
                found.append((row, match.group(0)))
        except Exception:
            pass
    return found


def row_summary(row, registry_number: str) -> dict:
    cells = row.locator(":scope > td")
    values = []

    for cell in cells.all():
        try:
            values.append(clean(cell.inner_text(timeout=1500)))
        except Exception:
            values.append("")

    name = values[2] if len(values) > 2 else ""

    if not name:
        buttons = row.locator("button")
        for button in buttons.all():
            try:
                text = clean(button.inner_text(timeout=1000))
                if text and registry_number not in text:
                    name = text
                    break
            except Exception:
                continue

    return {
        "registry_number": registry_number,
        "organization_name": name,
        "accreditation_date_list": values[3] if len(values) > 3 else "",
        "status_list": values[4] if len(values) > 4 else "",
    }

def extract_detail_tables(scope) -> tuple[dict, list[dict]]:
    """
    Extract key/value rows from expanded detail tables.
    Returns (fields, linked_documents).
    """
    fields: dict[str, str] = {}
    documents: list[dict] = []

    for table in scope.locator("table").all():
        try:
            for tr in table.locator("tr").all():
                tds = tr.locator("td")
                if tds.count() < 2:
                    continue
                label = clean(tds.nth(0).inner_text(timeout=700)).rstrip(":")
                value = clean(tds.nth(1).inner_text(timeout=700))
                if label and value and len(label) < 130:
                    fields[label] = value

                for anchor in tds.nth(1).locator("a[href]").all():
                    href = anchor.get_attribute("href")
                    if not href:
                        continue
                    absolute = urljoin(SITE_ROOT, href)
                    label_text = clean(anchor.inner_text(timeout=500)) or label or "document"
                    if ".pdf" in urlparse(absolute).path.lower() or "/media/file/" in absolute.lower():
                        documents.append({
                            "document_label": label_text,
                            "document_url": absolute,
                        })
        except Exception:
            continue

    # De-duplicate document URLs.
    unique = {}
    for doc in documents:
        unique[doc["document_url"]] = doc
    return fields, list(unique.values())


def extract_pdf_links_from_scope(scope) -> list[dict]:
    docs = []
    for anchor in scope.locator("a[href]").all():
        try:
            href = anchor.get_attribute("href")
            if not href:
                continue
            absolute = urljoin(SITE_ROOT, href)
            path = urlparse(absolute).path.lower()
            if path.endswith(".pdf") or "/media/file/" in absolute.lower():
                docs.append({
                    "document_label": clean(anchor.inner_text(timeout=500)) or "document",
                    "document_url": absolute,
                })
        except Exception:
            pass
    return list({d["document_url"]: d for d in docs}.values())


def expand_record(page, row, registry_number: str):
    """Open the organization's details if they are not already expanded."""
    try:
        row_text = clean(row.inner_text(timeout=1000))
        if "STIR" in row_text or "Akkreditatsiya sohasi" in row_text:
            return

        # The organization name is usually a button in the third column.
        buttons = row.locator("button")
        target = None
        for button in buttons.all():
            label = clean(button.inner_text(timeout=500))
            if label and registry_number not in label:
                target = button
                break

        if target is None and buttons.count():
            target = buttons.last

        if target is not None:
            target.click(timeout=5000)
            page.wait_for_timeout(900)
    except PlaywrightTimeoutError:
        log.warning("%s: timeout while opening details", registry_number)
    except Exception as exc:
        log.warning("%s: could not open details: %s", registry_number, exc)


def get_detail_scope(row):
    """
    Details may be nested in the registry row or rendered in the next sibling row.
    Return whichever contains the detail table.
    """
    try:
        nested = row.locator("table")
        if nested.count():
            return row
    except Exception:
        pass

    try:
        following = row.locator("xpath=following-sibling::tr[1]")
        if following.count() and following.locator("table").count():
            return following
    except Exception:
        pass
    return row


def download_document(request_context, document: dict, folder: Path, registry_number: str) -> dict:
    url = document["document_url"]
    parsed_name = Path(urlparse(url).path).name
    filename = safe_filename(parsed_name or document.get("document_label", "document.pdf"))
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    target_dir = folder / safe_filename(registry_number)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    if target.exists() and target.stat().st_size > 0:
        return {**document, "downloaded_file": str(target), "download_status": "already_exists"}

    last_error = ""
    for attempt in range(1, 4):
        try:
            response = request_context.get(url, timeout=60000)
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")
            content_type = (response.headers.get("content-type") or "").lower()
            body = response.body()
            if not body:
                raise RuntimeError("Empty response")
            if "pdf" not in content_type and not body.startswith(b"%PDF"):
                # Some servers send PDFs as application/octet-stream.
                if not body.startswith(b"%PDF"):
                    raise RuntimeError(f"Response is not a PDF (content-type={content_type})")
            target.write_bytes(body)
            return {
                **document,
                "downloaded_file": str(target),
                "download_status": "downloaded",
                "file_size_bytes": len(body),
            }
        except Exception as exc:
            last_error = str(exc)
            log.warning("PDF attempt %s/3 failed for %s: %s", attempt, url, exc)
            time.sleep(attempt * 2)

    return {
        **document,
        "downloaded_file": "",
        "download_status": "failed",
        "download_error": last_error,
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape O'ZAKK management system certification bodies.")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximum registry pages to scan (default: 20)")
    parser.add_argument("--out", default="akkred_uz_management_bodies", help="Output directory")
    parser.add_argument("--no-download", action="store_true", help="Only collect data and PDF URLs")
    parser.add_argument("--slow-mo", type=int, default=0, help="Slow browser actions by N milliseconds")
    args = parser.parse_args()

    out_dir = Path(args.out)
    pdf_dir = out_dir / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    seen_registry_numbers = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=args.slow_mo)
        context = browser.new_context(
            accept_downloads=True,
            locale="uz-UZ",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
        )
        page = context.new_page()
        page.set_default_timeout(12000)

        # Start with the registry filter only. Do not add status=active:
        # we want active, expired, suspended, and other statuses.
        first_url = f"{BASE_URL}?page=1&type_std={TYPE_STD}"
        log.info("Opening registry: %s", first_url)
        page.goto(first_url, wait_until="domcontentloaded", timeout=60000)
        page.locator("table").first.wait_for(state="visible", timeout=20000)
        page.wait_for_timeout(1200)

        for page_number in range(1, args.max_pages + 1):
            log.info("Reading registry page %s", page_number)

            try:
                table = get_registry_table(page)
                rows = registry_rows(table)
            except Exception as exc:
                log.error("Could not read page %s: %s", page_number, exc)
                break

            if not rows:
                log.info("No registry rows found on page %s; stopping.", page_number)
                break

            page_new_records = 0

            # Snapshot registry numbers first. Expanding a row can change the DOM.
            page_numbers = [number for _, number in rows]

            for registry_number in page_numbers:
                if registry_number in seen_registry_numbers:
                    continue

                seen_registry_numbers.add(registry_number)
                page_new_records += 1

                try:
                    row = page.locator("tr").filter(has_text=registry_number).first
                    record = row_summary(row, registry_number)
                    record["source_page"] = page.url

                    log.info(
                        "Processing %s | %s",
                        registry_number,
                        record.get("organization_name", "")[:90],
                    )

                    expand_record(page, row, registry_number)
                    page.wait_for_timeout(350)

                    # Re-find the row after expansion; Playwright locators are live.
                    row = page.locator("tr").filter(has_text=registry_number).first
                    scope = get_detail_scope(row)
                    fields, documents = extract_detail_tables(scope)

                    if not fields or not documents:
                        sibling = row.locator("xpath=following-sibling::tr[1]")
                        if sibling.count():
                            sibling_fields, sibling_docs = extract_detail_tables(sibling)
                            if not fields:
                                fields = sibling_fields
                            if not documents:
                                documents = sibling_docs
                            if not documents:
                                documents = extract_pdf_links_from_scope(sibling)

                    if not documents:
                        documents = extract_pdf_links_from_scope(scope)

                    record["details"] = fields
                    record["documents"] = documents
                    record["pdf_count"] = len(documents)

                    if not args.no_download:
                        record["documents"] = [
                            download_document(
                                context.request, document, pdf_dir, registry_number
                            )
                            for document in documents
                        ]

                    records.append(record)

                    # Save after each record, so interrupted runs retain progress.
                    (out_dir / "records.json").write_text(
                        json.dumps(records, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                except Exception as exc:
                    log.exception("%s: record extraction failed: %s", registry_number, exc)
                    records.append({
                        "registry_number": registry_number,
                        "organization_name": "",
                        "source_page": page.url,
                        "details": {},
                        "documents": [],
                        "pdf_count": 0,
                        "scrape_error": str(exc),
                    })

            log.info("Page %s: %s new records", page_number, page_new_records)

            if page_number >= args.max_pages:
                break

            # Prefer the site's own pagination control (button or link).
            next_page_number = str(page_number + 1)
            next_control = page.get_by_role(
                "button", name=next_page_number, exact=True
            )
            if not next_control.count():
                next_control = page.get_by_role(
                    "link", name=next_page_number, exact=True
                )

            if not next_control.count():
                log.info("No pagination control for page %s; last page reached.", next_page_number)
                break

            first_before = page_numbers[0]
            try:
                next_control.first.click(timeout=8000)
                page.wait_for_timeout(1200)

                # Verify that pagination actually changed the result set.
                new_table = get_registry_table(page)
                new_rows = registry_rows(new_table)
                new_first = new_rows[0][1] if new_rows else None

                if not new_rows or new_first == first_before:
                    log.warning(
                        "Pagination control did not change the records; trying page URL."
                    )
                    fallback_url = f"{BASE_URL}?page={page_number + 1}&type_std={TYPE_STD}"
                    page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                    page.locator("table").first.wait_for(state="visible", timeout=20000)
                    page.wait_for_timeout(1000)
                    check_rows = registry_rows(get_registry_table(page))
                    if not check_rows or check_rows[0][1] == first_before:
                        log.error("Could not advance to page %s; stopping.", page_number + 1)
                        break

            except Exception as exc:
                log.error("Could not navigate to page %s: %s", page_number + 1, exc)
                break

        context.close()
        browser.close()
    # JSON is the complete, nested output.
    json_path = out_dir / "records.json"
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    # Flat CSV: list fields plus all detail fields in separate columns.
    detail_keys = sorted({key for rec in records for key in (rec.get("details") or {}).keys()})
    columns = [
        "registry_number", "organization_name", "accreditation_date_list",
        "status_list", "source_page", "pdf_count",
    ] + detail_keys

    with (out_dir / "organizations.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            flat = dict(rec)
            flat.update(rec.get("details") or {})
            writer.writerow(flat)

    # Separate document inventory, including failed downloads.
    with (out_dir / "documents.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "registry_number", "organization_name", "document_label",
                "document_url", "downloaded_file", "download_status",
                "file_size_bytes", "download_error",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for rec in records:
            for doc in rec.get("documents", []):
                writer.writerow({
                    "registry_number": rec["registry_number"],
                    "organization_name": rec["organization_name"],
                    **doc,
                })

    log.info("Finished. Organizations: %s", len(records))
    log.info("JSON: %s", json_path.resolve())
    log.info("CSV: %s", (out_dir / "organizations.csv").resolve())
    log.info("PDF folder: %s", pdf_dir.resolve())


if __name__ == "__main__":
    main()
