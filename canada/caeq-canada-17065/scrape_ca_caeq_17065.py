"""Scrape the CAEQ register (https://caeq.ca/accredited-organizations/) for ISO/IEC 17065 bodies.

Every CAEQ accreditation is product certification (organic / Québec reserved designations), so all cards
are taken. The page is server-rendered: one `.organism-item-ctn[data-slug]` card per body, holding the
label/value details and the "Show certificate" attestation PDF.

Usage: python scrape_ca_caeq_17065.py [out_dir] [saved_page.html]  (retries; never overwrites with an empty result)
Writes <out_dir>/caeq_17065_raw.json and <out_dir>/scope_lines.csv
(source = appellation | product_category | geographic_scope).
"""
import csv, json, re, sys, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = "https://caeq.ca/accredited-organizations/"
LABELS = ["ADDRESS", "CITY", "ZIP CODE", "REGION", "COUNTRY", "PHONE", "FAX", "EMAIL", "WEBSITE",
          "CAEQ CERTIFICATE NO.", "CFIA ACCREDITATION NO.", "ACCREDITATION DATE",
          "APPELLATION(S)", "PRODUCT CATEGORIES", "GEOGRAPHIC SCOPE"]
SKIP = {"SHOW MORE", "HIDE", "SEE THE DETAILS", "SHOW CERTIFICATE", "CONTACT DETAILS"}
SOURCES = {"APPELLATION(S)": "appellation", "PRODUCT CATEGORIES": "product_category", "GEOGRAPHIC SCOPE": "geographic_scope"}


def card(chunk):
    soup = BeautifulSoup(chunk, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip() and l.strip().upper() not in SKIP]
    rec, key = {"name": lines[0]}, None
    for l in lines[1:]:
        if l.upper() in LABELS:
            key = l.upper(); rec[key] = []
        elif key:
            rec[key].append(l)
    pdfs = list(dict.fromkeys(a["href"] for a in soup.select("a[href$='.pdf']")))
    return rec, pdfs


def fetch():
    for attempt in range(4):
        try:
            r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            if r.ok and "organism-item-ctn" in r.text:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(10 * (attempt + 1))
    sys.exit("CAEQ register unavailable (no body cards); previous output kept")


def main(out=".", html_file=None):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    html = Path(html_file).read_text(encoding="utf-8") if html_file else fetch()
    chunks = re.split(r'(?=<div class="organism-item-ctn)', html)[1:]
    if not chunks:
        sys.exit("No body cards found; previous output kept")
    if not html_file:
        (out / "caeq_register.html").write_text(html, encoding="utf-8")
    raw, lines = [], []
    for ch in chunks:
        slug = re.search(r'data-slug="([^"]+)"', ch).group(1)
        r, pdfs = card(ch)
        g = lambda k: " ".join(r.get(k, []))
        reg = g("CAEQ CERTIFICATE NO.") or g("CFIA ACCREDITATION NO.")
        raw.append({"registration_no": reg, "id": slug, "name": r["name"],
                    "address": ", ".join(x for x in [g("ADDRESS"), g("CITY"), g("REGION"), g("ZIP CODE")] if x),
                    "country": g("COUNTRY"), "phone": g("PHONE"), "email": g("EMAIL"), "website": g("WEBSITE"),
                    "cfia_no": g("CFIA ACCREDITATION NO."), "issued": g("ACCREDITATION DATE"), "expiry": "",
                    "annex_urls": pdfs})
        for k, src in SOURCES.items():
            for i, t in enumerate(r.get(k, []), 1):
                lines.append([reg, src, i, t, slug])
    json.dump(raw, open(out / "caeq_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "scope_lines.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["registration_no", "source", "row_index", "product_text_raw", "id"]); w.writerows(lines)
    print(f"Bodies: {len(raw)}\nScope lines: {len(lines)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
