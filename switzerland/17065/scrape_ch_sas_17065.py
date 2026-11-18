#!/usr/bin/env python3
"""Scrape Swiss Accreditation Service (SAS) ISO/IEC 17065 product certification bodies.

SAS publishes one register for all accredited bodies. The management system (17021) scraper
selects the type SCESm; product, process and service certification bodies (17065) are the type
SCESp ("Zertifizierungsstelle für Produkte, Prozesse und Dienstleistungen"). This script reuses
the MS scraper's client, PDF handling and status lists, and only changes the type and the output
folder.

Usage:
    python scrape_ch_sas_17065.py                     # SCESp into ./sas_17065_data
    python scrape_ch_sas_17065.py --delay 1           # any sas_scraper.py option is passed through
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the MS scraper lives one folder up
import sas_scraper as ms  # noqa: E402

PRODUCT_TYPE = "SCESp"
DEFAULT_OUT = "sas_17065_data"


def main() -> int:
    extra = sys.argv[1:]
    if "--types" not in extra:
        extra = ["--types", PRODUCT_TYPE, *extra]
    if "--out" not in extra:
        extra = [*extra, "--out", str(HERE / DEFAULT_OUT)]
    sys.argv = [sys.argv[0], *extra]
    return ms.main()


if __name__ == "__main__":
    sys.exit(main())
