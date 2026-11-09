#!/usr/bin/env python3
"""Download OLAS-accredited management system certification bodies (ISO/IEC 17021-1)
from portail-qualite.public.lu: body details, accreditation certificates, technical
annexes and OLAS's related general documents.

Setup:   pip install requests beautifulsoup4
Run:     python olas_17021_scraper.py [--out olas_17021] [--discover]

Output:
    <out>/bodies.json                  full structured data, including the file manifest
    <out>/bodies.csv                   one row per body
    <out>/bodies/<body>/page.html      the body's page as served
    <out>/bodies/<body>/*.pdf          annexe technique, certificat d'accreditation, ...
    <out>/general_documents/*.pdf      "Pour en savoir plus" documents on the listing page

Robots.txt: the site disallows every URL with a query string, which includes the search
filters and pagination. By default this script obeys robots.txt and reads only the known
body pages below, so it cannot notice a new body, and a renewal that changes a page's URL
shows up as a 404.
--discover is an explicit opt-in that uses the disallowed filter pages to find the current
list of bodies and their activities and domains. Nothing else ignores robots.txt.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://portail-qualite.public.lu"
LISTING_PATH = "/fr/accreditation-notification/organismes-accredites.html"
STANDARD = "ISO/IEC 17021-1"
# Known bodies as of 2026-11-05. The numeric ids in these URLs can change when an
# accreditation is renewed; --discover finds the current ones.
KNOWN_BODY_PATHS = [
    "/fr/accreditation-notification/organismes-accredites/6/20266001.html",  # Certi-trust Europe S.A
    "/fr/accreditation-notification/organismes-accredites/4/20234014.html",  # ESCEM a.s.b.l.
]
USER_AGENT = "olas-17021-scraper/1.0 (python-requests)"
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".ppsx", ".zip")
FIELD_NAMES = {
    "Nom de l'organisme": "name",
    "Numéro d'accréditation": "accreditation_number",
    "Adresse": "address",
    "Accréditation selon les normes": "standards",
    "Validité de l'accréditation": "valid_until",
    "Date d'émission": "issued_on",
}


class RobotsBlocked(Exception):
    pass


class Client:
    def __init__(self, base_url, delay):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.disallow = self._load_robots()

    def _load_robots(self):
        response = self._request(self.base_url + "/robots.txt")
        if response.status_code != 200:
            return []
        rules, agents, in_agent_lines = [], [], False
        for raw in response.text.splitlines():
            match = re.match(r"([A-Za-z-]+)\s*:\s*(.*)", raw.split("#")[0].strip())
            if not match:
                continue
            key, value = match.group(1).lower(), match.group(2).strip()
            if key == "user-agent":
                agents = agents + [value] if in_agent_lines else [value]
                in_agent_lines = True
            else:
                in_agent_lines = False
                if key == "disallow" and value and "*" in agents:
                    rules.append(value)
        return rules

    def allowed(self, url):
        parts = urlsplit(url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        for rule in self.disallow:
            anchored = rule.endswith("$")
            pattern = re.escape(rule.rstrip("$")).replace(r"\*", ".*")
            if re.match(pattern + ("$" if anchored else ""), target):
                return False
        return True

    def _request(self, url):
        last_error = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                response = self.session.get(url, timeout=60)
            except requests.RequestException as error:
                last_error = error
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = requests.HTTPError(f"HTTP {response.status_code}")
                continue
            return response
        raise last_error

    def get(self, url, ignore_robots=False):
        """Fetch a URL politely. Returns the response, whatever its status."""
        if not ignore_robots and not self.allowed(url):
            raise RobotsBlocked(url)
        time.sleep(self.delay)
        return self._request(url)

    def soup(self, url, ignore_robots=False):
        response = self.get(url, ignore_robots)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def main_of(soup):
    return soup.find("main") or soup


def to_iso(date_text):
    try:
        return datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return date_text


def slugify(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "unnamed"


def body_key(url):
    """Stable key for a body page, independent of any /content/qualite path prefix."""
    return "/".join(urlsplit(url).path.split("/")[-2:])


def is_document_link(href):
    path = urlsplit(href).path.lower()
    return "/download/" in path or path.endswith(DOCUMENT_EXTENSIONS)


def document_links(root, page_url):
    links, seen = [], set()
    for anchor in root.select("a[href]"):
        url = urljoin(page_url, anchor["href"])
        if is_document_link(url) and url not in seen:
            seen.add(url)
            links.append({"label": clean(anchor.get_text()), "url": url})
    return links


def parse_body_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    main = main_of(soup)
    body = {
        "name": None,
        "accreditation_number": None,
        "address": [],
        "standards": [],
        "valid_until": None,
        "issued_on": None,
        "page_last_updated": None,
        "activities": None,
        "domains": None,
        "other_fields": {},
        "page_url": url,
    }
    for row in main.select("tr"):
        header, value = row.find("th"), row.find("td")
        if not header or not value:
            continue
        label = clean(header.get_text()).replace("’", "'")
        field = FIELD_NAMES.get(label)
        if field in ("address", "standards"):
            body[field] = [clean(part) for part in value.stripped_strings]
        elif field in ("valid_until", "issued_on"):
            body[field] = to_iso(clean(value.get_text()))
        elif field:
            body[field] = clean(value.get_text())
        else:
            body["other_fields"][label] = clean(value.get_text())
    if not body["name"] and main.find("h1"):
        body["name"] = clean(main.find("h1").get_text())
    updated = re.search(r"Dernière mise à jour\s*(\d{2}/\d{2}/\d{4})", main.get_text(" "))
    if updated:
        body["page_last_updated"] = to_iso(updated.group(1))
    body["documents"] = document_links(main, url)
    return body


def result_links(soup, page_url):
    return [
        (clean(link.get_text()), urljoin(page_url, link["href"]))
        for link in soup.select("article.search-result h2 a[href]")
    ]


def collect_results(client, start_url):
    """Every result of a filtered search, following pagination. Query-string URLs: opt-in only."""
    results, url, seen = [], start_url, set()
    while url and url not in seen:
        seen.add(url)
        soup = client.soup(url, ignore_robots=True)
        results += result_links(soup, url)
        next_link = soup.select_one("li.pagination-next a[href]")
        url = urljoin(url, next_link["href"]) if next_link else None
    return results


def discover(client, listing_url):
    """Find the bodies for STANDARD and each body's activities and domains via the site's filters."""
    filter_label = lambda link: clean((link.select_one(".more") or link).get_text())
    listing = client.soup(listing_url)
    standard_link = next(
        (a for a in listing.select("a.filter-value[href]") if filter_label(a) == STANDARD), None
    )
    if standard_link is None:
        raise RuntimeError(f"No '{STANDARD}' filter found on {listing_url}; has the page changed?")
    filtered_url = urljoin(listing_url, standard_link["href"])
    filtered = client.soup(filtered_url, ignore_robots=True)
    results = collect_results(client, filtered_url)

    headline = re.search(r"(\d+)\s*résultat", main_of(filtered).get_text(" "))
    if headline and int(headline.group(1)) != len(results):
        print(f"WARNING: site reports {headline.group(1)} results, found {len(results)}.", file=sys.stderr)

    facets = {}
    for link in filtered.select("a.filter-value[href]"):
        label = filter_label(link)
        if label.startswith("Organismes"):
            kind = "activities"
        elif re.match(r"[A-Z]+\d+\s*-", label):
            kind = "domains"
        else:
            continue
        members = collect_results(client, urljoin(filtered_url, link["href"]))
        for _, url in members:
            facets.setdefault(body_key(url), {"activities": [], "domains": []})[kind].append(label)
    return [url for _, url in results], facets


def unique_path(folder, name, used):
    candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", unquote(name)) or "document"
    stem, suffix = Path(candidate).stem, Path(candidate).suffix
    number = 2
    while candidate.lower() in used:
        candidate, number = f"{stem}-{number}{suffix}", number + 1
    used.add(candidate.lower())
    return folder / candidate


def download_document(client, document, folder, used, out):
    """Download one document into folder. Adds the outcome to the document record."""
    url = document["url"]
    if not client.allowed(url):
        document["error"] = "disallowed by robots.txt"
        return False
    try:
        response = client.get(url)
    except requests.RequestException as error:
        document["error"] = str(error)
        return False
    if response.status_code != 200:
        document["error"] = f"HTTP {response.status_code}"
        return False
    data = response.content
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf") and not data.startswith(b"%PDF-"):
        document["error"] = "response is not a PDF"
        return False
    path = unique_path(folder, name, used)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    document.update(
        file=path.relative_to(out).as_posix(),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return True


def scrape_body(client, url, out, facets):
    """Returns (body or None, error list)."""
    try:
        response = client.get(url)
    except requests.RequestException as error:
        return None, [f"{url}: {error}"]
    if response.status_code != 200:
        return None, [f"{url}: HTTP {response.status_code}"]
    body = parse_body_page(response.content, url)
    if not any(STANDARD in standard for standard in body["standards"]):
        return None, [f"{url}: {body['name']} is no longer listed under {STANDARD}"]
    if facets is not None:
        body.update(facets.get(body_key(url), {"activities": [], "domains": []}))

    folder = out / "bodies" / f"{slugify(body['name'])}_{slugify(body['accreditation_number'] or '')}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_bytes(response.content)
    used, errors = {"page.html"}, []
    for document in body["documents"]:
        print(f"    {document['label']}")
        if not download_document(client, document, folder, used, out):
            errors.append(f"{document['url']}: {document['error']}")
    return body, errors


def write_csv(path, bodies):
    columns = [
        "name", "accreditation_number", "address", "standards", "valid_until", "issued_on",
        "page_last_updated", "activities", "domains", "page_url", "documents",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, columns, extrasaction="ignore")
        writer.writeheader()
        for body in bodies:
            row = dict(body)
            for column in ("address", "standards", "activities", "domains"):
                row[column] = "; ".join(body[column] or [])
            row["documents"] = "; ".join(d.get("file", d["url"]) for d in body["documents"])
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="olas_17021", help="output folder (default: %(default)s)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: %(default)s)")
    parser.add_argument("--discover", action="store_true",
                        help="opt in to the filter pages robots.txt disallows: finds the current "
                             "list of bodies, plus their activities and domains")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    args = parser.parse_args()

    out = Path(args.out)
    client = Client(args.base_url, args.delay)
    listing_url = client.base_url + LISTING_PATH
    errors = []

    if args.discover:
        print("Discovering bodies through the site's search filters (robots.txt opt-in)")
        urls, facets = discover(client, listing_url)
    else:
        urls, facets = [client.base_url + path for path in KNOWN_BODY_PATHS], None

    bodies = []
    for url in urls:
        print(f"Body: {url}")
        body, body_errors = scrape_body(client, url, out, facets)
        errors += body_errors
        if body:
            bodies.append(body)

    if not bodies:
        errors.append("No bodies found; the site layout or URLs may have changed.")

    print("General documents")
    general = document_links(main_of(client.soup(listing_url)), listing_url)
    used = set()
    for document in general:
        print(f"    {document['label']}")
        if not download_document(client, document, out / "general_documents", used, out):
            errors.append(f"{document['url']}: {document['error']}")

    out.mkdir(parents=True, exist_ok=True)
    result = {
        "source": listing_url,
        "standard": STANDARD,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bodies": bodies,
        "general_documents": general,
        "errors": errors,
    }
    (out / "bodies.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "bodies.csv", bodies)

    files = sum("file" in d for b in bodies for d in b["documents"]) + sum("file" in d for d in general)
    print(f"\nDone: {len(bodies)} bodies, {files} files in {out.resolve()}")
    if errors:
        print(f"{len(errors)} problem(s):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        if not args.discover:
            print("A 404 on a body page usually means a renewal changed its URL; rerun with --discover.",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
