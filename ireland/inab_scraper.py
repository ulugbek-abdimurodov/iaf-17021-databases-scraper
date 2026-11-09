#!/usr/bin/env python3
"""Scrape an INAB directory: body details, contacts, certificates and scopes.

    pip install requests beautifulsoup4
    python inab_scraper.py

Writes to ./inab_output (change with --out):
    bodies.json      everything, nested
    bodies.csv       one row per accredited body
    documents.csv    one row per PDF, with size and SHA-256
    documents/<accreditation no>_<body>/*.pdf

Re-running skips PDFs already downloaded (use --force to refetch). Other INAB
directories that use the same page layout work via --url.
"""
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
from requests.adapters import HTTPAdapter, Retry

DEFAULT_URL = (
    "https://www.inab.ie/inab-directory/certification-bodies/"
    "management-systems-certification/"
)
LABELS = {
    "tel": "phone", "telephone": "phone", "phone": "phone", "fax": "fax",
    "mobile": "mobile", "contact": "contact_person", "email": "email",
    "e-mail": "email", "website": "website", "web": "website",
}
LABEL_RE = re.compile(r"\b(" + "|".join(LABELS) + r")\s*:", re.I)


def clean(text):
    return re.sub(r"[ \t\xa0]+", " ", text or "").strip()


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "inab-directory-scraper/1.0"
    retry = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def parse_listing(html, base_url):
    """The table is rendered client-side from a `var gridData = [...]` literal."""
    match = re.search(r"\bvar\s+gridData\s*=\s*", html)
    if not match:
        raise ValueError("gridData not found: the page layout may have changed")
    rows, _ = json.JSONDecoder().raw_decode(html[match.end():])

    bodies = []
    for company, summary, location, schedule, certificate in rows:
        link = BeautifulSoup(company, "html.parser").find("a")
        bodies.append({
            "name": clean(link.get_text()),
            "detail_url": urljoin(base_url, link["href"]),
            "location": clean(location),
            "summary": clean(summary),
            "listing_document_urls": [
                urljoin(base_url, a["href"])
                for cell in (schedule, certificate)
                for a in BeautifulSoup(cell, "html.parser").find_all("a", href=True)
            ],
        })
    return bodies


def parse_activities(summary):
    return {
        "standards": re.findall(r"ISO(?:/IEC)?\s*\d+(?:-\d+)?|\bFSSC\b", summary),
        "directives": [clean(d) for d in re.findall(r"\d{4}/\d+/EU[^.\n]*", summary)],
        "notified_body": "notified body" in summary.lower(),
        "services_available_to_public": "available to the public" in summary.lower(),
    }


def parse_contact(soup, base_url):
    contact = {
        "address": [], "phone": "", "fax": "", "mobile": "", "contact_person": "",
        "email": "", "email_link": "", "website": "",
    }
    heading = soup.find(
        lambda t: t.name in ("h2", "h3", "h4") and "Contact Details" in t.get_text()
    )
    if not heading:
        return contact

    paragraphs = [p for p in heading.find_next_siblings("p")]
    text = "\n".join(p.get_text("\n") for p in paragraphs)
    parts = LABEL_RE.split(text)  # [address, label, value, label, value, ...]
    contact["address"] = [line for line in map(clean, parts[0].splitlines()) if line]
    for label, value in zip(parts[1::2], parts[2::2]):
        contact[LABELS[label.lower()]] = clean(" ".join(value.split()))

    for p in paragraphs:
        for a in p.find_all("a", href=True):
            href = a["href"]
            if href.lower().startswith("mailto:"):
                # Kept separately: the link target can differ from the visible address.
                contact["email_link"] = href[7:].split("?")[0]
            elif href.startswith("http"):
                contact["website"] = urljoin(base_url, href)
    return contact


def parse_documents(soup, base_url):
    documents = []
    for article in soup.select(".related-list article"):
        link = article.select_one("h5 a[href]")
        if not link:
            continue
        meta = [clean(c.get_text()) for c in article.select(".post-meta .col-auto")]
        meta = [m for m in meta if m]
        date = next((m for m in meta if re.fullmatch(r"\d{2}/\d{2}/\d{4}", m)), "")
        size = next((m for m in meta if re.fullmatch(r"[\d.]+\s*[KMG]B", m, re.I)), "")
        kind = next((m for m in meta if m not in (date, size)), "")
        documents.append({
            "title": clean(link.get_text()),
            "url": urljoin(base_url, link["href"]),
            "file_type": kind,
            "listed_size": size,
            "listed_date": date,
        })
    return documents


def classify(title):
    lowered = title.lower()
    if "scope" in lowered or "schedule" in lowered:
        return "scope"
    if "cert" in lowered:
        return "certificate"
    if "annex" in lowered:
        return "annex"
    return "other"


def slugify(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60]


