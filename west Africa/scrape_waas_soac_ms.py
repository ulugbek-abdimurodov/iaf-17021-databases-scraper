"""SOAC-WAAS management-system certification bodies (ISO/IEC 17021-1).
Register: https://soacwaas.org/en/oec/referentiel/CERTIFICATION_DES_SYSTEMES_DE_MANAGEMENT
Usage: python scrape_waas_soac_ms.py [--limit N] [--no-files] [--out DIR]
"""
import argparse
from pathlib import Path
from soac_common import run

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int)
ap.add_argument("--no-files", action="store_true")
ap.add_argument("--out", default=str(Path(__file__).parent / "soac_ms"))
a = ap.parse_args()
run("CERTIFICATION_DES_SYSTEMES_DE_MANAGEMENT", a.out, a.limit, a.no_files)
