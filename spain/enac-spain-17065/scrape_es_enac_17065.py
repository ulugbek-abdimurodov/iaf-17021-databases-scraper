#!/usr/bin/env python3
"""Scrape ENAC (Spain) Product Certification Bodies (ISO/IEC 17065) into CertiFind raw files.

Derived from ../database/spain/scrape_es_enac.py (the management-system scraper), whose
endpoints and list parser are imported. Only the scheme changes: idLista=6 = Product
Certification (accreditation numbers NN/C-PRNNN) instead of idLista=46 (management systems).
The value comes from ENAC's "products and services" search URL for product certification.

Outputs (default folder enac_17065/):
  raw_records.json       the MS scraper's record format (name, addr, phone, email, annex, num, scope)
  enac_17065_raw.json    one record per accreditation (CertiFind input)
  scope_lines.csv        registration_no,source,row_index,product_text_raw
  annexes/<uuid>.pdf     Technical Annex PDFs (skipped with --no-files; resumes)
  run_report.json
Product annexes have no IAF/EA codes, so the MS annex parser (parse_annex) is not used;
only the entry-into-force and revision dates are taken from each annex.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

MS_DIR = Path(__file__).resolve().parent.parent / "database" / "spain"
sys.path.insert(0, str(MS_DIR))
import scrape_es_enac as ms  # noqa: E402

ID_LISTA = "6"  # Product Certification (C-PR); the MS scraper uses 46
_ms_common_params = ms._common_params


def _product_params():
    q = _ms_common_params()
    q[ms.P + "idLista"] = ID_LISTA
    return q


ms._common_params = _product_params

PAGE = 200  # the listing returns at most 200 cards per page whatever delta is asked
NUM_RE = re.compile(r"^(\d{1,4}/C-[A-Z]{1,3}\d{2,4}(?:\.\d+)?)\s*-\s*(.*)$")  # e.g. 09/C-PR010.01


def fetch_records(sess):
    """ms.fetch_records with paging (product list > 200) and numbers like C-PR010.01."""
    from bs4 import BeautifulSoup
    cards = []
    for cur in range(1, 50):
        q = ms._common_params()
        q.update({ms.P + "destino": "listado", ms.P + "delta": str(PAGE),
                  ms.P + "andOperator": "true", ms.P + "cur": str(cur)})
        page = BeautifulSoup(sess.get(ms.BASE, params=q, timeout=90).text, "html.parser")
        found = page.select("div.search-result")
        cards += found
        if len(found) < PAGE:
            break
    q2 = ms._common_params()
    q2[ms.P + "destino"] = "impresion"
    imp_text = re.sub(r"\t", "", BeautifulSoup(sess.get(ms.BASE, params=q2, timeout=90).text,
                                               "html.parser").get_text("\n"))
    imp, name = [], ""
    for line in (x.strip() for x in imp_text.split("\n") if x.strip()):
        m = NUM_RE.match(line)
        if m:
            imp.append((name, m.group(1), m.group(2).strip()))
        elif not re.match(r"^(Phone Number:|Email:)", line) and not re.search(
                r"\d{5}\s*-|nº|C/|Avda|Calle|Plaza|Polígono|Carretera", line) and len(line) > 3:
            name = line
    if len(cards) != len(imp):
        raise RuntimeError(f"listing and print view misaligned: {len(cards)} vs {len(imp)}")
    recs = []
    for i, (c, (_nm, num, scope)) in enumerate(zip(cards, imp)):
        a = c.select_one('a[href*="/documents/7020/"]')
        tel, mail = c.select_one('a[href^="tel:"]'), c.select_one('a[href^="mailto:"]')
        title, span = c.select_one(".title"), c.select_one("span")
        recs.append({
            "i": i, "name": title.get_text().strip() if title else "",
            "addr": span.get_text().strip() if span else "",
            "phone": tel["href"][4:] if tel else "", "email": mail["href"][7:] if mail else "",
            "annex": a["href"].split("/documents/7020/")[1].split("?")[0] if a else "",
            "num": num, "scope": scope,
        })
    return recs


def ddmmyyyy_iso(text: str) -> str:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def annex_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(str(path)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--output", default=str(Path(__file__).parent / "enac_17065"))
    ap.add_argument("--no-files", action="store_true", help="skip annex PDF downloads")
    ap.add_argument("--limit", type=int, default=0, help="only the first N accreditations")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between PDF requests")
    args = ap.parse_args(argv)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (CertiFind scraper)"
    recs = fetch_records(sess)
    print(f"register (idLista={ID_LISTA}): {len(recs)} accreditations")
    if args.limit:
        recs = recs[: args.limit]
    (out / "raw_records.json").write_text(json.dumps(recs, ensure_ascii=False, indent=0),
                                          encoding="utf-8")

    lines, raw, failed, scanned, downloaded = [], [], [], [], 0
    for r in recs:
        reg = r["num"]
        lines.append([reg, "register", 0, r["scope"]])
        issue = rev = ""
        url = ms.DOC + r["annex"] if r["annex"] else ""
        if url and not args.no_files:
            target = out / "annexes" / f"{r['annex']}.pdf"
            if not (target.exists() and target.stat().st_size):
                try:
                    time.sleep(args.delay)
                    resp = sess.get(url, timeout=90)
                    resp.raise_for_status()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(resp.content)
                except requests.RequestException as exc:
                    print(f"  download failed {reg}: {exc}")
                    failed.append(url)
                    target = None
            if target:
                downloaded += 1
                try:
                    text = annex_text(target)
                except Exception as exc:  # noqa: BLE001 - broken PDF reported, not fatal
                    print(f"  cannot read {target.name}: {exc}")
                    text = ""
                rows = [re.sub(r"\s+", " ", t).strip() for t in text.splitlines()]
                rows = [t for t in rows if t]
                if not rows:
                    scanned.append(target.name)
                lines += [[reg, f"annex:{target.name}", i, t] for i, t in enumerate(rows)]
                if m := re.search(r"(?:Coming into effect|entrada en vigor):?\s*(\d{2}/\d{2}/\d{4})", text):
                    issue = m.group(1)
                if m := re.search(r"Rev\.?\s*\d+\s*fecha(?:/date)?\s*(\d{2}/\d{2}/\d{4})", text, re.I):
                    rev = m.group(1)
        raw.append({
            "registration_no": reg, "id": r["annex"] or str(r["i"]), "name": r["name"],
            "address": r["addr"], "phone": r["phone"], "email": r["email"], "website": "",
            "issued": ddmmyyyy_iso(issue), "revision_date": ddmmyyyy_iso(rev), "expiry": "",
            "scope_title": r["scope"], "annex_urls": [url] if url else [],
        })

    (out / "enac_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    bodies = len({r["name"] for r in recs})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": ms.BASE, "idLista": ID_LISTA, "accreditations": len(recs),
              "bodies": bodies, "scope_lines": len(lines), "pdfs_downloaded": downloaded,
              "pdfs_failed": failed, "pdfs_without_text": scanned}
    (out / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"bodies: {bodies}  accreditations: {len(recs)}  scope lines: {len(lines)}  "
          f"PDFs downloaded: {downloaded} failed: {len(failed)} without text: {len(scanned)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
