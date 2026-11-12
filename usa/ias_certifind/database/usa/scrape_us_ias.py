"""Scrape IAS (International Accreditation Service, USA) Management Systems Certification Bodies (MSCB).

Register: https://www.iasonline.org/search-accredited-organizations-2/ (program "Management Systems
Certification Bodies", service=13572). Listing pages are WordPress search results:
  /page/<n>/?post_type=ias_certificate&orderby=org&order=ASC&s=&global=1&service=13572
Each article.certs-row gives the certificate PDF link, expiry, name, city, country, status.
Each PDF (page 1: name + address; scope pages: "Certification Standard:" blocks with
"NN: sector" EA lines, "Table A1.x" IAF MD 8 areas for ISO 13485, "C: ..." ISO 22003-1 categories).

Writes raw/ias_raw.txt in the pipe format consumed by prepare_certifind.py:
  num|expiry|name|cc|status|pdf|address|website|effective|since|std~ea~md8tables~foodcats;...
(The 2026-11-10 run executed the same logic in the browser because the sandbox could not reach
iasonline.org; this script is the reproducible standalone version.)
"""
import io
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text

BASE = "https://www.iasonline.org"
Q = "?post_type=ias_certificate&orderby=org&order=ASC&s=&global=1&service=13572&number=&keyword="
OUT = Path(__file__).resolve().parents[2] / "raw" / "ias_raw.txt"
STD_ABBR = [(r"^ISO/IEC ", "I/"), (r"^ISO ", "I")]


def rng(nums):
    n = sorted(set(nums)); out = []; i = 0
    while i < len(n):
        j = i
        while j + 1 < len(n) and n[j + 1] == n[j] + 1:
            j += 1
        out.append(str(n[i]) if i == j else f"{n[i]}-{n[j]}"); i = j + 1
    return ",".join(out)


def blocks(text):
    for b in text.split("Certification Standard:")[1:]:
        b = re.split(r"Discipline of Certification|Note: The above|The above table", b)[0]
        lines = [l.strip() for l in b.splitlines()]
        std = re.sub(r"\s*:\s*(19|20)\d\d.*", "", lines[0]).replace(" - ", "-")
        for a, r in STD_ABBR:
            std = re.sub(a, r, std)
        ea = [int(m.group(1)) for l in lines if (m := re.match(r"^(\d{1,2})[a-z]?(\.\d+)?\s*:", l))]
        tb = [m.group(1) for l in lines if (m := re.search(r"Table A\.?\s*1\s*\.\s*(\d)", l))]
        lt = [m.group(1) for l in lines if (m := re.match(r"^([A-K])\s*[:–-]", l))]
        yield "~".join([std, rng(ea), ",".join(tb), ",".join(lt)]).rstrip("~")


def main():
    s = requests.Session(); rows = []; page = 1
    while True:
        url = f"{BASE}/{'' if page == 1 else f'page/{page}/'}{Q}"
        soup = BeautifulSoup(s.get(url, timeout=60).text, "html.parser")
        arts = soup.select("article.certs-row")
        if not arts:
            break
        for a in arts:
            link = a.select_one("a[href$='.pdf']")
            if not link:
                continue
            col = lambda c: a.select_one(f".column--{c} .content").get_text(" ", strip=True)
            cols = [c.get_text(" ", strip=True) for c in a.select(".column")]
            rows.append((link["href"], cols))
        page += 1
    out = []
    for pdf, cols in rows:
        t = extract_text(io.BytesIO(s.get(pdf, timeout=120).content))
        p1 = [l.strip() for l in t.split("\f")[0].splitlines() if l.strip()]
        i = next((k for k, l in enumerate(p1) if "This is to attest" in l), -1)
        j = next((k for k, l in enumerate(p1) if "Certification Body" in l), len(p1))
        addr = "; ".join(l for l in p1[i + 2:j] if "OPERATING VIRTUALLY" not in l)
        web = next((re.sub(r"\s", "", l) for l in t.splitlines() if re.search(r"www\s*\.|https?:", l, re.I)), "")
        eff = (re.search(r"Effective Date\s*([A-Za-z]+ \d+\s*,\s*\d{4})", t) or [None, ""])[1]
        since = (re.search(r"Accredited Since\s*([A-Za-z]+ \d+, \d{4})", t) or [None, ""])[1]
        strip = lambda x: re.sub(r"^(View Certificate|Expires|Organization Name|City, State|Country|Status) ?", "", x)
        c = [strip(x) for x in cols]
        st = "" if c[6] == "Accredited" else c[6]
        out.append("|".join([c[0].replace("MSCB-", ""), c[1].replace(" ", ""), c[2], c[4].split(" ")[0], st,
                             pdf.replace(BASE + "/wp-content/uploads/", ""), addr, web, eff.replace(" ", ""),
                             since.replace(" ", ""), ";".join(blocks(t))]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Registrations: {len(out)}")


if __name__ == "__main__":
    main()
