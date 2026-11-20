#!/usr/bin/env python3
"""Scrape Dutch RvA ISO/IEC 17065 product certification bodies from rva.nl.

RvA publishes one register for all accredited bodies. The management system (17021) scraper
filters on norm:17021-1; product certification bodies carry norm:17065. This wrapper reuses the
MS scraper's client, PDF handling and output format and only changes the filter and output folder.

Usage:
    python scrape_nl_rva_17065.py                      # 66 bodies into ./rva_17065_output
    python scrape_nl_rva_17065.py --limit 3            # trial run (any rva_scraper.py option works)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the MS scraper lives one folder up
import rva_scraper as ms  # noqa: E402

PRODUCT_FILTER = "norm:17065"
DEFAULT_OUT = "rva_17065_output"


def iso(date: str) -> str:
    """'11-09-2026' / '11.9.2026' -> '2026-09-11' (other text is returned unchanged)."""
    import re
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", (date or "").strip())
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (date or "")


def write_certifind(out: Path) -> None:
    """rva_17065_raw.json (one record per accreditation) and scope_lines.csv (annex text lines)."""
    import csv
    import json

    bodies = json.loads((out / "bodies.json").read_text(encoding="utf-8"))
    docs = json.loads((out / "documents.json").read_text(encoding="utf-8"))
    by_id: dict[str, list[dict]] = {}
    for d in docs:
        by_id.setdefault(d["id"], []).append(d)
    raw, lines = [], []
    for b in bodies:
        mine = by_id.get(b["id"], [])
        dated = sorted(mine, key=lambda d: d.get("language") != "en")  # prefer the English annex
        first = next((d for d in dated if d.get("valid_from") or d.get("valid_until")), {})
        raw.append({
            "registration_no": b["id"], "id": b["id"], "name": b["title"],
            "address": ", ".join(p for p in (b.get("street"), b.get("address"), b.get("country")) if p),
            "phone": b.get("phone", ""), "email": b.get("email", ""), "website": b.get("website", ""),
            "issued": iso(first.get("valid_from", "")), "expiry": iso(first.get("valid_until", "")),
            "normative_document": first.get("normative_document", ""),
            "business_number": b.get("business_number", ""), "url": b["url"],
            "annex_urls": [d["url"] for d in dated],
        })
        for d in dated:
            txt = (out / d["file"]).with_suffix(".txt") if d.get("file") else None
            if not txt or not txt.exists():
                continue
            rows = [ms.clean(t) for t in txt.read_text(encoding="utf-8").splitlines()]
            rows = [t for t in rows if t]
            lines += [[b["id"], f"annex:{txt.with_suffix('.pdf').name}", i, t] for i, t in enumerate(rows)]
    (out / "rva_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "scope_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    no_text = sum(1 for d in docs if d.get("pages") and not
                  ((out / d["file"]).with_suffix(".txt").exists()
                   and (out / d["file"]).with_suffix(".txt").read_text(encoding="utf-8").strip()))
    print(f"CertiFind: {len(raw)} accreditations, {len(lines)} scope lines, "
          f"{len(docs)} PDFs ({no_text} without text) -> rva_17065_raw.json, scope_lines.csv")


def main() -> int:
    extra = sys.argv[1:]
    if "--filter" not in extra:
        extra = ["--filter", PRODUCT_FILTER, *extra]
    if "--out" not in extra:
        extra = [*extra, "--out", str(HERE / DEFAULT_OUT)]
    out = Path(extra[extra.index("--out") + 1])
    sys.argv = [sys.argv[0], *extra]
    code = ms.main()
    if (out / "bodies.json").exists():
        write_certifind(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
