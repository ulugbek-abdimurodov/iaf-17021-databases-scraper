#!/usr/bin/env python3
"""Scrape PCA's (Polskie Centrum Akredytacji) management-system certification bodies.

Source:
https://www.pca.gov.pl/en/accredited-organizations/accredited-organizations/management-systems-certification-bodies

Setup:  pip install requests beautifulsoup4 openpyxl pdfplumber
        (openpyxl and pdfplumber are optional; without them, the Excel file and
        PDF text extraction are skipped.)
Run:    python pca_scraper.py
        python pca_scraper.py --out data --delay 2 --only "AC 014" "AC 019"

Output (default folder: pca_ac_bodies/):
    bodies.json   everything, nested, one object per certification body
    bodies.csv    one row per body
    scopes.csv    one row per body + program scheme
    pca_ac_bodies.xlsx   the two tables above as sheets
    documents.csv one row per downloaded document, with size and SHA-256
    pdfs/         the scope-of-accreditation PDFs, e.g. AC_014.pdf
    pdf_text/     the text of those PDFs, for searching
    html/         the raw detail pages, for re-parsing or auditing
    errors.json   anything that failed (only written when something did)

Run it again to resume: existing PDFs are kept unless --force is given.

How the site works: the list is not in the page's HTML. A Vue component POSTs the
filter form to <section>/search-form.html, with the CSRF token from the page's meta
tag, and gets JSON back. An empty form returns every body. Detail pages are plain
HTML. Their PDF links are dated paths that can change, so they are read fresh on
each run and never reused from an earlier one.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SITE = "https://www.pca.gov.pl"
SECTION = "/en/accredited-organizations/accredited-organizations/management-systems-certification-bodies"
SYMBOL = "AC"  # PCA's prefix for management-system certification bodies
USER_AGENT = "Mozilla/5.0 (compatible; pca-scraper/1.0)"
TIMEOUT = 60
DOCUMENT_RE = re.compile(r"\.(pdf|docx?|xlsx?|zip)$", re.I)

CONTACT_FIELDS = {
    "telephone": "phone",
    "telefon komórkowy": "mobile",
    "fax": "fax",
    "e-mail": "email",
    "www": "website",
}
HEADER_FIELDS = {
    "accreditation number": "accreditation_number",
    "accreditation validity date": "valid_until",
    "date of granting the accreditation": "granted_on",
}
BODY_COLUMNS = [
    "accreditation_number", "organization", "organization_address", "certification_body",
    "certification_body_address", "street", "postal_code", "city", "granted_on", "valid_until",
    "phone", "phone_internal", "mobile", "fax", "email", "website", "scheme_count", "schemes",
    "pdf_issue_no", "pdf_issue_date", "pdf_pages", "pdf_file", "pdf_url", "detail_url",
]
SCOPE_COLUMNS = ["accreditation_number", "organization", "scheme", "standard", "flagged_suspended", "raw_text"]
DOCUMENT_COLUMNS = ["accreditation_number", "file", "url", "bytes", "sha256", "status"]


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def iso_date(value: str) -> str:
    """Turn the site's DD-MM-YYYY into YYYY-MM-DD; leave anything else as found."""
    try:
        return datetime.strptime(value, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return value


def split_address(address: str) -> dict:
    match = re.match(r"^(.*?);?\s*(\d{2}-\d{3})\s+(.+)$", address)
    if not match:
        return {"street": address, "postal_code": "", "city": ""}
    return {"street": match[1].strip(" ;"), "postal_code": match[2], "city": match[3].strip()}


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=None, respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def fetch_list(session: requests.Session, site: str) -> list[dict]:
    """Return every body from the site's search endpoint, checked against its total."""
    page_url = site + SECTION
    response = session.get(page_url, timeout=TIMEOUT)
    response.raise_for_status()
    meta = BeautifulSoup(response.text, "html.parser").find("meta", attrs={"name": "csrf-token"})
    if not meta or not meta.get("content"):
        raise RuntimeError("No csrf-token meta tag on the list page; the site may have changed.")
    token = meta["content"]

    form = {"_token": token, "symbol": SYMBOL, "accreditation": "", "entity": "",
            "organization": "", "city": "", "voivodeship": "0"}
    response = session.post(
        f"{page_url}/search-form.html",
        files=[(key, (None, value)) for key, value in form.items()],  # multipart, as the browser sends
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                 "X-CSRF-Token": token, "Referer": page_url},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"Unexpected search response: {str(data)[:300]}")
    if data.get("total") != len(results):
        raise RuntimeError(f"Search reported {data.get('total')} records but returned {len(results)}.")
    return results


