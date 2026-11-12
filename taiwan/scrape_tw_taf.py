"""Scrape TAF (Taiwan) ISO/IEC 17021-1 management system CBs into raw/*.txt.
Directory list: https://www.taftw.org.tw/en/find-facility/scheme/msv/ (HTML, paginated, 23 CBs).
Scope per CB:  https://accreditation.taftw.org.tw/taf/public/basic/viewApplyItems.action?unitNo=<ID>&language=EN
(the scope items are embedded as JSON objects in the page: itemCode/code2EnName/status)."""
import re, sys, requests
from bs4 import BeautifulSoup

LIST = "https://www.taftw.org.tw/en/find-facility/scheme/msv/"
SCOPE = "https://accreditation.taftw.org.tw/taf/public/basic/viewApplyItems.action?unitNo={}&language=EN"
ITEM = re.compile(r'"itemCode":"([^"]*)"[\s\S]*?"status":"?([^",]*)"?')
S = requests.Session()

def bodies():
    out, page = [], 1
    while True:
        soup = BeautifulSoup(S.get(LIST, params={"page": page, "pageSize": 50}, timeout=60).text, "html.parser")
        rows = soup.select(".list-table .tr")[1:]
        if not rows:
            break
        for tr in rows:
            c = [td.get_text(" ", strip=True) for td in tr.select(".td")]
            links = [a.get("href", "") for a in tr.select("a")]
            web = next((h for h in links if h.startswith("http") and "taftw" not in h), "")
            mail = next((h[7:] for h in links if h.lower().startswith("mailto:")), "")
            out.append([c[0], c[2], c[3], c[4], web, mail])
        if len(rows) < 50:
            break
        page += 1
    return out

def scope(cid):
    html = S.get(SCOPE.format(cid), timeout=120).text
    t = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))
    oa = (re.search(r"Originally Accredited\s*[：:]\s*([\d/]+)", t) or [None, ""])[1]
    ep = re.search(r"Effective Period\s*[：:]\s*([\d/]+)\s*~\s*([\d/]+)", t)
    groups: dict[str, list[str]] = {}
    for code, st in ITEM.findall(html):
        m = re.match(r"^(0[12]|030[12]|0401|0[5-9]\d\d|0[7-9]|\d\d)(.*)$", code)
        groups.setdefault(m[1], []).append(m[2] + ("" if st == "A" else "#"))
    sc = ";".join(f"{k}:{','.join(v)}" for k, v in groups.items())
    return f"{cid}|{oa}|{ep[1] if ep else ''}|{ep[2] if ep else ''}|{sc}"

if __name__ == "__main__":
    b = bodies()
    with open("raw/msv_bodies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join("|".join(r) for r in b) + "\n")
    with open("raw/msv_scopes.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(scope(r[0]) for r in b) + "\n")
    print(f"Bodies: {len(b)}", file=sys.stderr)
