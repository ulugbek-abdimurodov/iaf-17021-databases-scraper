"""Scrape GAC (GCC Accreditation Center) MSC register -> gac_register.txt + gac_raw.json.

The register (https://gac.org.sa/accredited-bodies/) lists CAB cards; each card's modal is
loaded via POST /wp-admin/admin-ajax.php (action=certifications_action, token, status) and
links a certificate PDF and a scope PDF on api.gac.org.sa. Scope PDFs are parsed per
"ISO xxxx:yyyy Certification" section for IAF codes (1-39) / ISO 22000 categories (A-K).
NOTE: in the original run the workspace had no egress to gac.org.sa, so the identical logic
was executed in the browser (pdf.js) and results saved to gac_raw.json.
"""
import io, json, re, sys
import requests, pdfplumber
from bs4 import BeautifulSoup

BASE = "https://gac.org.sa"

def scope_sections(text: str) -> dict:
    t = re.sub(r"\s+", " ", text)
    t = re.sub(r"/\s?Amd\s?\d\s?:\s?\d{4}", "", t)
    b = re.split(r"Log of Suspended", t, flags=re.I)[0]
    b = re.sub(r"IAF\s*MD\s*\d+", "", b); b = re.sub(r"17021\s*-\s*\d+", "", b)
    k = b.find("Scope details"); b = b[k:] if k > 0 else b
    hits = [m for m in re.finditer(r"((?:FSSC|ISO(?:/IEC)?)\s?\d{4,5}(?:-\d)?)\s?:\s?\d{4}", b)
            if not re.search(r"22003|27006|50003|17021|17065", m.group(1))]
    out = {}
    for i, m in enumerate(hits):
        seg = b[m.end(): hits[i + 1].start() if i + 1 < len(hits) else len(b)]
        seg = re.split(r"in accordance with|Note 1|\bEND\b", seg)[0]
        std = re.sub(r"(ISO|FSSC)\s?", r"\1 ", m.group(1)).strip()
        if "22000" in std:
            v = "".join(sorted(set(re.findall(r"\b([A-K])\s?[-–:]\s?[A-Z][a-z]", seg))))
        elif "13485" in std:
            v = ""
        else:
            v = ",".join(str(n) for n in sorted({int(x) for x in re.findall(r"\b(\d{1,2})\b", seg) if 1 <= int(x) <= 39}))
        out[std] = v
    return out

def main():
    s = requests.Session()
    soup = BeautifulSoup(s.get(f"{BASE}/accredited-bodies/").text, "html.parser")
    reg, raw = [], {}
    for c in soup.select(".cab_details"):
        h = s.post(f"{BASE}/wp-admin/admin-ajax.php", data={"action": "certifications_action",
                   "token": c["token"], "status": c["status"]}).text
        d = BeautifulSoup(h, "html.parser")
        code = d.select_one(".accredited_bodies_code").get_text(strip=True).replace("MSC ", "")
        links = [a["href"] for a in d.find_all("a", href=True)]
        cert = next(l for l in links if "/certificates/" in l); scope = next(l for l in links if "/scopes/" in l)
        valid = re.search(r"Valid Until\s*(.+)$", d.get_text(" ", strip=True)).group(1)
        reg.append("|".join([code, d.select_one(".title").get_text(strip=True),
                             d.select_one(".badge_flag").get_text(strip=True), valid,
                             cert.split("/")[-1][:-4], scope.split("/")[-1][:-4]]))
        with pdfplumber.open(io.BytesIO(s.get(scope).content)) as pdf:
            txt = "\n".join(p.extract_text() or "" for p in pdf.pages)
        raw[code] = {"sc": scope_sections(txt)}
    open("gac_register.txt", "w").write("\n".join(reg) + "\n")
    json.dump(raw, open("gac_raw_auto.json", "w"), indent=1)
    print(f"Bodies scraped: {len(reg)}")

if __name__ == "__main__":
    sys.exit(main())