def parse_detail(html, body, base_url):
    soup = BeautifulSoup(html, "html.parser")
    body["contact"] = parse_contact(soup, base_url)
    documents = parse_documents(soup, base_url)

    # Anything linked only from the listing table still gets downloaded.
    known = {d["url"] for d in documents}
    for url in body.pop("listing_document_urls"):
        if url not in known:
            known.add(url)
            documents.append({
                "title": unquote(Path(urlparse(url).path).stem), "url": url,
                "file_type": "", "listed_size": "", "listed_date": "",
            })

    number = next(
        (m.group(1) for d in documents if (m := re.search(r"\b(\d{4})\b", d["title"]))),
        "",
    )
    body["accreditation_number"] = number
    body["activities"] = parse_activities(body["summary"])
    body["documents"] = documents


def download(session, doc, body, out_dir, force, used):
    folder = Path("documents") / slugify(f'{body["accreditation_number"]} {body["name"]}')
    kind = classify(doc["title"])
    stem = f'{body["accreditation_number"] or "unnumbered"}_{kind}'
    original = unquote(Path(urlparse(doc["url"]).path).name)
    suffix = Path(original).suffix or ".pdf"
    relative = folder / f"{stem}{suffix}"
    counter = 2
    while relative in used:
        relative = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(relative)

    target = out_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if force or not target.exists():
        response = session.get(doc["url"], timeout=120)
        response.raise_for_status()
        if suffix.lower() == ".pdf" and not response.content.startswith(b"%PDF"):
            raise ValueError("response is not a PDF")
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(response.content)
        partial.replace(target)
        fetched = True
    else:
        fetched = False

    data = target.read_bytes()
    doc.update(
        document_type=kind,
        original_filename=original,
        local_path=relative.as_posix(),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return fetched


def write_csv(path, fields, rows):
    # utf-8-sig so Excel opens the accents correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(out_dir, source_url, bodies, errors):
    result = {
        "source": source_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "body_count": len(bodies),
        "document_count": sum(len(b["documents"]) for b in bodies),
        "errors": errors,
        "bodies": bodies,
    }
    (out_dir / "bodies.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    write_csv(
        out_dir / "bodies.csv",
        ["accreditation_number", "name", "location", "standards", "directives",
         "notified_body", "services_available_to_public", "summary", "address",
         "phone", "fax", "mobile", "contact_person", "email", "email_link", "website",
         "detail_url"],
        [{
            "accreditation_number": b["accreditation_number"],
            "name": b["name"],
            "location": b["location"],
            "standards": "; ".join(b["activities"]["standards"]),
            "directives": "; ".join(b["activities"]["directives"]),
            "notified_body": b["activities"]["notified_body"],
            "services_available_to_public": b["activities"]["services_available_to_public"],
            "summary": b["summary"].replace("\n", " "),
            **b["contact"],
            "address": ", ".join(line.rstrip(" ,") for line in b["contact"]["address"]),
            "detail_url": b["detail_url"],
        } for b in bodies],
    )

    fields = ["accreditation_number", "body", "document_type", "title", "file_type",
              "listed_size", "listed_date", "size_bytes", "sha256", "original_filename",
              "local_path", "url"]
    write_csv(
        out_dir / "documents.csv",
        fields,
        [{
            "accreditation_number": b["accreditation_number"], "body": b["name"],
            **{k: d.get(k, "") for k in fields[2:]},
        } for b in bodies for d in b["documents"]],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="INAB directory page")
    parser.add_argument("--out", default="inab_output", type=Path, help="output folder")
    parser.add_argument("--delay", default=0.5, type=float, help="seconds between requests")
    parser.add_argument("--force", action="store_true", help="re-download existing PDFs")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    session = make_session()

    response = session.get(args.url, timeout=60)
    response.raise_for_status()
    bodies = parse_listing(response.text, args.url)
    print(f"{len(bodies)} bodies found")

    errors = []
    used = set()
    for index, body in enumerate(bodies, 1):
        print(f'[{index}/{len(bodies)}] {body["name"]}')
        time.sleep(args.delay)
        try:
            page = session.get(body["detail_url"], timeout=60)
            page.raise_for_status()
            parse_detail(page.text, body, args.url)
        except (requests.RequestException, ValueError) as exc:
            errors.append({"item": body["detail_url"], "error": str(exc)})
            print(f"  ! {exc}", file=sys.stderr)
            body.setdefault("contact", parse_contact(BeautifulSoup("", "html.parser"), args.url))
            body.setdefault("activities", parse_activities(body["summary"]))
            body.setdefault("accreditation_number", "")
            body["documents"] = [
                {"title": unquote(Path(urlparse(u).path).stem), "url": u, "file_type": "",
                 "listed_size": "", "listed_date": ""}
                for u in body.pop("listing_document_urls", [])
            ]

        for doc in body["documents"]:
            try:
                fetched = download(session, doc, body, args.out, args.force, used)
                state = "downloaded" if fetched else "already present"
                print(f'  {doc["local_path"]} ({doc["size_bytes"]:,} bytes, {state})')
                if fetched:
                    time.sleep(args.delay)
            except (requests.RequestException, ValueError, OSError) as exc:
                errors.append({"item": doc["url"], "error": str(exc)})
                print(f'  ! {doc["url"]}: {exc}', file=sys.stderr)

    write_outputs(args.out, args.url, bodies, errors)
    total = sum(len(b["documents"]) for b in bodies)
    print(f"Done: {len(bodies)} bodies, {total} documents, {len(errors)} errors -> {args.out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
