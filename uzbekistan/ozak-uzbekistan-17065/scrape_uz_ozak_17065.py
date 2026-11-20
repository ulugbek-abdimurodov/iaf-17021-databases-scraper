"""Scrape O'ZAK (akkred.uz) Product Certification Bodies, ISO/IEC 17065.

Same register as ../accred_uz_management_bodies.py (https://akkred.uz/uz/reestr), but read through the JSON
API the page itself calls, instead of clicking through the table with Playwright (the click-based pager stops
after page 1 for this register because the list refreshes slowly and ?page=N in the page URL is ignored):

  https://api-e.akkred.uz/apps/registries/main/?page=N&type_std=17     (17 = "Mahsulot sertifikatlash organi",
                                                                        O'z DSt ISO/IEC 17065; MS register = 20)
All statuses are collected (no status filter), like the MS scraper.

Outputs (in --out, default ./ozak_17065/):
  raw/registries.json    untouched API records
  ozak_17065_raw.json    one record per accreditation (CertiFind shape)
  scope_lines.csv        registration_no,source,row_index,product_text_raw
                         source = register (API "text", split on ';') or annex:<file> (PDF text layer)
  pdfs/<number>/         certificate, scope (oblast) and scope-update PDFs   (skipped with --no-files)
"""
import argparse
import csv
import json
import re
import time
from pathlib import Path

import requests

API = "https://api-e.akkred.uz/apps/registries/main/"
TYPE_STD = 17
HERE = Path(__file__).resolve().parent
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
PDF_FIELDS = ("certificate_pdf", "file_oblast", "file_scopes")
SCOPE_PDF_FIELDS = ("file_oblast", "file_scopes")


def get(url, **kw):
    for i in range(4):
        try:
            r = S.get(url, timeout=120, **kw)
            r.raise_for_status()
            return r
        except Exception:
            if i == 3:
                raise
            time.sleep(2 * (i + 1))


def fetch(limit: int | None) -> list[dict]:
    out, url, params = [], API, {"page": 1, "type_std": TYPE_STD}
    while url:
        j = get(url, params=params).json()
        out += j["results"]
        print(f"page {params and params['page'] or '?'}: {len(out)}/{j['count']}")
        url, params = j.get("next"), None
        if limit and len(out) >= limit:
            return out[:limit]
    return out


def safe(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s or "x")


def pdf_lines(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        return [ln.strip() for p in PdfReader(path).pages for ln in (p.extract_text() or "").splitlines() if ln.strip()]
    except Exception:
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape O'ZAK product certification bodies (ISO/IEC 17065).")
    ap.add_argument("--out", type=Path, default=HERE / "ozak_17065")
    ap.add_argument("--limit", type=int, help="number of records (trial run)")
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    out = a.out
    (out / "raw").mkdir(parents=True, exist_ok=True)

    recs = fetch(a.limit)
    (out / "raw" / "registries.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

    raw, lines = [], []
    ok = failed = no_text = 0
    for r in recs:
        no = r["number"]
        urls = {f: r[f] for f in PDF_FIELDS if r.get(f)}
        raw.append({
            "registration_no": no, "id": r["id"], "tin": r.get("tin"),
            "name": r.get("title_organ") or r.get("legal_entity_name"), "legal_entity": r.get("legal_entity_name"),
            "address": r.get("address_organ") or r.get("legal_entity_address"),
            "phone": r.get("phone_ao") or r.get("phone"), "email": r.get("email_ao") or r.get("email"),
            "website": r.get("web_site"),
            "issued": r.get("re_accreditation_date") or r.get("accreditation_date"),
            "first_issued": r.get("accreditation_date"),
            "expiry": r.get("accreditation_duration") or r.get("certificate_date_to"),
            "status": r.get("status"), "status_date": r.get("status_date"),
            "standard": r.get("designation_of_the_fundamental_standard"),
            "certificate_url": r.get("certificate_pdf"),
            "annex_urls": [urls[f] for f in SCOPE_PDF_FIELDS if f in urls],
        })
        parts = [p.strip() for p in re.split(r";\s*", r.get("text") or "") if p.strip()]
        lines += [(no, "register", i, t) for i, t in enumerate(parts)]
        if a.no_files:
            continue
        d = out / "pdfs" / safe(no)
        d.mkdir(parents=True, exist_ok=True)
        for f, u in urls.items():
            p = d / f"{f}__{safe(u.rsplit('/', 1)[-1])}"
            if not p.exists():
                try:
                    c = get(u).content
                    if not c.startswith(b"%PDF"):
                        raise ValueError("not a PDF")
                    p.write_bytes(c)
                except Exception as e:
                    failed += 1
                    print(f"pdf failed {no} {f}: {e}")
                    continue
            ok += 1
            if f in SCOPE_PDF_FIELDS:
                tl = pdf_lines(p)
                if not tl:
                    no_text += 1
                lines += [(no, f"annex:{p.name}", i, t) for i, t in enumerate(tl)]

    (out / "ozak_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    from collections import Counter
    print(f"bodies={len({x['tin'] or x['name'] for x in raw})} accreditations={len(raw)} "
          f"scope_lines={len(lines)} (register={sum(1 for l in lines if l[1] == 'register')}) "
          f"pdfs_ok={ok} pdfs_failed={failed} scope_pdfs_without_text={no_text}")
    print("status:", dict(Counter(x["status"] for x in raw)))


if __name__ == "__main__":
    main()
