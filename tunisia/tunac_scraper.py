#!/usr/bin/env python3
"""Download TUNAC's accredited-body register, with certificates and annexes.

Default scope: management system certification bodies (Cert.Management).
Needs Python 3.8+ and nothing else.

    python tunac_scraper.py                     # management system bodies
    python tunac_scraper.py --domain all        # all 164 bodies, every domain
    python tunac_scraper.py --no-pdf            # data only, no PDFs
    python tunac_scraper.py --force             # download existing PDFs again

Output (in ./tunac_data by default):
    organismes.csv / organismes.json   one row per body
    history.csv                        accreditation changes per body
    documents.csv                      one row per PDF, with status and SHA-256
    raw_api.json                       the site's unmodified response
    pdfs/<accreditation no>_<name>/    annexes and certificates

Re-running is safe: PDFs already on disk are kept unless --force is used.
"""
import argparse
import csv
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_API = "https://www.tunac.tn/webtunac.nsf/(jsongetsearchtowebis)?openagent&ret=!all!"
USER_AGENT = "Mozilla/5.0 (compatible; tunac-register-scraper/1.0)"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RETRY_STATUS = {429, 500, 502, 503, 504}


def strip_tags(text):
    """Remove HTML tags and entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def split_br(text):
    """Split on <br> into cleaned, non-empty lines."""
    lines = (strip_tags(p) for p in re.split(r"<br\s*/?>", text or "", flags=re.I))
    return [line for line in lines if line]


class LinkParser(HTMLParser):
    """Collect (href, label) pairs from the attachefiles field."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None


def safe_url(url):
    """Encode spaces and accents but keep existing %XX sequences.

    The site's links mix raw characters with escapes such as d%27accreditation.
    Encoding '%' again produces %2527, which the server answers with HTTP 400.
    """
    return urllib.parse.quote(url, safe="%/:$?=&!()+,;@~*")


def filename_from_url(url):
    return urllib.parse.unquote(url.rsplit("/", 1)[-1])


