#!/usr/bin/env python3
"""TAF (Taiwan) 17065 scrape (raw/) -> certifind/data/taf-taiwan-17065.

raw/pc_bodies.txt   unitNo|name|address|phone|website|email   (accId CBA_PC_ID list)
raw/pc_scopes.txt   unitNo|originally accredited|effective from|effective to|codes
raw/pc_items.json   scope items per body (scrape_tw_taf_17065.py --items): code path names in English, English
                    comment, status. Lines: product_text = level-2 (and level-3) name + comment, scheme_text =
                    level-1 name. Only items with status A (active); terminated items are not imported.
Usage: python prepare_certifind_17065.py [raw_dir] [--today YYYY-MM-DD]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

RAW, TODAY = c.cli(HERE / "raw")
URL = "https://www.taftw.org.tw/en/find-facility/scheme/pva/"
DETAIL = "https://accreditation.taftw.org.tw/taf/public/basic/viewApplyItems.action?unitNo={}&language=EN"
dates = {}
for l in (RAW / "pc_scopes.txt").read_text(encoding="utf-8").splitlines():
    f = l.split("|")
    if len(f) >= 4:
        dates[f[0]] = (f[1].replace("/", "-"), f[3].replace("/", "-"))
items = json.loads((RAW / "pc_items.json").read_text(encoding="utf-8"))
bodies = []
for l in (RAW / "pc_bodies.txt").read_text(encoding="utf-8").splitlines():
    f = l.split("|")
    if len(f) < 6:
        continue
    unit, name, addr, tel, web, mail = f[:6]
    country = c.country_name(addr.rsplit(",", 1)[-1], "") if "," in addr else ""
    if country not in c.DIAL or country in ("", "Taiwan") or "Taiwan" in addr or "R.O.C" in addr:
        country = "Taiwan"
    issued, expiry = dates.get(unit, ("", ""))
    b = c.Body(reg=unit, name=name, country=country, phone=tel, email=mail, website=web, address=addr,
               issued=issued, expiry=expiry, proof_url=DETAIL.format(unit), source_url=URL)
    for it in items.get(unit, []):
        if it.get("status") != "A":
            continue
        prod = " - ".join(x for x in (it.get("code2EnName"), it.get("code3EnName"), it.get("fieldCodeEnName")) if x)
        comment = c.clean(it.get("enComment") or "")
        b.lines.append(c.Line(product_text=f"{prod} {comment}".strip(), scheme_text=it.get("code1EnName") or ""))
    bodies.append(b)
c.run("TAF", "taf-taiwan-17065", "taf-taiwan", URL, bodies, HERE / "taf_17065_review.md", TODAY,
      "TAF directory scheme 'pva' (ISO/IEC 17065 Product Certification Body), list JSON endpoint "
      "`cba-list-process.jsp?accId=CBA_PC_ID`, and each body's scope page (viewApplyItems, embedded item JSON). "
      "Scraper `database/taiwan/17065/scrape_tw_taf_17065.py` (then `--items`); converter `prepare_certifind_17065.py`.")
