"""Scrape ISMS-AC (Japan) registers of accredited management system CBs.
Writes raw_bodies.tsv and raw_accreditations.csv (scheme,reg_no,body_idx,accr_date)."""
import re, requests
from datetime import datetime
from bs4 import BeautifulSoup

BASE = "https://isms.jp"
PAGES = {"ISMS": "/english/lst/isr/isr.html", "ITSMS": "/english/itsms/lst/isr/isr.html",
         "BCMS": "/english/bcms/lst/isr/isr.html", "AIMS": "/english/aims/lst/isr/isr.html",
         "PIMS": "/english/pims/lst/isr/isr.html", "CLS": "/english/lst/isr/isr-ismscls.html",
         "ISPIMS": "/english/lst/isr/isr-ismspims.html"}

def main():
    bodies, idx, accs = [], {}, []
    for scheme, path in PAGES.items():
        soup = BeautifulSoup(requests.get(BASE + path, timeout=30).content, "html.parser")
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3 or not re.match(r"^[A-Z]{2,}\d", tds[0].get_text(strip=True)):
                continue
            lines = [l.strip() for l in tds[1].get_text("\n").split("\n") if l.strip()]
            name = re.sub(r"\s+", " ", lines[0]); a = tds[1].find("a")
            key = re.sub(r"\W", "", name.lower())
            if key not in idx:
                idx[key] = len(bodies)
                bodies.append([name, " ".join(lines[1:]), a["href"] if a else ""])
            d = datetime.strptime(tds[2].get_text(strip=True), "%d %B %Y").date()
            accs.append(f"{scheme},{tds[0].get_text(strip=True)},{idx[key]},{d}")
    open("raw_bodies.tsv", "w").write("\n".join("\t".join(b) for b in bodies) + "\n")
    open("raw_accreditations.csv", "w").write("\n".join(accs) + "\n")

if __name__ == "__main__":
    main()
