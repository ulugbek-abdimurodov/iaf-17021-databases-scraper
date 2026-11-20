#!/usr/bin/env python3
"""Collect UKAS Product Certification Bodies (ISO/IEC 17065) data.

Derived from ../ukas_ms_scraper.py, whose client, listing crawler, schedule downloader,
schedule parser and CertCheck matching are imported. Changes for product certification:
  * parent category cat=323 ("Product Certification") instead of 2567 (Management Systems);
    its sub-categories (schemes/regulations, ~44) become each body's categories.
  * the schedule URL is forced to /download-schedule/<no>/Product: a card can link the
    body's ManagementSystems schedule, which is a different PDF.
  * Cloudflare-protected emails are decoded (the MS card parser stored the
    /cdn-cgi/l/email-protection link as the website); the real website is kept.
  * CertiFind outputs ukas_17065_raw.json and scope_lines.csv are added.

ukas.com's robots.txt disallows "/*cat=*" (the listing pages). As in the MS scraper, the
request rate is kept low (default 3 s) and the run stops on HTTP 401/403.

Usage
  python scrape_uk_ukas_17065.py --max-bodies 3     # small trial
  python scrape_uk_ukas_17065.py                    # full run, safe to re-run (resumes)
Output (default ./ukas_17065): the MS scraper's files (bodies.json/csv, body_categories.csv,
certcheck_bodies.csv, schedules/, schedule_text/, schedule_tables/, raw_listings/,
run_summary.json) plus ukas_17065_raw.json and scope_lines.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ukas_ms_scraper as ms  # noqa: E402

ms.PARENT_CATEGORY = "323"  # Product Certification
_ms_parse_card = ms.parse_card


def decode_cfemail(hexstr: str) -> str:
    data = bytes.fromhex(hexstr)
    return "".join(chr(b ^ data[0]) for b in data[1:])


def parse_card(card, base_url: str) -> dict | None:
    rec = _ms_parse_card(card, base_url)
    if not rec:
        return None
    para = card.select_one(".content p") or card.select_one("p")
    email = website = ""
    for a in (para.select("a[href]") if para else []):
        href = a["href"].strip()
        protected = a.select_one("[data-cfemail]")
        if protected or "/cdn-cgi/l/email-protection" in href:
            code = protected["data-cfemail"] if protected else href.split("#", 1)[-1]
            try:
                email = email or decode_cfemail(code)
            except ValueError:
                pass
        elif href.lower().startswith("mailto:"):
            email = email or href[7:].split("?")[0]
        elif not website:
            website = href
    rec["email"] = rec["email"] if rec["email"] and "@" in rec["email"] else email
    rec["website"] = website
    rec["listing_schedule_url"] = rec["schedule_url"]
    rec["schedule_url"] = f"{base_url.rstrip('/')}/download-schedule/{rec['accreditation_number']}/Product"
    return rec


ms.parse_card = parse_card  # parse_listing looks it up at call time


def iso_date(text: str) -> str:
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def write_certifind(bodies: list[dict], out: Path) -> int:
    raw, lines = [], []
    for b in bodies:
        reg = b["accreditation_number"]
        raw.append({
            "registration_no": reg, "id": b.get("listing_post_id", ""), "name": b["name"],
            "address": b["address"], "phone": b["telephone"], "email": b["email"],
            "website": b["website"], "issued": iso_date(b.get("schedule_issue_date", "")),
            "expiry": "", "issue_no": b.get("schedule_issue_no", ""),
            "accredited_to": b.get("accredited_to", ""), "categories": b["categories"],
            "certcheck_status": b.get("certcheck_status", ""),
            "annex_urls": [b["schedule_url"]],
        })
        for i, cat in enumerate(b["categories"]):
            lines.append([reg, "register", i, cat])
        if b.get("schedule_file"):
            txt = out / "schedule_text" / (Path(b["schedule_file"]).stem + ".txt")
            if txt.exists():
                rows = [ms.clean(t) for t in txt.read_text(encoding="utf-8").splitlines()]
                rows = [t for t in rows if t and not re.fullmatch(r"--- page \d+ ---", t)]
                lines += [[reg, f"annex:{Path(b['schedule_file']).name}", i, t]
                          for i, t in enumerate(rows)]
    (out / "ukas_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    with (out / "scope_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    return len(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Collect UKAS Product Certification Bodies (ISO/IEC 17065) data.")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "ukas_17065")
    p.add_argument("--delay", type=float, default=3.0, help="seconds between requests (minimum 1)")
    p.add_argument("--max-bodies", "--limit", type=int, help="only download this many schedules")
    p.add_argument("--refresh", action="store_true", help="fetch again instead of reusing saved files")
    p.add_argument("--skip-certcheck", action="store_true")
    p.add_argument("--no-parse", action="store_true", help="download PDFs without extracting content")
    p.add_argument("--no-files", action="store_true", help="skip schedule PDF downloads")
    p.add_argument("--contact", help="contact detail to include in the User-Agent")
    p.add_argument("--base-url", default="https://www.ukas.com", help=argparse.SUPPRESS)
    p.add_argument("--api-url", default="https://api.certcheck.ukas.com", help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.delay < 1:
        p.error("--delay must be at least 1 second")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    client = ms.Client(args.delay, args.contact)
    client.session.headers["User-Agent"] = client.session.headers["User-Agent"].replace(
        "ukas-ms-scraper", "ukas-17065-scraper")
    warnings: list[str] = []
    failures: list[dict] = []
    bodies: dict[str, dict] = {}
    certcheck: list[dict] = []
    stopped = ""

    def save() -> None:
        ordered = sorted(bodies.values(), key=lambda b: b["accreditation_number"])
        (out / "bodies.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
        ms.write_csv(out / "bodies.csv", ordered, ms.BODY_COLUMNS)
        ms.write_csv(out / "body_categories.csv",
                     [{"accreditation_number": b["accreditation_number"], "name": b["name"], "category": c}
                      for b in ordered for c in b["categories"]],
                     ["accreditation_number", "name", "category"])
        (out / "run_summary.json").write_text(json.dumps({
            "finished_at": datetime.now().astimezone().isoformat(), "stopped_early": stopped,
            "parent_category": ms.PARENT_CATEGORY, "bodies": len(bodies),
            "schedules_saved": sum(1 for b in bodies.values() if b.get("schedule_file")),
            "schedules_without_text": [b["accreditation_number"] for b in ordered
                                       if b.get("schedule_empty_text")],
            "certcheck_rows": len(certcheck), "warnings": warnings, "failures": failures,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        print("Reading the Product Certification category (cat=323) and its sub-categories...")
        bodies = ms.crawl_listings(client, base, out, args.refresh, warnings)
        print(f"Found {len(bodies)} bodies.")
        if not args.skip_certcheck:
            try:
                certcheck = ms.fetch_certcheck(client, args.api_url.rstrip("/"))
                (out / "certcheck_bodies.json").write_text(
                    json.dumps(certcheck, ensure_ascii=False, indent=1), encoding="utf-8")
                ms.attach_certcheck(bodies, certcheck)
            except (ms.Blocked, RuntimeError, ValueError, requests.RequestException) as exc:
                # CertCheck is a separate, optional API (403 from the shell); keep going.
                warnings.append(f"CertCheck list not collected: {exc}")
        selected = sorted(bodies.values(), key=lambda b: b["accreditation_number"])[:args.max_bodies]
        if args.max_bodies:
            bodies = {b["accreditation_number"]: b for b in selected}
        for i, body in enumerate([] if args.no_files else selected, 1):
            print(f"  [{i}/{len(selected)}] {body['accreditation_number']} {body['name']}")
            try:
                body.update(ms.download_schedule(client, base, out, body, args.refresh))
                if not args.no_parse:
                    pdf_path = out / body["schedule_file"]
                    body.update(ms.parse_schedule(pdf_path, out, pdf_path.stem))
            except ms.Blocked:
                raise
            except Exception as exc:  # one bad document should not end the run
                body["error"] = str(exc)
                failures.append({"accreditation_number": body["accreditation_number"], "error": str(exc)})
            save()
    except ms.Blocked as exc:
        stopped = f"{exc}. The site refused access, so the run stopped."
        print(f"STOPPED: {stopped}", file=sys.stderr)

    save()
    ordered = sorted(bodies.values(), key=lambda b: b["accreditation_number"])
    n_lines = write_certifind(ordered, out)
    saved = sum(1 for b in ordered if b.get("schedule_file"))
    no_text = sum(1 for b in ordered if b.get("schedule_empty_text"))
    print(f"\nbodies: {len(ordered)}  scope lines: {n_lines}  PDFs downloaded: {saved} "
          f"failed: {len(failures)} without text: {no_text}  warnings: {len(warnings)}")
    for w in warnings[:15]:
        print(f"  warning: {w}")
    return 1 if stopped or failures else 0


if __name__ == "__main__":
    sys.exit(main())
