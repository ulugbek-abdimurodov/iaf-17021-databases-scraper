"""Scrape ACCREDIA (Italy) ISO/IEC 17021-1 CABs.

services.accredia.it is not reachable from the build sandbox, so the scrape was run
in-browser (same requests, see below) and saved to accredia_raw.json. This script
reproduces it where the host is reachable.
Search: POST accredia_orgmask.jsp with PPSEARCH_ORG_SEARCH_MASK_STANDARDS=1 (ISO/IEC 17021-1)
Detail: GET accredia_orgmask.jsp?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG=<id>
The 'Management Systems' block lists each scheme with '(IAF Sectors|Sectors|Technical Areas|Categories|NACE Codes: ...)'.
"""
import re, json, sys, requests
from bs4 import BeautifulSoup
BASE = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp"
DETAIL = BASE + "?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG="
STD = re.compile(r"(?:(?:UNI|CEI|EN|BS) )*(?:ISO/IEC|ISO|FSSC|EN) ?\d{2,5}(?:-\d+)?")
CODES = re.compile(r"\((IAF Sectors|Sectors|Technical Areas|Categories|NACE Codes): ([^)]*)\)")

def main(out="accredia_raw_full.json"):
    s = requests.Session()
    r = s.post(BASE, data={"ID_LINK": "1733", "area": "310", "PPSEARCH_ORG_SEARCH_MASK_STANDARDS": "1", "submitBtn": "Search"})
    ids = sorted(set(re.findall(r"PPSEARCH_ORG_SEARCH_MASK_ORG=(\w+)", r.text)) - {""})
    res = []
    for i in ids:
        t = BeautifulSoup(s.get(DETAIL + i).text, "html.parser").get_text("\n")
        a = t.find("Management Systems")
        ms = t[a:t.find("Accreditation scheme:", a + 1)]
        items, last = [], 0
        for m in CODES.finditer(ms):
            stds = STD.findall(ms[last:m.start()])
            items += [[x] for x in stds[:-1]] + ([[stds[-1], m.group(1), m.group(2)]] if stds else [])
            last = m.end()
        items += [[x] for x in STD.findall(ms[last:])]
        res.append({"id": i, "text_head": t[:a], "ms": ms, "items": items})
    json.dump(res, open(out, "w"), ensure_ascii=False)

if __name__ == "__main__":
    main(*sys.argv[1:])
