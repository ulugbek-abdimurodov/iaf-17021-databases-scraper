#!/usr/bin/env python3
"""Scrape TAF (Taiwan) ISO/IEC 17065 product certification bodies into raw/*.txt.

The TAF directory pages are Vue templates: the rows are loaded from a JSON endpoint, so the
HTML parser in scrape_tw_taf.py (management systems, 17021) finds no rows on the current site.
The product list is the same endpoint with accId=CBA_PC_ID (the product body type; the MS
scraper's type is CBA_MS_ID, 23 bodies). Scope per body is read from the same
viewApplyItems page as the MS scraper, through its scope() helper.

Output (raw/): pc_bodies.txt and pc_scopes.txt, same columns as the MS raw files (msv_bodies.txt,
msv_scopes.txt).

Usage:  python scrape_tw_taf_17065.py            # bodies + code scopes
        python scrape_tw_taf_17065.py --items    # then: item names/comments -> raw/pc_items.json
"""
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the MS scraper lives one folder up
import scrape_tw_taf as ms  # noqa: E402

LIST_JSON = "https://www.taftw.org.tw/system/modules/com.thesys.project.taf/pages/ajax/cba-list-process.jsp"
PRODUCT_ACC_ID = "CBA_PC_ID"
PAGE_SIZE = 50
RAW = HERE / "raw"


def _text(value):
    """Localised fields arrive as {"zh_TW": ..., "en": ...}; keep English, else whatever is there."""
    if isinstance(value, dict):
        return (value.get("en") or next(iter(value.values()), "") or "").strip()
    return (value or "").strip() if isinstance(value, str) else ""


def bodies():
    out, index, page_count = [], 1, 1
    while index <= page_count:
        data = ms.S.get(LIST_JSON, params={"accId": PRODUCT_ACC_ID, "lang": "en",
                                           "pageSize": PAGE_SIZE, "pageIndex": index},
                        timeout=60).json()
        if not data.get("success"):
            raise RuntimeError(f"TAF list request failed on page {index}: {str(data)[:200]}")
        page_count = data.get("pageCount", 1)
        for item in data.get("itemList", []):
            out.append([
                item.get("unitNo", ""),
                _text(item.get("unitName")),
                _text(item.get("address")),
                item.get("contactTel") or "",
                item.get("website") or "",
                item.get("contactEmail") or "",
            ])
        index += 1
    seen, unique = set(), []
    for row in out:  # the endpoint can repeat a body across pages
        if row[0] not in seen:
            seen.add(row[0])
            unique.append(row)
    return unique


if __name__ == "__main__" and "--items" not in sys.argv:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = bodies()
    (RAW / "pc_bodies.txt").write_text("\n".join("|".join(r) for r in rows) + "\n", encoding="utf-8")
    scopes = [ms.scope(r[0]) for r in rows]
    (RAW / "pc_scopes.txt").write_text("\n".join(scopes) + "\n", encoding="utf-8")
    print(f"Bodies: {len(rows)}  Scope lines: {len(scopes)}", file=sys.stderr)


# ---------------------------------------------------------------- item-level scope (names, comments, status)
def items(unit_no):
    """Every scope item of a body: code path names (EN), English comment and status, from the
    `result = {...}` JSON objects embedded in the viewApplyItems page."""
    import json
    html = ms.S.get(ms.SCOPE.format(unit_no), timeout=120).text
    dec, out, pos = json.JSONDecoder(), [], 0
    while True:
        i = html.find("result = {", pos)
        if i < 0:
            return out
        try:
            obj, end = dec.raw_decode(html, i + len("result = "))
        except ValueError:
            pos = i + 10
            continue
        pos = end
        out.append({k: obj.get(k) for k in ("itemCode", "code1EnName", "code2EnName", "code3EnName",
                                             "fieldCodeEnName", "enComment", "status")})


if __name__ == "__main__" and "--items" in sys.argv:
    import json
    rows = [l.split("|") for l in (RAW / "pc_bodies.txt").read_text(encoding="utf-8").splitlines() if l]
    data = {r[0]: items(r[0]) for r in rows}
    (RAW / "pc_items.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Items: {sum(len(v) for v in data.values())} for {len(data)} bodies", file=sys.stderr)
