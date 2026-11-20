"""SOAC-WAAS product/process/service certification bodies (ISO/IEC 17065).
Register: https://soacwaas.org/en/oec/referentiel/CERTIFICATION_DE_PRODUITS_DE_PROCEDES_ET_DE_SERVICES
Usage: python scrape_waas_soac_17065.py [--limit N] [--no-files] [--out DIR]
"""
import argparse
from pathlib import Path
from soac_common import run

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int)
ap.add_argument("--no-files", action="store_true")
ap.add_argument("--out", default=str(Path(__file__).parent / "soac_17065"))
a = ap.parse_args()
run("CERTIFICATION_DE_PRODUITS_DE_PROCEDES_ET_DE_SERVICES", a.out, a.limit, a.no_files)
