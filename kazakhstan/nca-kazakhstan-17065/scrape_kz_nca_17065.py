"""Scrape Kazakhstan NCA Product Certification Bodies, ISO/IEC 17065
("Органы по подтверждению соответствия продукции / продукции и услуг", ОПС П / ОПС ПиУ).

Same register module as the MS scraper (../database/kazakhstan/kz_nca_register.py, the NCA register linked
from www.nca.kz); only the activity filter differs: fldActivityType[] = 1 (MS = 7).
Branches of one body (e.g. the NaCEkS regional branches, "Приложение N / KZ.O.01.0317") are separate rows
that share a certificate number; each row is kept, with its own contacts and scope files.

Usage:  python scrape_kz_nca_17065.py [--out nca_17065] [--limit N] [--no-files]
Output: <out>/list.json            parsed register rows, verbatim
        <out>/nca_17065_raw.json   one record per register row (CertiFind shape)
        <out>/scope_lines.csv      registration_no,source,row_index,product_text_raw  (scope annex text)
        <out>/files/<row>/<file_id>.doc|.docx|.pdf (+ .txt made by Word)
"""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "database" / "kazakhstan"))
import kz_nca_register as reg  # noqa: E402

ACTIVITY = reg.ACT_PRODUCT


def main():
    ap = argparse.ArgumentParser(description="Scrape NCA Kazakhstan product certification bodies (ISO/IEC 17065).")
    ap.add_argument("--out", default=str(HERE / "nca_17065"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = reg.fetch_list(ACTIVITY)
    print(f"register: {len(rows)} rows")
    if a.limit:
        rows = rows[:a.limit]
    (out / "list.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = failed = 0
    paths = {}
    if not a.no_files:
        for n, r in enumerate(rows, 1):
            for f in r["files"]:
                try:
                    paths[f["id"]] = reg.download(f["id"], out / "files" / r["row_no"].zfill(3), f["name"])
                    ok += 1
                except Exception as e:
                    failed += 1
                    print(f"file failed row {r['row_no']} {f['id']}: {e}")
            print(f"files {n}/{len(rows)}", flush=True)
        reg.convert_with_word(out / "files")

    raw, lines, no_text = [], [], 0
    for r in rows:
        raw.append({
            "registration_no": r["registration_no"], "id": r["row_no"], "name": r["name"],
            "branch_of": r["branch_of"], "region": r["region"], "address": r["address_block"],
            "phone": r["phone"], "email": r["email"], "website": r["website"],
            "issued": r["issued"], "expiry": r["expiry"], "status": r["status"],
            "annex_urls": [reg.file_url(f["id"]) for f in r["files"]],
            "annex_names": [f["name"] for f in r["files"]],
        })
        for f in r["files"]:
            p = paths.get(f["id"])
            if not p:
                continue
            tl = reg.text_lines(p)
            if not tl:
                no_text += 1
            lines += [(r["registration_no"], f"annex:{r['row_no']}:{f['id']}:{f['name'][:80]}", i, t)
                      for i, t in enumerate(tl)]

    (out / "nca_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"bodies={len({x['registration_no'] for x in raw})} register_rows={len(raw)} scope_lines={len(lines)} "
          f"files_ok={ok} files_failed={failed} files_without_text={no_text}")


if __name__ == "__main__":
    main()
