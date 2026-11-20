"""Shared helpers for the US ISO/IEC 17065 scrapers (A2LA, ANAB, IOAS, UAF).

Every scraper builds a list of accreditation records and calls write_outputs(), which writes the two
CertiFind inputs used by prepare_certifind_17065.py:
  <ab>_17065_raw.json : one record per accreditation
      registration_no, id, name, address, phone, email, website, issued, expiry, annex_urls (+ extra keys)
  scope_lines.csv     : registration_no,source,row_index,product_text_raw
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CertiFind-scraper"}
RAW_KEYS = ["registration_no", "id", "name", "address", "phone", "email", "website", "issued", "expiry",
            "annex_urls"]


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def get(sess: requests.Session, url: str, tries: int = 3, **kw) -> requests.Response:
    for i in range(tries):
        try:
            r = sess.get(url, timeout=60, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                return r
        except requests.RequestException:
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))
    r.raise_for_status()
    return r


def safe_name(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_")[:80]


def download_pdf(sess, url: str, dest: Path, stats: dict) -> Path | None:
    """Download once (resume); returns the path or None. Counts downloaded/cached/failed in stats."""
    if dest.exists() and dest.stat().st_size > 0:
        stats["pdf_cached"] = stats.get("pdf_cached", 0) + 1
        return dest
    try:
        r = get(sess, url)
        if not r.content.startswith(b"%PDF"):
            raise ValueError("not a PDF")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        stats["pdf_downloaded"] = stats.get("pdf_downloaded", 0) + 1
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"  ! PDF failed {url}: {e}")
        stats["pdf_failed"] = stats.get("pdf_failed", 0) + 1
        return None


def pdf_text(path: Path) -> list[str]:
    """Text per page ('' for scanned pages)."""
    from pypdf import PdfReader
    try:
        return [p.extract_text() or "" for p in PdfReader(str(path)).pages]
    except Exception:  # noqa: BLE001
        return []


def clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]


def write_outputs(out: Path, ab: str, records: list[dict], scope_rows: list[tuple], stats: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    recs = [{**{k: r.get(k, [] if k == "annex_urls" else "") for k in RAW_KEYS},
             **{k: v for k, v in r.items() if k not in RAW_KEYS}} for r in records]
    (out / f"{ab}_17065_raw.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "scope_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(scope_rows)
    bodies = len({r.get("id") or r["name"] for r in records})
    print(f"\n{ab.upper()} 17065 -> {out}\n  bodies: {bodies}\n  accreditations: {len(records)}\n"
          f"  scope lines: {len(scope_rows)}\n  PDFs downloaded: {stats.get('pdf_downloaded', 0)}"
          f" (cached {stats.get('pdf_cached', 0)}), failed: {stats.get('pdf_failed', 0)}"
          f", without text layer: {stats.get('pdf_scanned', 0)}")
