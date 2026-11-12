"""ONAC (Colombia) CSG register scraper.

onac.org.co is not reachable from the build workspace, so the scrape runs in a
browser session (same-origin fetch + pdf.js) and the result is stored in
onac_raw.tsv. This script documents/replays that procedure where the site is
reachable: DOA search (esquema=CSG) -> detail page -> scope certificate PDF.
"""
import re, sys, requests, pdfplumber, io
from bs4 import BeautifulSoup

BASE = "https://onac.org.co"
SEARCH = BASE + "/directorio3/index.php/buscador/resultado_busqueda_empresa?lang=es"
DETAIL = BASE + "/directorio3/index.php/acreditaciones/{}"
PDF = BASE + "/certificados/{}.pdf"


def list_csg(s):
    html = s.post(SEARCH, data={"esquema": "CSG", "tipoEsquema": "1"}).text
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.select("#resultado_busqueda tbody tr"):
        td = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        yield {"name": td[0], "code": td[3], "status": td[4], "city": td[5]}


def scope_lines(s, code):
    with pdfplumber.open(io.BytesIO(s.get(PDF.format(code)).content)) as pdf:
        txt = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"Alcance de la acreditaci.*?(?=Sitios cubiertos)", txt, re.S)
    return m.group(0) if m else ""


if __name__ == "__main__":
    s = requests.Session()
    for b in list_csg(s):
        d = BeautifulSoup(s.get(DETAIL.format(b["code"])).text, "html.parser").get_text(" ", strip=True)
        b["dates"] = re.findall(r"Fecha[^:]*: (\d{4}-\d\d-\d\d)", d)
        b["scope"] = scope_lines(s, b["code"])
        print(b["code"], b["name"], file=sys.stderr)
