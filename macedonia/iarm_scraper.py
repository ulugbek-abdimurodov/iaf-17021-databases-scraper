#!/usr/bin/env python3
"""Download management-system certification body data from iarm.gov.mk.

Collects, in English, Macedonian and Albanian:
  * each body's published details (certificate no., address, scope, dates)
  * the current annex to its accreditation certificate
  * earlier annex versions still held in the site's media library

Setup:  pip install requests beautifulsoup4 pdfplumber
Run:    python iarm_scraper.py
        python iarm_scraper.py --include-withdrawn --out my_folder

Re-running skips files that were already downloaded. pdfplumber is optional;
with it, each PDF also gets a .txt file of its extracted text.
"""
import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

BASE_URL = "https://iarm.gov.mk"
CATEGORY_SLUGS = {
    "en": "cb_management",
    "mk": "st_upravuvanje",
    "sq": "organe-certifikuese-per-sistemet-e-menaxhimit",
}
WITHDRAWN_SLUG = "withdrawn_acc"
ANNEX_FORM_CODE = "OB-05-23"  # the institute's form code for these annexes

# Names used in annex filenames that don't contain the certificate number.
BODY_ALIASES = {
    5: ["MQS", "MKS", "МКС"],
    6: ["MKD", "МКД"],
    9: ["Intercert", "Интерцерт"],
}

FIELD_LABELS = {
    "certificate_no": [
        "Accreditation Certificate No.",
        "Сертификат за акредитација број",
        "Сertifikatë për akreditim me numër",
    ],
    "accredited_body": ["Accredited Body", "Акредитирано тело", "Organ i akredituar"],
    "address": ["Address", "Адреса", "Adresë"],
    "scope": [
        "Short description of the scope",
        "Краток опис на опсегот на акредитација",
        "Përshkrim i shkurtër i fushës së akreditimit",
    ],
    "first_accreditation": ["First accreditation", "Прва акредитација", "Akreditimi i parë"],
    "valid_until": [
        "Certificate valid until",
        "Дата на важност на сертификатот",
        "Data e vlefshmërisë së certifikatës",
    ],
}
LABEL_TO_FIELD = {
    label.casefold(): field for field, labels in FIELD_LABELS.items() for label in labels
}

CERT_NO_RE = re.compile(r"\b(?:CB|ST|CT|СТ|ЦТ)\s*[-–—]\s*(\d{1,3})\b", re.I)
STANDARD_RE = re.compile(r"^(?:МКС|MKS|MKC|ISO|EN|IEC)\b", re.I)
WEBSITE_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
WITHDRAWN_RE = re.compile(r"withdrawn on (\d{2}\.\d{2}\.\d{4})\s*(?:\(([^)]*)\))?", re.I)


def log(message):
    print(message, flush=True)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def iso_date(value):
    try:
        return datetime.strptime(clean(value), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return ""


def safe_name(name, limit=120):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "-", name.strip()).strip(".-")
    return name[:limit] or "unnamed"


def file_name_from_url(url):
    return safe_name(unquote(urlparse(url).path.rsplit("/", 1)[-1]))


def upload_month(url):
    match = re.search(r"/uploads/(\d{4})/(\d{2})/", unquote(url))
    return f"{match.group(1)}-{match.group(2)}" if match else "undated"


class Client:
    def __init__(self, base_url, delay):
        self.base_url = base_url.rstrip("/")
        self.host = urlparse(self.base_url).netloc
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "iarm-cb-scraper/1.0"
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def get(self, url, **kwargs):
        time.sleep(self.delay)
        response = self.session.get(url, timeout=60, **kwargs)
        response.raise_for_status()
        return response

    def api(self, endpoint, **params):
        """Return every item from a paginated WordPress REST endpoint."""
        url = f"{self.base_url}/wp-json/wp/v2/{endpoint}"
        items, page = [], 1
        while True:
            response = self.get(url, params={**params, "per_page": 100, "page": page})
            items.extend(response.json())
            if page >= int(response.headers.get("X-WP-TotalPages", 1)):
                return items
            page += 1

    def category_posts(self, slug):
        categories = self.api("categories", slug=slug)
        if not categories:
            raise RuntimeError(f"Category not found on the site: {slug}")
        return self.api("posts", categories=categories[0]["id"])


