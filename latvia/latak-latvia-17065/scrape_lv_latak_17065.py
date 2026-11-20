#!/usr/bin/env python3
"""Scrape Latvian (LATAK) Product Certification Bodies (ISO/IEC 17065), ID prefix S1.

Derived from ../latak_s2_scraper.py (management systems, prefix S2), which is imported and run
with --scope S1. LATAK's register on www.latak.gov.lv lists every body in one active and one
inactive table; the ID prefix is the type: S1 = product certification (17065), S2 = management
systems (17021-1), S3 = personnel (17024). Each body has one PDF: certificate (portrait pages)
followed by the annex (landscape pages); the MS scraper downloads, splits and extracts it.

    python scrape_lv_latak_17065.py              # writes to ./latak_17065
    python scrape_lv_latak_17065.py --limit 3    # trial
    python scrape_lv_latak_17065.py --no-files   # tables only

Output: the MS scraper's files (bodies.json/csv, raw_tables/, <ID>/...) plus
latak_17065_raw.json and scope_lines.csv for CertiFind.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import latak_s2_scraper as ms  # noqa: E402

SCOPE = "S1"


LV_MONTHS = ["janvār", "februār", "mart", "aprīl", "maij", "jūnij",
             "jūlij", "august", "septembr", "oktobr", "novembr", "decembr"]


def iso(date):
    """'19.03.2030' or '2025. gada 20. marta' -> ISO date (other text unchanged)."""
    m = re.fullmatch(r"(\d{4})\. gada (\d{1,2})\. (\w+)", (date or "").strip())
    if m:
        month = next((i for i, s in enumerate(LV_MONTHS, 1) if m.group(3).lower().startswith(s)), 0)
        if month:
            return f"{m.group(1)}-{month:02d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\.?", (date or "").strip())
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (date or "")


def annex_lines(directory, document):
    """Text lines of the annex pages (those after the certificate pages)."""
    stem = Path(document.get("file", "")).stem
    txt = directory / f"{stem}_text.txt"
    if not stem or not txt.exists():
        return None
    cert_pages = document.get("certificate_pages") or 0
    pages = re.split(r"^--- page (\d+) ---$", txt.read_text(encoding="utf-8"), flags=re.M)
    lines = []
    for number, text in zip(pages[1::2], pages[2::2]):
        if int(number) > cert_pages:
            lines += [ms.clean(t) for t in text.splitlines() if ms.clean(t)]
    return lines


def write_certifind(out):
    data = json.loads((out / "bodies.json").read_text(encoding="utf-8"))
    raw, lines, with_text, without_text = [], [], 0, []
    for body in data["bodies"]:
        reg = body["id"]
        cert = body.get("certificate", {})
        period = cert.get("accreditation_period", "")
        start = re.search(r"no\s*(\d{4}\. gada \d{1,2}\. \w+)", period)
        raw.append({
            "registration_no": reg, "id": cert.get("registration_number", ""),
            "name": body.get("name", ""), "address": body.get("addresses", ""),
            "phone": body.get("phone", ""), "email": "", "website": "",
            "issued": iso(start.group(1)) if start else "",
            "expiry": iso(body.get("valid_until", "")), "status": body["status"],
            "decision_date": iso(body.get("decision_date", "")), "notes": body.get("notes", ""),
            "standard": cert.get("standard", ""), "certificate_number": cert.get("certificate_number", ""),
            "scope_text": body.get("scope", ""),
            "annex_urls": [d["url"] for d in body.get("documents", [])],
        })
        if body.get("scope"):
            lines.append([reg, "register", 0, body["scope"]])
        for document in body.get("documents", []):
            got = annex_lines(out / ms.safe_name(reg), document)
            if got is None:
                continue
            if got:
                with_text += 1
                lines += [[reg, f"annex:{document['file']}", i, t] for i, t in enumerate(got)]
            else:
                without_text.append(document["file"])
    (out / "latak_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        writer.writerows(lines)
    pdfs = sum(1 for b in data["bodies"] for d in b.get("documents", []) if d.get("file"))
    links = sum(len(b.get("documents", [])) for b in data["bodies"])
    statuses = {s: sum(b["status"] == s for b in data["bodies"]) for s in ("active", "inactive")}
    print(f"bodies: {len(raw)} {statuses}  scope lines: {len(lines)}  PDFs downloaded: {pdfs}/{links}  "
          f"annexes with text: {with_text} without: {len(without_text)}  problems: {len(data['errors'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, default=HERE / "latak_17065")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between downloads")
    parser.add_argument("--limit", type=int, default=0, help="only the first N bodies per table")
    parser.add_argument("--no-files", action="store_true", help="skip PDF downloads")
    args = parser.parse_args()

    if args.limit:
        rows = ms.rows_for_scope
        ms.rows_for_scope = lambda *a, **k: rows(*a, **k)[: args.limit]
    if args.no_files:
        ms.process_document = lambda *a, **k: None
    sys.argv = [sys.argv[0], "--scope", SCOPE, "-o", str(args.output), "--delay", str(args.delay)]
    code = ms.main()
    if (args.output / "bodies.json").exists():
        write_certifind(args.output)
    return code


if __name__ == "__main__":
    sys.exit(main())