def slug(text, max_len=50):
    """Make a folder name that is safe on Windows, macOS and Linux."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")
    return cleaned[:max_len].rstrip("_") or "organisme"


def parse_contact(field):
    """Lines are name, contact, Tel/Fax, email, then address, but not always all."""
    lines = split_br(field)
    name = lines[0] if lines else ""
    out = {"name": name, "contact": "", "phone": "", "fax": "", "email": "", "address": ""}
    address = []
    for line in lines[1:]:
        if re.match(r"t[ée]l", line, re.I) or re.search(r"\bfax\s*:", line, re.I):
            before, _, fax = line.partition("Fax:")
            out["phone"] = re.sub(r"^(?:t[ée]l\s*:?\s*)+", "", before, flags=re.I).strip(" -")
            out["fax"] = fax.strip()
        elif EMAIL_RE.fullmatch(line):
            out["email"] = line
        elif not out["contact"] and not out["phone"] and not out["email"]:
            out["contact"] = line
        else:
            address.append(line)
    out["address"] = ", ".join(address)
    return out


def parse_history(field):
    """Return (valid_from, valid_to, events) from the logbs field."""
    match = re.search(r"entre\s*:\s*(\S+)\s+et\s+(\S+)", strip_tags(field))
    valid_from, valid_to = match.groups() if match else ("", "")
    events = []
    pattern = r"<i[^>]*>\s*<b>\s*A partir\s*([^:<]*?)\s*:?\s*</b>(.*?)</i>"
    for date, text in re.findall(pattern, field or "", flags=re.I | re.S):
        events.append({"date": strip_tags(date), "text": strip_tags(text)})
    return valid_from, valid_to, events


def label_mismatch(label, filename):
    """Flag a certificate whose file name names a different language than its link."""
    if label.upper() not in {"AR", "FR", "EN"}:
        return ""
    found = re.findall(r"(?<![A-Za-z])(ar|fr|en)(?![A-Za-z])", Path(filename).stem, re.I)
    langs = {lang.upper() for lang in found}
    if langs and label.upper() not in langs:
        return "file name says " + "/".join(sorted(langs))
    return ""


def parse_record(rec):
    domain_html = rec.get("domaine", "")
    domain_match = re.search(r"<b>(.*?)</b>", domain_html, flags=re.I | re.S)
    domain = strip_tags(domain_match.group(1)) if domain_match else ""
    standard = strip_tags(re.sub(r"<b>.*?</b>", " ", domain_html, flags=re.I | re.S))
    valid_from, valid_to, events = parse_history(rec.get("logbs", ""))
    parser = LinkParser()
    parser.feed(rec.get("attachefiles") or "")
    docs = [{"label": label, "url": href} for href, label in parser.links if href]
    return {
        "accreditation_no": strip_tags(rec.get("boidps", "")),
        **parse_contact(rec.get("ExtNamePS", "")),
        "domain": domain,
        "standard": standard,
        "scope": split_br(rec.get("descript", "")),
        "status": strip_tags(rec.get("etatdoc", "")),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "events": events,
        "documents": docs,
        "site_id": rec.get("id", ""),
    }


def fetch(url, context, timeout=90, retries=3, delay=2.0):
    """Return the response body, retrying temporary failures."""
    request = urllib.request.Request(safe_url(url), headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code not in RETRY_STATUS or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries:
                raise
        time.sleep(delay * attempt)
    raise RuntimeError("unreachable")


def doc_path(body_dir, body, doc, used):
    label = doc["label"] or "document"
    kind = "Annexe" if label.lower().startswith("annexe") else "Certificat_" + slug(label)
    stem = f"{body['accreditation_no']}_{kind}"
    name, n = f"{stem}.pdf", 2
    while name in used:
        name, n = f"{stem}_{n}.pdf", n + 1
    used.add(name)
    return body_dir / name


def download_documents(bodies, out, context, delay, force):
    rows = []
    for body in bodies:
        body_dir = out / "pdfs" / f"{body['accreditation_no']}_{slug(body['name'])}"
        used = set()
        print(f"{body['accreditation_no']}  {body['name']}")
        for doc in body["documents"]:
            target = doc_path(body_dir, body, doc, used)
            original = filename_from_url(doc["url"])
            row = {
                "accreditation_no": body["accreditation_no"],
                "organisme": body["name"],
                "label": doc["label"],
                "original_filename": original,
                "note": label_mismatch(doc["label"], original),
                "local_path": target.relative_to(out).as_posix(),
                "url": safe_url(doc["url"]),
                "size_bytes": "",
                "sha256": "",
                "status": "",
            }
            rows.append(row)
            try:
                if target.exists() and not force:
                    data, row["status"] = target.read_bytes(), "already present"
                else:
                    data = fetch(doc["url"], context)
                    if not data.startswith(b"%PDF"):
                        raise ValueError("response is not a PDF")
                    body_dir.mkdir(parents=True, exist_ok=True)
                    part = target.with_name(target.name + ".part")
                    part.write_bytes(data)
                    os.replace(part, target)
                    row["status"] = "downloaded"
                    time.sleep(delay)
                row["size_bytes"] = len(data)
                row["sha256"] = hashlib.sha256(data).hexdigest()
                print(f"  {row['status']:<16}{doc['label']:<8}{target.name}")
            except (urllib.error.URLError, OSError, ValueError) as err:
                row["status"] = f"FAILED: {err}"
                print(f"  FAILED          {doc['label']:<8}{original}: {err}", file=sys.stderr)
    return rows


def write_csv(path, rows, fields):
    # utf-8-sig lets Excel display accented characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Scrape TUNAC's register of accredited bodies.")
    parser.add_argument("--domain", default="Cert.Management",
                        help="Cert.Management (default), Cert.Produit, Cert.personne, Inspection, "
                             "Analyse, Essai, Etalonnage, BM, PT, or 'all'")
    parser.add_argument("--out", default="tunac_data", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between downloads")
    parser.add_argument("--no-pdf", action="store_true", help="skip the PDFs")
    parser.add_argument("--force", action="store_true", help="download existing PDFs again")
    parser.add_argument("--api-url", default=DEFAULT_API, help=argparse.SUPPRESS)
    parser.add_argument("--insecure", action="store_true",
                        help="skip TLS certificate checks, only if Python rejects the site's certificate")
    args = parser.parse_args()

    context = ssl.create_default_context()
    if args.insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        raw = fetch(args.api_url, context)
    except (urllib.error.URLError, OSError) as err:
        sys.exit(f"Could not reach the TUNAC register: {err}")
    records = json.loads(raw.decode("utf-8"))
    (out / "raw_api.json").write_bytes(raw)

    bodies = [parse_record(rec) for rec in records]
    if args.domain.lower() != "all":
        bodies = [b for b in bodies if b["domain"].lower() == args.domain.lower()]
    if not bodies:
        sys.exit(f"No bodies found for domain '{args.domain}'.")
    print(f"{len(bodies)} bodies out of {len(records)} in the register\n")

    with open(out / "organismes.json", "w", encoding="utf-8") as handle:
        json.dump(bodies, handle, ensure_ascii=False, indent=2)

    fields = ["accreditation_no", "name", "contact", "phone", "fax", "email", "address", "domain",
              "standard", "scope", "status", "valid_from", "valid_to", "documents_count"]
    write_csv(out / "organismes.csv",
              [{**{k: b[k] for k in fields if k in b},
                "scope": " | ".join(b["scope"]),
                "documents_count": len(b["documents"])} for b in bodies],
              fields)
    write_csv(out / "history.csv",
              [{"accreditation_no": b["accreditation_no"], "organisme": b["name"], **event}
               for b in bodies for event in b["events"]],
              ["accreditation_no", "organisme", "date", "text"])

    if args.no_pdf:
        print(f"Data saved in {out.resolve()} (PDFs skipped)")
        return 0

    rows = download_documents(bodies, out, context, args.delay, args.force)
    write_csv(out / "documents.csv", rows,
              ["accreditation_no", "organisme", "label", "original_filename", "note", "local_path",
               "url", "size_bytes", "sha256", "status"])

    failed = [r for r in rows if r["status"].startswith("FAILED")]
    flagged = [r for r in rows if r["note"]]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} PDFs OK, saved in {out.resolve()}")
    for row in flagged:
        print(f"Check: {row['accreditation_no']} {row['label']} link: {row['note']} "
              f"({row['original_filename']})")
    if failed:
        print(f"{len(failed)} failed; run the script again to retry them.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
