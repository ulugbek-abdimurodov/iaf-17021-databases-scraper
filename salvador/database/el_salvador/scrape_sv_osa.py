"""Scrape OSA (El Salvador) accredited certification bodies (ISO/IEC 17021-1) and their scope PDFs."""
import json, re, subprocess, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://www.osa.gob.sv"
LIST = f"{BASE}/organismos-de-certificacion-acreditados/"
OUT = Path(__file__).parent / "raw"

def main():
    OUT.mkdir(exist_ok=True)
    s = requests.Session()
    soup = BeautifulSoup(s.get(LIST, timeout=60).text, "html.parser")
    recs = []
    for a in soup.select("article a[href*='wpdmdl']"):
        slug = a["href"].split("/descarga/")[1].split("/")[0]
        pdf = OUT / f"{slug}.pdf"
        pdf.write_bytes(s.get(a["href"], timeout=120).content)
        txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        (OUT / f"{slug}.txt").write_text(txt, encoding="utf-8")
        recs.append({"slug": slug, "page": f"{BASE}/descarga/{slug}/", "pdf": a["href"].split("?")[0]})
    (OUT / "index.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")
    print(f"PDFs: {len(recs)}")

if __name__ == "__main__":
    main()
