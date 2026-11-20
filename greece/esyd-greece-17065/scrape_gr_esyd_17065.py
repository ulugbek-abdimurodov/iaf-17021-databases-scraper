"""Download every ISO/IEC 17065 product certification body from the Greek ESYD register.

Derived from ../esyd_scraper.py (the 17021 scraper), whose client, parsers and downloader are
imported. ESYD still labels product certification with the old standard name "ELOT EN 45011"
(replaced by ISO/IEC 17065); both labels are accepted. The site's own search value is
"accStd:45011". Outputs (default folder esyd_17065/):
  bodies.csv, accreditations.csv, bodies.json, run_report.json  (same as the MS scraper)
  esyd_17065_raw.json   one record per accreditation (CertiFind input)
  scope_lines.csv       registration_no,source,row_index,product_text_raw
  scope_documents/      scope annexes (.doc), unless --download-docs none
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

MS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MS_DIR))
import esyd_scraper as ms  # noqa: E402
import worddoc  # noqa: E402

# Product certification: 17065, or its predecessor EN 45011 as ESYD still prints it.
ms.STANDARD_RE = re.compile(r"17065|45011")
SEARCH_VALUE = "accStd:45011"
ms.USER_AGENT = "esyd-17065-scraper/1.0 (accredited body register export)"

log = logging.getLogger("esyd17065")


class Scraper(ms.Scraper):
    def search_ids(self) -> list[str]:
        """Ids the site's own search returns for product certification (45011/17065)."""
        ids: list[str] = []
        for page in range(1, ms.MAX_CATALOGUE_PAGES + 1):
            html = self._html("POST", f"{self.en}showResults.jsp", data={
                "nomos": "", "protypoDiap": SEARCH_VALUE, "protypoPist": "", "antikeimeno": "",
                "ea": "", "nace": "", "type": "Body", "page": str(page),
            })
            new = [i for i in ms.parse_catalogue_ids(html) if i not in ids]
            if not new:
                break
            ids.extend(new)
        return ids


def write_certifind(bodies: list[ms.Body], out_dir: Path, docs_dir: Path) -> dict:
    raw, lines, stats = [], [], {"docs_read": 0, "docs_no_text": 0}
    for body in bodies:
        address = ", ".join(p for p in (body.address, body.city, body.region) if p)
        folder = docs_dir / f"{body.body_id}_{ms.safe_name(body.name)}"
        for acc in body.accreditations:
            reg = acc.certificate_number or body.body_id
            raw.append({
                "registration_no": reg, "id": body.body_id, "name": body.name,
                "address": address, "phone": body.telephone, "email": body.email,
                "website": body.website, "issued": acc.valid_since, "expiry": "",
                "standard": acc.standard, "field": acc.field,
                "annex_urls": [u for u in (acc.scope_doc_en, acc.scope_doc_el) if u],
            })
            if acc.field:
                lines.append([reg, "register", len(lines), acc.field])
            for url in (acc.scope_doc_en, acc.scope_doc_el):
                path = folder / url.rsplit("/", 1)[-1] if url else None
                if not path or not path.exists():
                    continue
                try:
                    text = worddoc.read_text(path)
                except Exception as exc:  # noqa: BLE001 - odd files are reported, not fatal
                    log.warning("cannot read %s: %s", path.name, exc)
                    text = ""
                stats["docs_read"] += 1
                text = re.sub(r"[\x00-\x08\x0b-\x1f]", "\n", text)  # Word cell/row marks
                rows = [ms.clean(t) for t in text.splitlines() if ms.clean(t)]
                if not rows:
                    stats["docs_no_text"] += 1
                for i, row in enumerate(rows):
                    lines.append([reg, f"annex:{path.name}", i, row])
    (out_dir / "esyd_17065_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out_dir / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        writer.writerows(lines)
    stats["scope_lines"] = len(lines)
    return stats


def run(args: argparse.Namespace) -> int:
    scraper = Scraper(args.base_url, args.delay)
    out_dir = Path(args.output)
    ids = scraper.catalogue_ids()
    log.info("catalogue lists %d bodies; checking each for 17065/45011", len(ids))
    if args.limit:
        ids = ids[: args.limit]

    bodies, errors, checked = [], [], set()
    for index, body_id in enumerate(ids, 1):
        try:
            body = scraper.fetch_body(body_id)
            checked.add(body_id)
        except (requests.RequestException, ms.ParseError) as exc:
            log.error("body %s failed: %s", body_id, exc)
            errors.append({"body_id": body_id, "error": str(exc)})
            continue
        if body:
            bodies.append(body)
            log.info("[%d/%d] 17065: %s (%d scopes)", index, len(ids), body.name,
                     len(body.accreditations))

    ms.write_outputs(bodies, out_dir)
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": scraper.en, "filter": "standard ~ 17065|45011; search " + SEARCH_VALUE,
        "catalogue_bodies_checked": len(checked), "bodies_17065": len(bodies),
        "accreditation_rows": sum(len(b.accreditations) for b in bodies), "errors": errors,
    }
    found = {b.body_id for b in bodies}
    if not args.limit:
        try:
            search = set(scraper.search_ids())
            report["search_cross_check"] = {
                "search_results": len(search),
                "in_search_but_no_17065_on_detail_page": sorted(search & checked - found),
                "in_search_but_not_in_catalogue": sorted(search - set(ids)),
                "has_17065_but_not_in_search": sorted(found - search),
            }
        except (requests.RequestException, ms.ParseError) as exc:
            report["search_cross_check"] = {"error": str(exc)}

    docs_dir = out_dir / "scope_documents"
    failures: list = []
    if args.download_docs != "none":
        languages = ["en", "el"] if args.download_docs == "both" else [args.download_docs]
        failures = scraper.download_docs(bodies, docs_dir, languages)
        report["download_failures"] = failures
    report["certifind"] = write_certifind(bodies, out_dir, docs_dir)
    (out_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    c = report["certifind"]
    print(f"bodies: {len(bodies)}  accreditations: {report['accreditation_rows']}  "
          f"scope lines: {c['scope_lines']}  docs read: {c['docs_read']} "
          f"(no text: {c['docs_no_text']})  download failures: {len(failures)}  "
          f"errors: {len(errors)}")
    return 1 if errors or failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default=str(Path(__file__).parent / "esyd_17065"))
    parser.add_argument("--download-docs", choices=("none", "en", "el", "both"), default="en",
                        help="scope-of-accreditation .doc files to download (default: en)")
    parser.add_argument("--no-files", dest="download_docs", action="store_const", const="none")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    parser.add_argument("--limit", type=int, default=0, help="check only the first N bodies")
    parser.add_argument("--base-url", default=ms.DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        return run(args)
    except (requests.RequestException, ms.ParseError) as exc:
        log.error("aborted: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
