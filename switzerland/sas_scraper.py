#!/usr/bin/env python3
"""Scrape Swiss Accreditation Service (SAS) accredited bodies.

Defaults to SCESm (certification bodies for management systems). For each body
it saves the API record, every published PDF directory in every language (the
document that holds the accreditation details and scope annex), the extracted
text, and the fields parsed from the PDF. It also saves SECO's lists of
suspended and withdrawn accreditations.

Setup:  pip install pypdf     (optional: without it, PDFs are saved but not parsed)
Usage:  python sas_scraper.py                     # SCESm into ./sas_data
        python sas_scraper.py --types SCESm SCESp
        python sas_scraper.py --types all --out data --delay 1

Re-runs are incremental: unchanged PDFs are not downloaded again.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://sas.seco.amboss.liip.cloud"
SECO_PAGE = "https://www.seco.admin.ch/en/search-accredited-bodies-sas"
USER_AGENT = "sas-accredited-bodies-scraper/1.0"
LANGUAGE_PREFERENCE = ("en", "de", "fr", "it")
PAGE_SIZE = 100

D = r"(\d{2}\.\d{2}\.\d{4})"
LABELS = {
    "head": r"Head|Leiter(?:in|/in)?|Leitung|Responsable|Directeur|Directrice|Direttore|Direttrice|Responsabile",
    "ms_responsible": r"Responsible for MS|Responsible MS|MS-Verantwortliche(?:r|/r)?|Responsable SM|Responsabile SM",
    "phone": r"Telephone|Telefon|Téléphone|Telefono",
    "email": r"E-?Mail",
    "website": r"Internet",
}
INITIAL_RE = re.compile(
    rf"(?:Initial accreditation|Erstmals akkreditiert|Première accréditation|Primo accreditamento)\s*:\s*{D}"
)
CURRENT_RE = re.compile(
    rf"(?:Current accreditation|Aktuelle Akkreditierung|Accréditation actuelle|Accreditamento attuale)"
    rf"\s*:\s*{D}\s+(?:to|bis|au|al)\s+{D}"
)
SCOPE_DATE_RE = re.compile(
    rf"(?:Scope of accreditation as (?:of|from)|Geltungsbereich der Akkreditierung ab|"
    rf"Portée de l.accréditation dès(?: le)?|Campo d.applicazione dell.accreditamento a partire dal)\s+{D}"
)
TABLE_HEADER_RE = re.compile(r"^(Standards?|Normen?|Normes?|Norma|Norme)\s")
DOC_LINE_RE = re.compile(rf"^{D}\s*/\s*(.+?)\s+(de|fr|it|en)(?:\.docx?)?\s+\d+/\d+\s*$", re.M)
ACCREDITATION_RE = re.compile(r"\b(S[A-Z]+[a-z]?)\s+(\d{4})\b")
NATIONAL_STD_RE = re.compile(
    r"^(?:Swiss standard|Schweizer Norm|Norme suisse|Norma svizzera)\s*:.*$", re.M
)
ISO_RE = re.compile(r"\bISO(?:/(?:IEC|CEI|TS))?\s+\d+(?:-\d+)?(?::\d{4})?")


def field(text: str, label_pattern: str) -> str:
    match = re.search(rf"^(?:{label_pattern})\s*:\s*(.+?)\s*$", text, re.M)
    return match.group(1) if match else ""


def parse_directory(text: str) -> dict:
    """Parse the header of a directory PDF. Works for all four languages."""
    out = {name: field(text, pattern) for name, pattern in LABELS.items()}
    doc = DOC_LINE_RE.search(text)
    out["document_date"], out["document_ref"] = (doc.group(1), doc.group(2)) if doc else ("", "")

    initial = INITIAL_RE.search(text)
    current = CURRENT_RE.search(text)
    scope = SCOPE_DATE_RE.search(text)
    out["initial_accreditation"] = initial.group(1) if initial else ""
    out["accreditation_from"] = current.group(1) if current else ""
    out["accreditation_to"] = current.group(2) if current else ""
    out["scope_as_of"] = scope.group(1) if scope else ""

    # Address block: from the line after the national standard to the first label.
    national = NATIONAL_STD_RE.search(text)
    head = re.search(rf"^(?:{LABELS['head']})\s*:", text, re.M)
    out["address_block"] = (
        " | ".join(l.strip() for l in text[national.end():head.start()].splitlines() if l.strip())
        if national and head else ""
    )

    # Scope description: from the scope date to the table header.
    description = []
    if scope:
        for line in text[scope.end():].splitlines():
            if TABLE_HEADER_RE.match(line):
                break
            if line.strip():
                description.append(line.strip())
    out["scope_description"] = " ".join(description)
    # The ISO/IEC 17021-1 accreditation standard is in the header, so skip it.
    body = text[scope.end():] if scope else text
    out["iso_standards_in_scope"] = sorted({re.sub(r"\s+", " ", m) for m in ISO_RE.findall(body)})
    return out


class Client:
    def __init__(self, delay: float):
        self.delay = delay

    def get(self, url: str, headers: dict | None = None, retries: int = 3):
        """Return (body, response headers), or (None, {}) on 304."""
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        for attempt in range(retries + 1):
            time.sleep(self.delay)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read(), response.headers
            except urllib.error.HTTPError as error:
                if error.code == 304:
                    return None, {}
                if error.code not in (429, 500, 502, 503, 504) or attempt == retries:
                    raise
            except urllib.error.URLError:
                if attempt == retries:
                    raise
            time.sleep(2 ** attempt)
        raise RuntimeError(f"unreachable: {url}")

    def get_json(self, path: str, **params):
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        body, _ = self.get(f"{BASE_URL}/api/v1/{path}{query}")
        return json.loads(body)


def fetch_bodies(client: Client, type_id: int) -> list[dict]:
    results, page = [], 1
    while True:
        data = client.get_json("search/", type=type_id, page=page, page_size=PAGE_SIZE)
        results.extend(data["results"])
        if page >= data["num_pages"]:
            break
        page += 1
    if len(results) != data["count"]:
        raise RuntimeError(f"type {type_id}: API said {data['count']} but returned {len(results)}")
    return results


def pdf_to_text(data_path: Path) -> tuple[str, int] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(str(data_path))
    return "\n\f\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def download_pdf(client: Client, url: str, target: Path, known: dict) -> dict:
    """Download one PDF, sending If-Modified-Since when we already have the file."""
    headers = {}
    previous = known.get(target.name)
    if previous and target.exists() and previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]
    body, response_headers = client.get(url, headers)
    if body is None:
        return {**previous, "status": "unchanged"}
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {
        "file": target.name,
        "url": url,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "last_modified": response_headers.get("Last-Modified", ""),
        "status": "downloaded",
    }


def fetch_status_lists(client: Client, out: Path) -> list[dict]:
    """Save the suspended and withdrawn lists linked from the SECO page."""
    saved = []
    html, _ = client.get(SECO_PAGE)
    links = set(re.findall(r'[^"\'\s]*/dam/[^"\'\s]+?\.pdf', html.decode("utf-8", "replace")))
    for link in sorted(links):
        url = urllib.parse.urljoin(SECO_PAGE, link.replace("\\u002F", "/"))
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if not re.search(r"SUSPENDIERTE|AUFGEHOBENE", name, re.I):
            continue
        body, _ = client.get(url)
        target = out / "status_lists" / re.sub(r"[^\w.\- ]", "_", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        saved.append({"file": target.name, "url": url, "bytes": len(body)})
    return saved


def write_csv(path: Path, rows: list[dict]) -> None:
    columns: list[str] = []
    for row in rows:
        columns.extend(key for key in row if key not in columns)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in row.items()})


def scrape_type(client: Client, acc_type: dict, out: Path) -> dict:
    code = acc_type["type"]
    root = out / code
    manifest_path = root / "documents.json"
    known = {}
    if manifest_path.exists():
        known = {d["file"]: d for d in json.loads(manifest_path.read_text("utf-8"))}

    bodies, documents, errors = [], [], []
    records = fetch_bodies(client, acc_type["id"])
    print(f"{code}: {len(records)} bodies")
    for record in records:
        body = {
            "accreditation_id": record["accreditation_id"],
            "accreditation_type": code,
            "accreditation_type_name": acc_type["name"],
            "company_name": " ".join(record["company_name"].split()),
            "street_address": record["street_address"],
            "postal_code": record["postal_code"],
            "locality": record["locality"],
            "languages": [],
        }
        parsed_by_language = {}
        for language, relative_url in record["pdf_urls"].items():
            if not relative_url:
                continue
            url = urllib.parse.urljoin(BASE_URL, relative_url)
            target = root / "pdf" / relative_url.rsplit("/", 1)[-1]
            try:
                document = download_pdf(client, url, target, known)
            except Exception as error:  # keep going so one bad file doesn't lose the rest
                errors.append(f"{url}: {error}")
                print(f"  ERROR {url}: {error}", file=sys.stderr)
                continue
            document.update(accreditation_id=record["accreditation_id"], language=language)
            body["languages"].append(language)

            extracted = pdf_to_text(target)
            if extracted:
                text, document["pages"] = extracted
                text_path = root / "text" / f"{target.stem}.txt"
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.write_text(text, "utf-8")
                parsed_by_language[language] = parse_directory(text)
            documents.append(document)
            print(f"  {target.name}: {document['status']}")

        for language in LANGUAGE_PREFERENCE:
            if language in parsed_by_language:
                body["parsed_from_language"] = language
                body.update(parsed_by_language[language])
                break
        body["raw_api_record"] = record
        bodies.append(body)

    root.mkdir(parents=True, exist_ok=True)
    (root / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False, indent=2), "utf-8")
    manifest_path.write_text(json.dumps(documents, ensure_ascii=False, indent=2), "utf-8")
    write_csv(root / "bodies.csv", [{k: v for k, v in b.items() if k != "raw_api_record"} for b in bodies])
    write_csv(root / "documents.csv", documents)
    return {"type": code, "bodies": len(bodies), "documents": len(documents), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--types", nargs="+", default=["SCESm"], help="type codes such as SCESm SCESp, or 'all'")
    parser.add_argument("--out", type=Path, default=Path("sas_data"))
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--skip-status-lists", action="store_true")
    args = parser.parse_args()

    client = Client(args.delay)
    available = {t["type"].lower(): t for t in client.get_json("accreditation-types/")}
    wanted = list(available) if args.types == ["all"] else [t.lower() for t in args.types]
    unknown = [t for t in wanted if t not in available]
    if unknown:
        parser.error(f"unknown types {unknown}; available: {[t['type'] for t in available.values()]}")

    summary = {"scraped_at": datetime.now(timezone.utc).isoformat(), "source": BASE_URL, "types": []}
    for code in wanted:
        summary["types"].append(scrape_type(client, available[code], args.out))
    if not args.skip_status_lists:
        try:
            summary["status_lists"] = fetch_status_lists(client, args.out)
        except Exception as error:
            summary["status_lists_error"] = str(error)
            print(f"Could not fetch status lists: {error}", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    failed = sum(len(t["errors"]) for t in summary["types"])
    print(f"Done: {args.out.resolve()} ({failed} failed downloads)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
