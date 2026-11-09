#!/usr/bin/env python3
"""Re-fetch only the EGAC bodies whose detail page came back incomplete or failed in the last
egac_ms_scraper.py run (the 'incomplete' / 'error' fields in cabs.json), with their PDFs,
instead of scraping all bodies again. Uses the scraper's own functions and output layout.

Run:  python egac_retry_incomplete.py  [--out egac_ms_bodies] [--attempts 6] [--wait 30]
"""
import argparse
import json
import sys
from pathlib import Path

import egac_ms_scraper as s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="egac_ms_bodies")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--wait", type=int, default=30)
    args = ap.parse_args()

    out = Path(args.out)
    cabs = json.loads((out / "cabs.json").read_text(encoding="utf-8"))
    todo = [c for c in cabs if c.get("incomplete") or c.get("error") or not c.get("accreditations")]
    print(f"{len(todo)} bodies to retry: {', '.join(c['reference_no'] for c in todo)}")
    client = s.Client(args.delay)
    used = {f["local_path"] for c in cabs for a in c.get("accreditations", []) for f in a["files"]
            if f.get("local_path")}
    used = {str(out / p) for p in used}

    for cab in todo:
        print(f"{cab['reference_no']} {cab['name']}")
        try:
            detail = s.fetch_detail(client, cab["detail_url"], attempts=args.attempts, wait=args.wait)
        except Exception as exc:
            cab["error"] = f"detail page: {exc}"
            print(f"  ERROR {cab['error']}", file=sys.stderr)
            continue
        cab.update(detail)
        cab.pop("error", None)
        folder_name = s.safe_name(f"{cab['reference_no']} - {cab['name']}")
        for acc in cab.get("accreditations", []):
            for item in acc["files"]:
                kind = s.FILE_TYPES.get(item["type"], f"type_{item['type']}")
                folder = out / "files" / folder_name / acc["status"] / s.safe_name(acc["title"]) / kind
                target = s.unique_path(folder, s.safe_name(item["file_name"], 120), used)
                item["local_path"] = str(target.relative_to(out))
                try:
                    item["result"] = s.download_pdf(client, item, target)
                except Exception as exc:
                    item["result"] = f"error: {exc}"
                print(f"  {item['file_name']}: {item['result']}")
        print(f"  {'still incomplete' if cab.get('incomplete') else 'complete'}")
        s.write_outputs(out, cabs)

    still = [c["reference_no"] for c in todo if c.get("incomplete") or c.get("error")]
    print(f"Done. Still incomplete: {', '.join(still) or 'none'}")


if __name__ == "__main__":
    main()