def cell_lines(cell):
    return [clean(line) for line in cell.get_text("\n", strip=True).split("\n") if clean(line)]


def parse_scope(lines):
    """Turn alternating standard/description lines into structured entries."""
    entries = []
    for line in lines:
        if STANDARD_RE.match(line) or not entries:
            entries.append({"standard": line, "description": ""})
        else:
            current = entries[-1]
            current["description"] = clean(f'{current["description"]} {line}')
    return entries


def parse_post(post, base_host):
    """Extract the structured details from one WordPress post."""
    soup = BeautifulSoup(post["content"]["rendered"], "html.parser")
    title = clean(html.unescape(post["title"]["rendered"]))
    fields, other_fields = {}, {}
    table = soup.find("table")
    if table:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label, lines = clean(cells[0].get_text()), cell_lines(cells[1])
            field = LABEL_TO_FIELD.get(label.casefold())
            if field:
                fields[field] = lines
            else:
                other_fields[label] = "\n".join(lines)

    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        links.append({"text": clean(anchor.get_text()), "url": href})
    documents = [
        link for link in links
        if "/wp-content/uploads/" in link["url"] and urlparse(link["url"]).netloc == base_host
    ]

    address, websites = [], []
    for line in fields.get("address", []):
        (websites if WEBSITE_RE.match(line) else address).append(line)

    if table:
        table.extract()
    intro = "\n".join(cell_lines(soup))
    first = " ".join(fields.get("first_accreditation", []))
    until = " ".join(fields.get("valid_until", []))
    certificate_no = " ".join(fields.get("certificate_no", []))
    number_match = CERT_NO_RE.search(certificate_no) or CERT_NO_RE.search(title)
    withdrawn = WITHDRAWN_RE.search(intro)

    return {
        "number": int(number_match.group(1)) if number_match else None,
        "post_id": post["id"],
        "title": title,
        "url": post.get("link", ""),
        "published": post.get("date", ""),
        "modified": post.get("modified", ""),
        "intro": intro,
        "certificate_no": certificate_no,
        "accredited_body": " ".join(fields.get("accredited_body", [])),
        "address": address,
        "websites": websites,
        "scope": parse_scope(fields.get("scope", [])),
        "first_accreditation": first,
        "first_accreditation_iso": iso_date(first),
        "valid_until": until,
        "valid_until_iso": iso_date(until),
        "withdrawn_on": iso_date(withdrawn.group(1)) if withdrawn else "",
        "withdrawn_reason": clean(withdrawn.group(2)) if withdrawn else "",
        "other_fields": other_fields,
        "links": links,
        "documents": documents,
    }


def collect_bodies(client, include_withdrawn, raw_dir):
    bodies = {}
    for lang, slug in CATEGORY_SLUGS.items():
        posts = client.category_posts(slug)
        log(f"[{lang}] {len(posts)} bodies")
        for post in posts:
            add_post(bodies, client, post, lang, "active", raw_dir)

    if include_withdrawn:
        posts = client.category_posts(WITHDRAWN_SLUG)
        matches = [
            post for post in posts
            if clean(html.unescape(post["title"]["rendered"])).upper().startswith("CB")
        ]
        log(f"[withdrawn] {len(matches)} CB-numbered entries out of {len(posts)}")
        for post in matches:
            add_post(bodies, client, post, "en", "withdrawn", raw_dir)
    return bodies


def add_post(bodies, client, post, lang, status, raw_dir):
    parsed = parse_post(post, client.host)
    number = parsed["number"]
    if number is None:
        log(f"  WARNING: no certificate number found in post {post['id']}: {parsed['title']}")
        return
    if status == "active" and not parsed["certificate_no"]:
        log(f"  WARNING: details table not recognised in post {post['id']}: {parsed['title']}")
    body = bodies.setdefault(
        number,
        {"number": number, "certificate_key": f"CB-{number:03d}", "status": status, "translations": {}},
    )
    body["translations"][lang] = parsed
    raw_path = raw_dir / lang / f'{body["certificate_key"]}_{post["id"]}.json'
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")


