"""Scrape MNAS (Mongolia) public register https://e-accreditation.gov.mn/ for MNS ISO/IEC 17021-1 bodies.
Endpoints (public, no login): POST /ref/list {standard:3, status:0, CurrentPageNumber:n} -> HTML table rows
onclick=detail(id); POST /ref/show {id} -> detail HTML with phone/email and img[fileDir] -> PDF at <fileDir>.pdf.
Certificates are scanned images (no text layer); scope tables on page 1 were transcribed into raw_mnas.json
(retrieved 2026-11-09 via browser because the workspace egress blocks the host)."""
import json, re, sys, requests
from bs4 import BeautifulSoup
B = "https://e-accreditation.gov.mn"

def main(out="raw_mnas.json"):
    s, rows = requests.Session(), {}
    for p in range(1, 20):
        soup = BeautifulSoup(s.post(B + "/ref/list", data={"org": "", "activity": "", "status": 0, "standard": 3, "CurrentPageNumber": p}).text, "html.parser")
        new = [(re.sub(r"\D", "", tr.get("onclick", "")), [td.get_text(strip=True) for td in tr.find_all("td")]) for tr in soup.select("tbody tr")]
        new = [n for n in new if n[0] and n[0] not in rows]
        if not new: break
        rows.update(new)
    res = []
    for pid, c in rows.items():
        d = BeautifulSoup(s.post(B + "/ref/show", data={"id": pid}).text, "html.parser")
        t = d.get_text("\n")
        res.append({"id": pid, "cert": c[1], "name_mn": c[2], "issue": c[5], "expiry": c[6], "status_mn": c[7],
                    "phone": (re.search(r"Утас:\s*(.*)", t) or [None, ""])[1].strip(),
                    "email": (re.search(r"Мэйл:\s*(.*)", t) or [None, ""])[1].strip(),
                    "pdfs": [B + i["filedir"] + ".pdf" for i in d.select("img[filedir]")]})
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Registrations: {len(res)}")

if __name__ == "__main__":
    main(*sys.argv[1:])