def parse_detail(html: str, base_url: str) -> dict:
    """Parse a detail page. Raises ValueError if the expected layout is missing."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    if not main.select_one(".accreditation"):
        raise ValueError("no .accreditation block on the page")
    body: dict = {}

    for p in main.select(".a-text-logo p"):
        label_tag = p.find("strong")
        if label_tag:
            label = clean(label_tag.get_text()).rstrip(":").lower()
            label_tag.extract()
            if label in HEADER_FIELDS:
                body[HEADER_FIELDS[label]] = clean(p.get_text())

    for selector, name_key, address_key in (
        (".data-organization", "organization", "organization_address"),
        (".dane-lab", "certification_body", "certification_body_address"),
    ):
        lines = [clean(p.get_text()) for p in main.select(f"{selector} p")]
        body[name_key] = lines[0] if lines else ""
        body[address_key] = lines[1] if len(lines) > 1 else ""

    for field in list(CONTACT_FIELDS.values()) + ["phone_internal"]:
        body[field] = ""
    for label_tag in main.select(".a-contact i"):
        field = CONTACT_FIELDS.get(clean(label_tag.get_text()).rstrip(":").lower())
        holder = label_tag.find_parent("p")
        if not field or holder is None:
            continue
        value = clean(holder.get_text().replace(label_tag.get_text(), "", 1))
        if field == "phone":
            value, _, internal = value.partition("internal:")
            body["phone_internal"] = internal.strip()
            value = value.strip()
        body[field] = value

    scopes = []
    for li in main.select(".a-right-column li"):
        raw = clean(li.get_text(" "))
        standard_tag = li.find("i")
        standard = ""
        if standard_tag:
            standard = clean(standard_tag.get_text()).strip("[]").strip()
            standard_tag.extract()
        scopes.append({
            "scheme": clean(li.get_text(" ")),
            "standard": standard,
            "flagged_suspended": bool(re.search(r"zawiesz|suspend", raw, re.I)),
            "raw_text": raw,
        })
    body["scopes"] = scopes

    # Take every document linked from the page, so any annex added later is included too.
    documents, seen = [], set()
    for link in main.select("a[href]"):
        url = urljoin(base_url, link["href"])
        if DOCUMENT_RE.search(urlparse(url).path) and url not in seen:
            seen.add(url)
            documents.append({"url": url, "label": clean(link.get_text())})
    body["documents"] = documents
    return body


def safe_filename(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._") or "document.pdf"


def download(session: requests.Session, url: str, target: Path, force: bool) -> str:
    if target.exists() and target.stat().st_size and not force:
        return "kept"
    temp = target.with_name(target.name + ".part")
    with session.get(url, timeout=TIMEOUT, stream=True) as response:
        response.raise_for_status()
        with temp.open("wb") as handle:
            for chunk in response.iter_content(65536):
                handle.write(chunk)
    with temp.open("rb") as handle:
        start = handle.read(5)
    if target.suffix.lower() == ".pdf" and start != b"%PDF-":
        temp.unlink()
        raise ValueError("response is not a PDF")
    temp.replace(target)
    return "downloaded"


def read_pdf(path: Path, text_dir: Path) -> dict:
    """Extract text, page count and issue number/date. Skipped if pdfplumber is missing."""
    try:
        import pdfplumber
    except ImportError:
        return {}
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n\n".join(pages)
    text_dir.mkdir(exist_ok=True)
    (text_dir / (path.stem + ".txt")).write_text(text, encoding="utf-8")
    issue = re.search(r"Wydanie\s*/\s*Issue\s+(\S+)\s+z\s*/\s*of\s+([\d.]+\d)", text)
    return {
        "pdf_pages": len(pages),
        "pdf_issue_no": issue[1] if issue else "",
        "pdf_issue_date": issue[2] if issue else "",
        "pdf_has_text": bool(text.strip()),
    }


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:  # BOM so Excel reads Polish letters
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, bodies: list[dict], scopes: list[dict]) -> bool:
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    workbook = Workbook()
    for index, (title, rows, columns) in enumerate(
        (("Bodies", bodies, BODY_COLUMNS), ("Scopes", scopes, SCOPE_COLUMNS))
    ):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = title
        sheet.append(columns)
        for row in rows:
            sheet.append([row.get(column, "") for column in columns])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cells in sheet.columns:
            width = max((len(str(cell.value or "")) for cell in cells), default=10)
            sheet.column_dimensions[cells[0].column_letter].width = min(width + 2, 60)
    workbook.save(path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="pca_ac_bodies", help="output folder")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--only", nargs="+", metavar="NUMBER", help='only these bodies, e.g. "AC 014"')
    parser.add_argument("--no-pdf", action="store_true", help="skip document downloads")
    parser.add_argument("--force", action="store_true", help="download documents again even if present")
    parser.add_argument("--site", default=SITE, help=argparse.SUPPRESS)  # for local testing
    args = parser.parse_args()

    out = Path(args.out)
    for folder in (out, out / "pdfs", out / "html"):
        folder.mkdir(parents=True, exist_ok=True)

    session = make_session()
    listing = fetch_list(session, args.site.rstrip("/"))
    print(f"The site lists {len(listing)} bodies.")
    if args.only:
        wanted = {clean(number).upper() for number in args.only}
        listing = [item for item in listing if clean(item.get("number")).upper() in wanted]
        print(f"Keeping {len(listing)} from --only.")

    bodies, scope_rows, document_rows, errors = [], [], [], []
    for position, item in enumerate(listing, 1):
        number = clean(item.get("number"))
        print(f"[{position}/{len(listing)}] {number} {clean(item.get('organization'))}")
        url = urljoin(args.site.rstrip("/") + "/", item["url"])
        body = {"accreditation_number": number, "organization": clean(item.get("organization")),
                "certification_body": clean(item.get("entity")),
                "organization_address": clean(item.get("address")), "detail_url": url,
                "scopes": [], "documents": []}
        try:
            time.sleep(args.delay)
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            stem = re.sub(r"\W+", "_", number)
            (out / "html" / f"{stem}.html").write_text(response.text, encoding="utf-8")
            parsed = parse_detail(response.text, url)
            if parsed.get("accreditation_number", number) != number:
                raise ValueError(f"page shows {parsed['accreditation_number']}, expected {number}")
            body.update({key: value for key, value in parsed.items() if value not in ("", None)})
        except (requests.RequestException, ValueError) as error:
            print(f"    FAILED detail page: {error}", file=sys.stderr)
            errors.append({"number": number, "step": "detail", "url": url, "error": str(error)})

        for field in ("granted_on", "valid_until"):
            if body.get(field):
                body[field] = iso_date(body[field])
        body.update(split_address(body.get("certification_body_address") or body["organization_address"]))
        body["scheme_count"] = len(body["scopes"])
        body["schemes"] = "; ".join(scope["standard"] or scope["scheme"] for scope in body["scopes"])
        for scope in body["scopes"]:
            scope_rows.append({"accreditation_number": number, "organization": body["organization"], **scope})

        for document in body["documents"] if not args.no_pdf else []:
            target = out / "pdfs" / safe_filename(document["url"])
            row = {"accreditation_number": number, "url": document["url"], "file": str(target.relative_to(out))}
            try:
                time.sleep(args.delay)
                row["status"] = download(session, document["url"], target, args.force)
                data = target.read_bytes()
                row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                if target.suffix.lower() == ".pdf":
                    body.setdefault("pdf_file", row["file"])
                    body.setdefault("pdf_url", row["url"])
                    try:
                        info = read_pdf(target, out / "pdf_text")
                        for key, value in info.items():
                            body.setdefault(key, value)
                    except Exception as error:  # a bad PDF must not lose the download
                        errors.append({"number": number, "step": "pdf_text", "url": row["url"], "error": str(error)})
            except (requests.RequestException, ValueError, OSError) as error:
                print(f"    FAILED document: {error}", file=sys.stderr)
                row["status"] = "failed"
                errors.append({"number": number, "step": "document", "url": document["url"], "error": str(error)})
            document_rows.append(row)
        if not body["documents"] and not any(e["number"] == number for e in errors):
            errors.append({"number": number, "step": "document", "url": url, "error": "no document link on the page"})
        bodies.append(body)

    output = {"source": args.site.rstrip("/") + SECTION,
              "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "count": len(bodies), "bodies": bodies}
    (out / "bodies.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "bodies.csv", bodies, BODY_COLUMNS)
    write_csv(out / "scopes.csv", scope_rows, SCOPE_COLUMNS)
    write_csv(out / "documents.csv", document_rows, DOCUMENT_COLUMNS)
    made_xlsx = write_xlsx(out / "pca_ac_bodies.xlsx", bodies, scope_rows)

    errors_path = out / "errors.json"
    if errors:
        errors_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
    elif errors_path.exists():
        errors_path.unlink()

    print(f"\nDone: {len(bodies)} bodies, {len(scope_rows)} schemes, {len(document_rows)} documents -> {out.resolve()}")
    if not made_xlsx:
        print("Excel file skipped: pip install openpyxl")
    if errors:
        print(f"{len(errors)} problem(s), see {errors_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
