#!/usr/bin/env python3
"""Remove everything from a CertiFind dataset folder that cannot be searched: CertiFind keeps
only certification bodies that currently hold a valid accreditation.

Rules (applied to bodies.csv, accreditations.csv and scopes.csv in place):
- An accreditation is kept only if its status is ACTIVE and its expiry_date is empty or not
  before today. WITHDRAWN (withdrawn, expired, cancelled) and SUSPENDED rows are dropped, and
  so is an ACTIVE row whose valid-to date has passed.
- A scope is kept only if its status is ACTIVE and its accreditation is kept.
- A body is kept only if it still holds a kept ISO/IEC 17021-1 accreditation, which search
  requires; otherwise the body and all its rows are dropped.

Each generator (database/<country>/prepare_certifind.py) calls prune() after writing its CSVs,
so a re-run never brings removed bodies back. It can also be run by hand:

    python prune_inactive.py <dataset folder> [<dataset folder> ...] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import csv
import io
from datetime import date
from pathlib import Path

BASE = "ISO/IEC 17021-1"


def _read(path: Path) -> tuple[list[str], list[dict], str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader), newline, bom


def _write(path: Path, header: list[str], rows: list[dict], newline: str, bom: bool) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator=newline)
    w.writeheader()
    w.writerows(rows)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + buf.getvalue().encode("utf-8"))


def prune(folder: Path | str, today: date | None = None) -> list[str]:
    """Filter the dataset in place; returns one line per removed body or accreditation."""
    folder = Path(folder)
    today_s = (today or date.today()).isoformat()
    files = {n: _read(folder / f"{n}.csv") for n in ("bodies", "accreditations", "scopes")}
    _, bodies, *_ = files["bodies"]
    _, accs, *_ = files["accreditations"]
    _, scopes, *_ = files["scopes"]

    def reason(a: dict) -> str | None:
        if a["status"] != "ACTIVE":
            return a["status"].lower()
        if a["expiry_date"] and a["expiry_date"] < today_s:
            return f"expired {a['expiry_date']}"
        return None

    removed: list[str] = []
    valid = [a for a in accs if reason(a) is None]
    holders = {a["body_name"] for a in valid if a["accreditation_standard"] == BASE}
    for a in accs:
        why = reason(a) or (None if a["body_name"] in holders else "no valid ISO/IEC 17021-1 accreditation")
        if why:
            removed.append(f"accreditation {a['certificate_number']} ({a['accreditation_standard']}) "
                           f"{a['body_name']}: {why}")
    kept_accs = [a for a in valid if a["body_name"] in holders]
    kept_certs = {a["certificate_number"] for a in kept_accs}
    kept_scopes = [s for s in scopes if s["status"] == "ACTIVE" and s["certificate_number"] in kept_certs]
    kept_bodies = [b for b in bodies if b["name"] in holders]
    removed += [f"body {b['name']} ({b['country']})" for b in bodies if b["name"] not in holders]

    for name, rows in (("bodies", kept_bodies), ("accreditations", kept_accs), ("scopes", kept_scopes)):
        header, old, newline, bom = files[name]
        if len(rows) != len(old):
            _write(folder / f"{name}.csv", header, rows, newline, bom)
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="+", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    for folder in args.folders:
        removed = prune(folder, args.today)
        bodies = sum(1 for r in removed if r.startswith("body "))
        print(f"{folder.name}: removed {bodies} bodies, {len(removed) - bodies} accreditations")
        for line in removed:
            print(f"  {line}")


if __name__ == "__main__":
    main()
