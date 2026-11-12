#!/usr/bin/env python3
"""Fill proof_url in data/dpa-albania/accreditations.csv with each body's DPA certificate PDF.

The DPA register (https://dpa.gov.al/en/accredited-bodies/) links each management system
certification body (code "CS nnn") in its "Field of Accreditation" cell. The link is a WordPress
attachment page that redirects to the certificate + annex PDF; the final PDF URL is stored.
Every accreditation row of a body (CS 006, CS 006 (27006) ...) gets the same PDF.

Rules: a body listed twice (CS 010) takes its last row (the newer certificate); links into
/wp-admin/ are unusable for visitors and are skipped; bodies without a usable link keep the
current value (the DPA home page).

Run:  python update_proof_urls.py <accreditations.csv>
"""
from __future__ import annotations

import csv
import html
import re
import sys
import urllib.request
from pathlib import Path

PAGE = "https://dpa.gov.al/en/accredited-bodies/"
UA = {"User-Agent": "certifind-dpa-links/1.0"}


def fetch(url: str) -> tuple[str, str]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def final_url(url: str) -> str | None:
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.geturl().replace("http://", "https://", 1) if r.status == 200 else None
    except Exception:
        return None


def cs_links() -> dict[str, str]:
    """CS number ("CS 010") -> certificate link from the register page."""
    _, page = fetch(PAGE)
    links: dict[str, str] = {}
    for row in re.findall(r"<tr.*?</tr>", page, re.S):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", row)))
        m = re.search(r"\bCS\s?-?(\d{3})\b", text)
        hrefs = [h.strip() for h in re.findall(r'href="([^"]+)"', row)]
        hrefs = [h for h in hrefs if "/wp-admin/" not in h]
        if m and hrefs:
            links[f"CS {m.group(1)}"] = hrefs[0]  # later rows overwrite earlier ones
    return links


def main() -> None:
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    columns = list(rows[0].keys())

    resolved = {cs: final_url(link) for cs, link in cs_links().items()}
    changed, missing = 0, set()
    for row in rows:
        base = row["certificate_number"].split(" (")[0]
        url = resolved.get(base)
        if url:
            changed += row["proof_url"] != url
            row["proof_url"] = url
        else:
            missing.add(base)

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, columns, lineterminator=newline)
        w.writeheader()
        w.writerows(rows)
    print(f"{changed} rows updated; linked: {sorted(k for k, v in resolved.items() if v)}")
    print(f"no usable certificate link (kept as is): {sorted(missing)}")


if __name__ == "__main__":
    main()
