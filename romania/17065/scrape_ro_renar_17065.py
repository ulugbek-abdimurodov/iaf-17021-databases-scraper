#!/usr/bin/env python3
"""RENAR (Romania) ISO/IEC 17065 product certification bodies.

Runs scraper.py (management systems, categories 5.2.x) with RENAR category 6,
"4 Organisme de certificare produse", into ./renar_17065_output. Categories 18 and 19
(8.2 / 8.3 protected-name and organic products, inspection and certification) are not included.
Any other scraper.py option is passed through.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scraper as ms  # noqa: E402

PRODUCT_ACT = 6
ms.CATEGORIES[PRODUCT_ACT] = "4 Organisme de certificare produse"

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--acts" not in argv:
        argv = ["--acts", str(PRODUCT_ACT), *argv]
    if "--out" not in argv:
        argv = [*argv, "--out", str(HERE / "renar_17065_output")]
    sys.exit(ms.run(ms.parse_args(argv)))
