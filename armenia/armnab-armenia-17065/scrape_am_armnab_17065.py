#!/usr/bin/env python3
"""Scrape ARMNAB's register of accredited product certification bodies (ISO/IEC 17065).

Site: https://armnab.am/certification-bodies (list, 15 rows server-rendered) and
https://armnab.am/certification-bodies-n/CBnnnnnnnn (detail pages, sequential ids).

Built on ../armnab_scraper.py (same Blazor site, same detail-page layout and parser); only the register path,
the id prefix (CB instead of MS) and the outputs differ. Like the MS scraper it walks the ids upward from 1 and
checks the total against the count on the list page.

    python scrape_am_armnab_17065.py [--output armnab_17065] [--delay 0.3]

Output:
    armnab_17065_raw.json  one record per accreditation (all statuses; prepare keeps the active ones)
    scope_lines.csv        registration_no,source,row_index,product_text_raw: the detail page's
                           "Հավատարմագրման ոլորտը" (accreditation scope) text, one row per line
    run_report.json        counts and errors
"""
from __future__ import annotations

import argparse, csv, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import armnab_scraper as ms  # noqa: E402

LIST_PATH = "/certification-bodies"
DETAIL_PATH = "/certification-bodies-n"
PREFIX = "CB"
SCOPE_BLOCK = "Հավատարմագրման ոլորտը"


class ProductScraper(ms.Scraper):
    def get(self, url):
        """The MS client gives up on 4xx; the site answers bursts with 429, so wait and retry those."""
        import time
        for wait in (0, 30, 60, 120, 240):
            time.sleep(wait)
            response = self.session.get(url, timeout=ms.TIMEOUT_SECONDS)
            time.sleep(self.delay)
            self.counts["requests"] += 1
            if response.status_code != 429:
                break
        if response.status_code == 200:
            return response
        self.error(url, f"HTTP {response.status_code}")
        return None

    def fetch_record(self, detail_id):
        url = f"{self.base_url}{DETAIL_PATH}/{detail_id}"
        response = self.get(url)
        if response is None:
            return None, False
        response.encoding = "utf-8"
        try:
            record = ms.parse_detail(response.text, detail_id, url)
        except (ValueError, AttributeError, KeyError) as exc:
            self.error(url, f"parse failed: {exc}")
            return None, False
        if record is None:
            self.counts["ids_not_found"] += 1
            return None, True
        return record, True

    def run(self):
        response = self.get(self.base_url + LIST_PATH)
        stated, listed = None, []
        if response is not None:
            response.encoding = "utf-8"
            html = response.text.replace(f"{DETAIL_PATH}/", "/management-systems/MS-")
            stated, listed = ms.parse_list(html)  # reuse the list parser; ids come back as "MS-CBnnnnnnnn"
        self.stated_total = stated
        highest = max((int(r["detail_id"][len("MS-" + PREFIX):]) for r in listed), default=0)
        records, misses, number = [], 0, 0
        while number < highest or misses < ms.STOP_AFTER_MISSES:
            number += 1
            record, ok = self.fetch_record(f"{PREFIX}{number:08d}")
            if record is not None:
                records.append(record); misses = 0
            elif ok:
                misses += 1
        if stated is not None and stated != len(records):
            self.error(self.base_url + LIST_PATH, f"list page says {stated} records, scraped {len(records)}")
        return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", type=Path, default=HERE / "armnab_17065")
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    s = ProductScraper(ms.BASE_URL, args.output, args.delay, False)
    records = s.run()
    raw, lines = [], []
    for r in records:
        reg = (r["certificate_numbers"] or [r["registration"].lstrip("№ ").strip()])[0]
        scope = [ln for b in r["blocks"] if b["title"] == SCOPE_BLOCK for e in b["entries"] for ln in e["lines"]]
        raw.append({"registration_no": reg, "id": r["detail_id"], "name": r["name"], "status": r["status"],
                    "address": r["activity_address"] or r["legal_address"], "legal_address": r["legal_address"],
                    "phone": r["phone"], "email": r["email"], "website": "", "head": r["head"],
                    "issued": r["start_date"], "expiry": r["end_date"], "decision_number": r["decision_number"],
                    "decision_date": r["decision_date"], "detail_url": r["source_url"],
                    "annex_urls": r["documents"] or [r["source_url"]],
                    "blocks": {b["title"]: [ln for e in b["entries"] for ln in e["lines"]] for b in r["blocks"]}})
        for i, ln in enumerate(scope):
            lines.append({"registration_no": reg, "source": r["source_url"], "row_index": i, "product_text_raw": ln})
    (args.output / "armnab_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(args.output / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(lines)
    (args.output / "run_report.json").write_text(json.dumps({"stated_total": s.stated_total, "records": len(records),
        **s.counts, "errors": s.errors}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bodies: {len({r['name'] for r in raw})}\nAccreditations: {len(raw)}\n"
          f"Scope lines: {len(lines)}\nErrors: {len(s.errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
