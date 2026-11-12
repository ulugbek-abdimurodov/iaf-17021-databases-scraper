"""Scrape KAB (Korea Accreditation Board) management-system CB register into kab_raw.txt.

eng.kab.or.kr is not reachable from the build sandbox, so the data was captured with
the same logic in the browser (same-origin fetch of /eng/kcn/kcn/view.do?orgIdx=<id>).
Run this locally where the site is reachable to refresh kab_raw.txt.
"""
import re, requests
from bs4 import BeautifulSoup

BASE = "https://eng.kab.or.kr"
LIST = BASE + "/eng/kcn/kcn/list.do"


def ea_compress(text):
    nums = sorted({int(n) for n in re.findall(r"\d+", text) if 1 <= int(n) <= 39})
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ";".join(out)


def main():
    s = requests.Session()
    soup = BeautifulSoup(s.get(LIST).text, "html.parser")
    ids = [re.search(r"orgIdx=(\d+)", tr["onclick"]).group(1)
           for tr in soup.select("table tbody tr[onclick]")]
    lines = []
    for oid in ids:
        d = BeautifulSoup(s.get(f"{BASE}/eng/kcn/kcn/view.do", params={"orgIdx": oid, "menuNo": "500044"}).text, "html.parser")
        g = lambda k: next((dt.find_next_sibling("dd").get_text(" ", strip=True) for dt in d.find_all("dt") if dt.get_text(strip=True) == k), "")
        head = re.search(r"인증기관현황\s*(.*?)General Information", d.get_text(" "), re.S).group(1)
        head = " ".join(head.split())
        abbr = re.search(r"\[(.*?)\]", head).group(1)
        name = re.sub(r"^.*?\]\s*", "", head)
        web = g("Web").replace("http://www.", "w:")
        addr = re.sub(r",\s*(Republic of )?Korea$", "", g("Head Office"))
        lines.append("|".join(["B", oid, name, abbr, g("Phone"), web, addr]))
        for sec in d.select(".org-detail-sec .section"):
            if not sec.select_one("img[onclick]"):
                continue
            title = re.sub(r"\s*\(.*$", "", sec.select_one(".title").get_text(strip=True))
            dd = [x.get_text(" ", strip=True) for x in sec.find_all("dd")]
            m = re.search(r"(\S+)\s*\((\d{4}-\d\d-\d\d)\)", dd[0])
            scope = re.sub(r"[^\x20-\x7eⅠⅡⅢⅣ]", "", dd[2] if len(dd) > 2 else "").replace(" ", "")
            if re.match(r"^\(\d", scope):
                scope = "#" + ea_compress(scope)
            lines.append("|".join([title.replace("ISO ", ""), m.group(1).replace("KAB-", ""), m.group(2), "", scope]))
    open("kab_raw.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
