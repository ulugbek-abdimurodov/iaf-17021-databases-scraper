"""SCC (Canada) MS CAB scraper.
scc-ccn.ca is not reachable from the build workspace, so this script documents the
browser-side extraction that produced scc_raw.tsv (run in a scc-ccn.ca tab):
  1. GET /search/accredited-organizations?f[0]=program:496&page=0..2  (.views-row -> profile href)
  2. GET each /accreditation/management-systems/<slug>; parse main text:
     Address/City/Country/Website/Phone/File Number/Initial Accreditation Date/Expires on/
     MS Program Specialty Areas; email decoded from Cloudflare data-cfemail; scope PDF link (SOA).
  3. Emit TSV: name,addr,city,country,web,phone,file,init,exp,areas,pdf_path,slug,email
If run with network access it repeats steps 1-2 with requests.
"""
import re, sys, requests
from bs4 import BeautifulSoup
B = "https://scc-ccn.ca"
def dec(e):
    k = int(e[:2], 16); return "".join(chr(int(e[i:i+2], 16) ^ k) for i in range(2, len(e), 2))
def main(out="scc_raw.tsv"):
    s = requests.Session(); links = []
    for p in range(3):
        soup = BeautifulSoup(s.get(f"{B}/search/accredited-organizations", params={"f[0]": "program:496", "page": p}).text, "html.parser")
        links += [a["href"] for a in soup.select('.views-row a[href*="/accreditation/management-systems/"]')]
    rows = []
    for u in dict.fromkeys(links):
        soup = BeautifulSoup(s.get(u if u.startswith("http") else B + u).text, "html.parser")
        t = re.sub(r"\s+", " ", soup.select_one("main").get_text(" "))
        g = lambda a, b: (re.search(a + r" (.*?) " + b, t) or [None, ""])[1].strip()
        name = soup.select_one("h1").get_text(" ", strip=True)
        cf = soup.select_one("[data-cfemail]")
        pdf = next((a["href"] for a in soup.select("main a[href$='.pdf']")), "")
        rows.append([name, g("Contact Data Address", "(?:City|Country)"), g(" City", "Country"), g("Country", "(?:Website|Contact Person|Email|Phone|Useful)"),
                     g("Website", "(?:Contact Person|Email|Phone|Useful)"), g("Phone", "Useful"), g("File Number", "Initial"),
                     g("Initial Accreditation Date", "(?:As of|Expires)"), g("Expires on", "Program"),
                     (re.search(r"Specialty Areas (.*?)(?: Related Notices| Notices|$)", t) or [None, ""])[1].replace("Management Systems", ""),
                     pdf.split("/files/")[-1], u.rstrip("/").split("/")[-1], dec(cf["data-cfemail"]) if cf else ""])
    open(out, "w", encoding="utf-8").write("\n".join("\t".join(r) for r in rows) + "\n")
if __name__ == "__main__":
    main(*sys.argv[1:])
