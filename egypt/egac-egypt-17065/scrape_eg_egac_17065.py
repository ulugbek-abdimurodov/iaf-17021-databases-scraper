#!/usr/bin/env python3
"""
Scraper for EGAC-accredited Product Certification Bodies (ISO/IEC 17065).
Source: https://egac.gov.eg/en/accredited-cabs/ , filter "Product Certification Bodies".

Built on ../egac_ms_scraper.py: same listing, detail pages, contacts and PDF downloads (all statuses, resume,
--limit, --no-files); only the discipline filter, the output folder and the CertiFind outputs differ.

Run:     python scrape_eg_egac_17065.py [--out egac_17065] [--limit 3] [--no-files] ...
Output (default folder: egac_17065/): the MS scraper's files (cabs.json, cabs.csv, contacts.csv, panels.csv,
scopes.csv, files.csv, logos/, files/) plus
  egac_17065_raw.json   one record per 17065 accreditation (panel)
  scope_lines.csv       registration_no,source,row_index,product_text_raw (register scope lines, then annex PDF
                        lines when the PDF has a text layer)
A body that also holds other accreditations keeps only its product-certification panels.
"""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import egac_ms_scraper as ms  # noqa: E402

PRODUCT_ROOT_LABEL = "Product Certification Bodies"
DEFAULT_OUT = "egac_17065"
# panel titles that are product certification; other panels on the same body page are dropped
PRODUCT_PANEL = re.compile(r"product|17065", re.I)

ms.MS_ROOT_LABEL = PRODUCT_ROOT_LABEL
_parse_detail = ms.parse_detail


def parse_detail(html):
    result = _parse_detail(html)
    result["other_panels"] = [a["title"] for a in result["accreditations"] if not is_product(a)]
    result["accreditations"] = [a for a in result["accreditations"] if is_product(a)]
    return result


def is_product(acc):
    root = acc["scopes"][0]["path"] if acc["scopes"] else ""
    return bool(PRODUCT_PANEL.search(acc["title"]) or PRODUCT_PANEL.search(root))


ms.parse_detail = parse_detail


def pdf_lines(path):
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            return [ln.strip() for page in doc for ln in page.get_text().splitlines() if ln.strip()]
    except Exception:
        return []


def certifind_outputs(out):
    cabs = json.loads((out / "cabs.json").read_text(encoding="utf-8"))
    recs, rows, scanned = [], [], 0
    for c in cabs:
        ct = c.get("contacts", {})
        get = lambda *keys: next((v for k, v in ct.items() for key in keys if key.lower() in k.lower() and v), "")
        for i, acc in enumerate(c.get("accreditations", [])):
            annex = [f for f in acc["files"] if ms.FILE_TYPES.get(f["type"]) == "scopes"]
            reg = c["reference_no"]
            recs.append({"registration_no": reg, "id": c["detail_url"], "name": c["name"], "country": c["country"],
                         "address": get("address"), "phone": get("phone", "tel"), "email": get("mail"),
                         "website": get("website", "web"), "issued": c.get("accreditation_date", ""),
                         "expiry": c.get("expiry_date", ""), "status": acc["status"], "title": acc["title"],
                         "annex_urls": [f.get("local_path", f["file_name"]) for f in annex]})
            n = 0
            for s in acc["scopes"]:
                rows.append({"registration_no": reg, "source": f"register:{acc['title']}", "row_index": n,
                             "product_text_raw": s["path"]}); n += 1
            for f in annex:
                p = out / f.get("local_path", "")
                lines = pdf_lines(p) if p.is_file() else []
                scanned += p.is_file() and not lines
                for ln in lines:
                    rows.append({"registration_no": reg, "source": f["file_name"], "row_index": n,
                                 "product_text_raw": ln}); n += 1
    (out / "egac_17065_raw.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(rows)
    print(f"Bodies: {len(cabs)}\nAccreditations: {len(recs)}\nScope lines: {len(rows)}\n"
          f"Annex PDFs without text layer: {scanned}")


def main():
    argv = sys.argv[1:]
    if "--out" not in argv:
        argv = ["--out", str(HERE / DEFAULT_OUT)] + argv
    sys.argv = [sys.argv[0]] + argv
    out = Path(argv[argv.index("--out") + 1])
    ms.main()
    certifind_outputs(out)


if __name__ == "__main__":
    main()
