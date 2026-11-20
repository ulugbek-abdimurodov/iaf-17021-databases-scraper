#!/usr/bin/env python3
"""Download Product Certification Bodies (ISO/IEC 17065) from the Lithuanian NAB register.

Source: http://db.nab.lt/ais/accreditation
Derived from ../nab_scraper.py (management systems), whose fetch, listing, detail-page and
document download code is imported. Changes for product certification:
  * active list: the register's type dropdown value for "Produktų sertifikavimo įstaigos /
    Product certification bodies (ISO/IEC 17065)" instead of the 17021-1 value.
  * suspended and withdrawn lists (all types mixed): product entries are picked by the
    accreditation mark's type code "-03" (e.g. 016-03, 143-03-2), or a certificate number
    LA.03.xxx / LA.nnn-03. The certificate number alone is not enough: product certificates
    come as LA.03.006 and as LA.211-03.
  * CertiFind outputs nab_17065_raw.json and scope_lines.csv.

Usage:  python scrape_lt_nab_17065.py [--out DIR] [--delay S] [--limit N] [--no-files]
Re-running skips documents already downloaded.
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nab_scraper as ms  # noqa: E402

PRODUCT_TYPE = "ee5304b9-3379-4645-8bcb-91f0152b5ddf"
LISTS = [("active", PRODUCT_TYPE), *[(s, t) for s, t in ms.LISTS if s != "active"]]
MARK_RE = re.compile(r"^\d+-03(?:-\d+)?$")
CERT_RE = re.compile(r"^LA\.(?:03\.\d+|\d+-03(?:-\d+)?)$")


def is_product(record):
    return bool(MARK_RE.match(record.get("mark") or "") or CERT_RE.match(record.get("certificate") or ""))


def iso(value):
    """API dates come as [y, m, d] (sometimes with a time part) or as text."""
    if isinstance(value, list) and len(value) >= 3:
        return f"{value[0]:04d}-{value[1]:02d}-{value[2]:02d}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else (value or "")


def pdf_lines(path):
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as exc:  # noqa: BLE001 - a bad PDF is reported, not fatal
        print(f"  cannot read {Path(path).name}: {exc}", file=sys.stderr)
        return []
    return [ms.clean(t) for t in text.splitlines() if ms.clean(t)]


def write_certifind(bodies, out):
    raw, lines, with_text, without_text = [], [], 0, []
    for body in bodies:
        r = body["record"]
        reg = r.get("certificate") or r.get("mark") or r["id"]
        raw.append({
            "registration_no": reg, "id": r["id"], "mark": r.get("mark"),
            "name": r.get("holder"), "legal_entity": r.get("legalEntity"),
            "address": r.get("address"), "phone": r.get("phoneNumber"), "email": r.get("email"),
            "website": r.get("website"), "issued": iso(r.get("validFrom") or r.get("certificateIssueDate")),
            "expiry": iso(r.get("validTo")), "status": body["status"],
            "suspension_date": iso(r.get("suspensionDate")), "cancellation_date": iso(r.get("cancellationDate")),
            "scope_lt": r.get("area"), "scope_en": r.get("description"),
            "annex_urls": [d["url"] for d in body["documents"]],
        })
        for i, part in enumerate(p.strip() for p in re.split(r";\s*|\n", r.get("description") or "") if p.strip()):
            lines.append([reg, "register_en", i, part])
        for i, part in enumerate(p.strip() for p in re.split(r";\s*|\n", r.get("area") or "") if p.strip()):
            lines.append([reg, "register_lt", i, part])
        for doc in body["documents"]:
            path = Path(doc["file"])
            if path.suffix.lower() != ".pdf" or not path.exists():
                continue
            got = pdf_lines(path)
            if got:
                with_text += 1
                lines += [[reg, f"annex:{path.name}", i, t] for i, t in enumerate(got)]
            elif got == []:
                without_text.append(path.name)
    (out / "nab_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        writer.writerows(lines)
    return len(lines), with_text, without_text


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=str(HERE / "nab_17065"), help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--limit", type=int, default=0, help="only the first N bodies per list")
    parser.add_argument("--no-files", action="store_true", help="skip document downloads")
    parser.add_argument("--base", default=ms.BASE, help=ms.argparse.SUPPRESS)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.no_files:
        ms.download_document = lambda base, doc_id, name, folder, used: {
            "id": doc_id, "name": name, "url": f"{base}/document/{doc_id}", "file": "", "skipped": True}

    bodies = []
    for status, search_type in LISTS:
        records = ms.list_records(args.base, search_type, args.delay)
        matches = [r for r in records if status == "active" or is_product(r)]
        if args.limit:
            matches = matches[: args.limit]
        print(f"{status}: {len(matches)} product body/bodies (of {len(records)} listed)")
        for record in matches:
            time.sleep(args.delay)
            print(f"  {record.get('certificate')}  {record.get('holder')}")
            try:
                bodies.append(ms.scrape_body(args.base, record, status, out, args.delay))
            except (ms.urllib.error.URLError, TimeoutError, ConnectionError, ms.http.client.HTTPException) as exc:
                # Some withdrawn bodies' detail pages answer HTTP 500: keep the API record.
                print(f"    detail page failed: {exc}", file=sys.stderr)
                bodies.append({
                    "status": status, "folder": "", "detail_url": f"{args.base}/accreditation/{record['id']}",
                    "record": record, "detail_fields": {}, "documents": [],
                    "document_errors": [], "detail_error": str(exc),
                })

    (out / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False, indent=2), encoding="utf-8")
    ms.write_csv(out / "bodies.csv", bodies)
    n_lines, with_text, without_text = write_certifind(bodies, out)

    docs = sum(1 for b in bodies for d in b["documents"] if d.get("file"))
    failures = [(b["record"].get("certificate"), e) for b in bodies for e in b["document_errors"]]
    statuses = {s: sum(b["status"] == s for b in bodies) for s, _ in LISTS}
    print(f"\nbodies: {len(bodies)} {statuses}  scope lines: {n_lines}  documents downloaded: {docs} "
          f"failed: {len(failures)}  PDFs with text: {with_text} without: {len(without_text)}")
    for certificate, error in failures:
        print(f"FAILED {certificate}: {error['name']}: {error['error']}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
