"""Scrape SLAB (Sri Lanka) register: active 'Certification bodies - System' records -> slab_raw.tsv.
Needs network access to www.slab.lk (blocked from the build sandbox; slab_raw.tsv was captured via browser 2026-11-09)."""
import re, sys, requests
from datetime import datetime
from bs4 import BeautifulSoup
BASE = "https://www.slab.lk"
LIST = BASE + "/directory?selectedTags[1]=8&selectedStatus=active&perPage=50"
def d(s): return datetime.strptime(s, "%B %d, %Y").strftime("%Y-%m-%d")
def main(out="slab_raw.tsv"):
    s = requests.Session(); rows = []
    links = sorted({a["href"] for a in BeautifulSoup(s.get(LIST).text, "html.parser").select("a[href*='/directory/registry/']")})
    for u in links:
        h = s.get(u if u.startswith("http") else BASE + u).text
        t = re.sub(r"\s+", " ", BeautifulSoup(h, "html.parser").main.get_text(" "))
        acc = re.search(r"Accreditation Number: (\S+ \S+)", t).group(1)
        name = re.split(r"\s+-\s*\w", BeautifulSoup(h, "html.parser").find(["h1", "h2"]).get_text(strip=True))[0]
        web = (re.search(r"Official Website (\S+)", t) or [None, ""])[1]
        v = re.search(r"Period (\w+ \d+, \d{4}) to (\w+ \d+, \d{4})", t)
        scopes = list(dict.fromkeys(re.findall(r"media/file/((?:SCOPE|\d)[^\"' <]+\.pdf)", h)))
        rows.append("\t".join([acc, name, web.rstrip("/"), d(v[1]), d(v[2]), scopes[0] if scopes else ""]))
    open(out, "w").write("\n".join(rows) + "\n"); print(f"Registrations: {len(rows)}")
if __name__ == "__main__": main(*sys.argv[1:])
