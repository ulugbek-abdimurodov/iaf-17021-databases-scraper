"""Scrape KENAS (Kenya) register: management system CBs + schedule PDFs.
Register: https://kenas.go.ke/status (server-rendered cards). Falls back to register_snapshot.json
(captured via browser on 2026-11-09) when kenas.go.ke is unreachable."""
import json, re, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
URL = "https://kenas.go.ke/status"

def scrape():
    html = requests.get(URL, timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", string=re.compile("GET SCHEDULE")):
        card = a
        while card and "KENAS/" not in card.get_text():
            card = card.parent
        lines = [l.strip() for l in card.get_text("\n").split("\n") if l.strip()]
        if "Management System" not in " ".join(lines):
            continue
        m = re.search(r"https?://(?:(?!https?:).)*?\.pdf", a["href"])  # hrefs concatenate several URLs
        out.append({"id": lines[0], "name": lines[1], "address": lines[2],
                    "expiry_raw": lines[lines.index("Expiry Date/Status") + 1],
                    "schedule": m.group(0) if m else a["href"]})
    return out

def main():
    try:
        rows = scrape()
    except Exception:
        rows = json.loads((HERE / "register_snapshot.json").read_text())
    pdir = HERE / "pdfs"; pdir.mkdir(exist_ok=True)
    got = 0
    for r in rows:
        f = pdir / (re.sub(r"\W", "_", r["id"]) + ".pdf")
        try:
            b = requests.get(r["schedule"], timeout=60).content
            if b[:4] == b"%PDF":
                f.write_bytes(b); got += 1
        except Exception:
            pass
    (HERE / "register.json").write_text(json.dumps(rows, indent=1))
    print(f"Registrations: {len(rows)} | Schedule PDFs: {got}")

if __name__ == "__main__":
    main()