def filename_matches_body(file_name, number):
    pattern = rf"(?<![A-Za-z0-9])(?:ST|CT|CB|СТ|ЦТ)[-_ ]?{number:03d}(?!\d)"
    if re.search(pattern, file_name, re.I):
        return True
    if ANNEX_FORM_CODE.casefold() not in file_name.casefold():
        return False
    return any(alias.casefold() in file_name.casefold() for alias in BODY_ALIASES.get(number, []))


def collect_documents(client, bodies, include_history):
    """Build the document list: linked annexes first, then media-library history."""
    documents = {}

    def add(url, number, kind, **extra):
        doc = documents.setdefault(url, {
            "url": url,
            "number": number,
            "kind": kind,
            "file_name": file_name_from_url(url),
            "link_text": "",
            "media_id": "",
            "media_date": "",
        })
        doc.update({key: value for key, value in extra.items() if value})
        return doc

    for number, body in bodies.items():
        kind = "current_annex" if body["status"] == "active" else "withdrawn_annex"
        for parsed in body["translations"].values():
            for link in parsed["documents"]:
                add(link["url"], number, kind, link_text=link["text"])

    if not include_history:
        return list(documents.values())

    searches = {ANNEX_FORM_CODE}
    for number in bodies:
        searches.update({f"ST-{number:03d}", f"ST_{number:03d}", f"CB-{number:03d}"})
        searches.update(BODY_ALIASES.get(number, []))

    media = {}
    for term in sorted(searches):
        for item in client.api("media", search=term):
            if not item.get("mime_type", "").startswith("image/"):
                media[item["source_url"]] = item
    log(f"Media library: {len(media)} candidate files")

    for url, item in media.items():
        name = file_name_from_url(url)
        number = next((n for n in sorted(bodies) if filename_matches_body(name, n)), None)
        if number is not None:
            kind = "historical_annex"
        elif ANNEX_FORM_CODE.casefold() in name.casefold():
            kind = "unassigned_annex"
        else:
            continue
        add(url, number, kind, media_id=item.get("id"), media_date=item.get("date"))
    return list(documents.values())


def body_folder(body):
    translations = body["translations"]
    title = next((translations[lang]["title"] for lang in ("en", "mk", "sq") if lang in translations), "")
    name = CERT_NO_RE.sub("", title, count=1)
    name = re.sub(r"[\s\-–—]+", "-", name).strip("-")
    return safe_name(f'{body["certificate_key"]}_{name}', limit=80)


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_text(pdf_path):
    if pdfplumber is None:
        return "not_attempted"
    txt_path = pdf_path.with_suffix(".txt")
    if txt_path.exists():
        return "extracted" if txt_path.stat().st_size else "no_text_layer"
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as error:
        log(f"  Could not read text from {pdf_path.name}: {error}")
        return "failed"
    text = "\n\n".join(pages).strip()
    txt_path.write_text(text, encoding="utf-8")
    return "extracted" if text else "no_text_layer"


