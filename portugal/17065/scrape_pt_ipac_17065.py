#!/usr/bin/env python3
"""Download IPAC (Portugal) ISO/IEC 17065 product certification bodies.

ipac_scraper.py already filters by scheme name; this wrapper runs it with --scheme 17065 and
writes to ./ipac_17065_data. Any other ipac_scraper.py option is passed through.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import ipac_scraper as ms  # noqa: E402

if __name__ == "__main__":
    extra = sys.argv[1:]
    if "--scheme" not in extra:
        extra = ["--scheme", "17065", *extra]
    if "--out" not in extra:
        extra = [*extra, "--out", str(HERE / "ipac_17065_data")]
    sys.argv = [sys.argv[0], *extra]
    sys.exit(ms.main())
