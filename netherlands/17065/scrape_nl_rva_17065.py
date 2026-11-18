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


def main() -> int:
    extra = sys.argv[1:]
    if "--filter" not in extra:
        extra = ["--filter", PRODUCT_FILTER, *extra]
    if "--out" not in extra:
        extra = [*extra, "--out", str(HERE / DEFAULT_OUT)]
    sys.argv = [sys.argv[0], *extra]
    return ms.main()


if __name__ == "__main__":
    sys.exit(main())
