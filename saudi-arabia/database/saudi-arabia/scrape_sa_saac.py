"""Scrape SAAC (Saudi Accreditation Center) management system CABs -> saac_raw.txt.

Register: https://saac.gov.sa/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Management+Systems+Certificates&page=N
Detail:   https://saac.gov.sa/en/accredited-bodies/?appid=<id lower>
Each detail page carries name, dates, email/phone/city, website link and a scope table
(IAF Code column, ISO 22000 Category column, or IAF MD8 Main Technical Areas).
Note: saac.gov.sa was fetched from a browser session (cloud egress blocked); this script is the equivalent.
"""
import re, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://saac.gov.sa"
LIST = BASE + "/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Management+Systems+Certificates&page={}"
OUT = Path(__file__).with_name("saac_raw.txt")
S = requests.Session()


def rows():
    seen = {}
    for p in range(1, 50):
        soup = BeautifulSoup(S.get(LIST.format(p), timeout=60).text, "html.parser")
        trs = soup.select("table tbody tr")
        new = 0
        for tr in trs:
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            a = tr.find("a")
            if len(c) < 7 or c[0] in seen:
                continue
            seen[c[0]] = dict(id=c[0], name=c[1], field=c[3], status=c[6], href=a["href"] if a else "")
            new += 1
        if not new:
            break
    return list(seen.values())


def detail(r):
    soup = BeautifulSoup(S.get(BASE + r["href"], timeout=60).text, "html.parser")
    t = "|".join(x.strip() for x in soup.get_text("\n").split("\n") if x.strip())
    t = t[t.find("|Certificate number|"):]
    g = lambda k: (re.search(r"\|" + k + r"\|([^|]*)", t) or [None, ""])[1]
    web = next((a["href"] for a in soup.find_all("a", href=True)
                if a["href"].startswith("http") and not re.search(r"saac|gov\.sa|twitter|x\.com|linkedin|youtube|instagram|facebook|google", a["href"])), "")
    iaf, fc, md, oth = set(), set(), [], []
    for tb in soup.find_all("table"):
        R = [[td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])] for tr in tb.find_all("tr")]
        if not R:
            continue
        h = R[0]
        ki = h.index("IAF Code") if "IAF Code" in h else -1
        kc = next((i for i, x in enumerate(h) if x in ("Category", "Food category")), -1)
        for row in R[1:]:
            if ki >= 0 and ki < len(row):
                iaf.update(int(x) for x in re.findall(r"\d+", row[ki]))
            elif kc >= 0 and kc < len(row):
                m = re.match(r"([A-K])\b", row[kc]); m and fc.add(m.group(1))
            elif h[0] == "Main Technical Areas":
                row[0] not in md and md.append(row[0])
            elif h[0] not in ("Standards", "المواصفات"):
                m = re.findall(r"IAF\s*(\d+)", " ".join(row))
                iaf.update(map(int, m)) if m else oth.append(row[1] if len(row) > 1 else "")
    return [g("Start date"), g("End date"), ",".join(map(str, sorted(iaf))), "".join(sorted(fc)), "|".join(md), "|".join(oth)], \
           [g("Email"), g("Phone"), g("Address"), re.sub(r"^https?://", "", web)]


def main():
    bodies, lines = {}, []
    for r in rows():
        d, b = detail(r)
        bi = bodies.setdefault(r["name"], (len(bodies), b))[0]
        lines.append(";;".join([r["id"], str(bi), r["field"][:45], r["status"]] + d))
    out = ["#BODIES idx;;name;;email;;phone;;city;;website"]
    out += [";;".join([str(i), n] + b) for n, (i, b) in bodies.items()]
    out += ["#CERTS id;;body;;field;;status;;start;;end;;iaf;;foodcat;;md8;;other"] + lines
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Registrations: {len(lines)} | Bodies: {len(bodies)}")


if __name__ == "__main__":
    main()