def download_documents(client, documents, bodies, out_dir):
    root = out_dir / "documents"
    for doc in documents:
        number = doc["number"]
        folder = root / (body_folder(bodies[number]) if number in bodies else "_unassigned")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{upload_month(doc["url"])}_{doc["file_name"]}'
        doc["local_path"] = target.relative_to(out_dir).as_posix()
        doc["text_status"] = ""

        if urlparse(doc["url"]).netloc != client.host:
            doc.update(status="skipped_other_host", bytes="", sha256="")
            log(f"  Skipped, not on {client.host}: {doc['url']}")
            continue

        if target.exists():
            doc["status"] = "already_downloaded"
        else:
            temp = target.with_name(target.name + ".part")
            try:
                with client.get(doc["url"], stream=True) as response:
                    if "html" in response.headers.get("Content-Type", "").lower():
                        raise ValueError("server returned a web page instead of a file")
                    with temp.open("wb") as handle:
                        for block in response.iter_content(1024 * 256):
                            handle.write(block)
                temp.replace(target)
                doc["status"] = "downloaded"
                log(f"  Downloaded {doc['local_path']}")
            except (requests.RequestException, ValueError, OSError) as error:
                temp.unlink(missing_ok=True)
                doc.update(status=f"failed: {error}", bytes="", sha256="")
                log(f"  FAILED {doc['url']}: {error}")
                continue
        doc["bytes"] = target.stat().st_size
        doc["sha256"] = sha256_of(target)
        if target.suffix.lower() == ".pdf":
            doc["text_status"] = extract_text(target)


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(out_dir, bodies, documents):
    ordered = [bodies[number] for number in sorted(bodies)]
    for body in ordered:
        body["documents"] = [doc for doc in documents if doc["number"] == body["number"]]

    payload = {
        "source": BASE_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bodies": ordered,
        "unassigned_documents": [doc for doc in documents if doc["number"] not in bodies],
    }
    (out_dir / "bodies.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    body_rows, scope_rows = [], []
    for body in ordered:
        translations = body["translations"]
        main = translations.get("en") or next(iter(translations.values()))
        body_rows.append({
            "certificate": body["certificate_key"],
            "status": body["status"],
            "name_en": translations.get("en", {}).get("accredited_body", "") or main["title"],
            "name_mk": translations.get("mk", {}).get("accredited_body", ""),
            "name_sq": translations.get("sq", {}).get("accredited_body", ""),
            "address_en": " | ".join(main["address"]),
            "address_mk": " | ".join(translations.get("mk", {}).get("address", [])),
            "website": " | ".join(main["websites"]),
            "standards": " | ".join(entry["standard"] for entry in main["scope"]),
            "first_accreditation": main["first_accreditation_iso"],
            "valid_until": main["valid_until_iso"],
            "withdrawn_on": main["withdrawn_on"],
            "withdrawn_reason": main["withdrawn_reason"],
            "last_modified": main["modified"],
            "documents": len(body["documents"]),
            "page_en": main["url"],
        })
        for lang, parsed in translations.items():
            for entry in parsed["scope"]:
                scope_rows.append({
                    "certificate": body["certificate_key"],
                    "language": lang,
                    "standard": entry["standard"],
                    "description": entry["description"],
                })

    write_csv(out_dir / "bodies.csv", list(body_rows[0]) if body_rows else ["certificate"], body_rows)
    write_csv(out_dir / "scopes.csv", ["certificate", "language", "standard", "description"], scope_rows)

    document_rows = []
    for doc in sorted(documents, key=lambda d: (d["number"] is None, d["number"] or 0, d["url"])):
        number = doc["number"]
        document_rows.append({
            **doc,
            "certificate": f"CB-{number:03d}" if number is not None else "",
        })
    write_csv(
        out_dir / "documents.csv",
        ["certificate", "kind", "file_name", "local_path", "status", "bytes", "sha256",
         "text_status", "media_date", "link_text", "url"],
        document_rows,
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="iarm_cb_management", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--include-withdrawn", action="store_true",
                        help="add withdrawn CB-numbered entries (these may include product CBs)")
    parser.add_argument("--no-history", action="store_true",
                        help="only get annexes linked from the body pages")
    parser.add_argument("--no-download", action="store_true", help="save the data but not the files")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = Client(args.base_url, args.delay)

    bodies = collect_bodies(client, args.include_withdrawn, out_dir / "raw")
    documents = collect_documents(client, bodies, not args.no_history)

    if args.no_download:
        for doc in documents:
            doc.update(status="not_downloaded", local_path="", bytes="", sha256="", text_status="")
    else:
        download_documents(client, documents, bodies, out_dir)
    write_outputs(out_dir, bodies, documents)

    failures = [doc for doc in documents if str(doc["status"]).startswith("failed")]
    log(f"\nDone: {len(bodies)} bodies, {len(documents)} documents, {len(failures)} failed")
    log(f"Results are in: {out_dir.resolve()}")
    if pdfplumber is None and not args.no_download:
        log("Tip: pip install pdfplumber to also extract text from the PDFs.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
