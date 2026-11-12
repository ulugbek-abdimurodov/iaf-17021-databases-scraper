"""Scrape CAEQ register (https://caeq.ca/accredited-organizations/) to caeq_raw.json.
Fields per card: name, address, city, zip, region, country, phone, email, website,
caeq_no, cfia_no, accreditation_date, appellations, product_categories, geo_scope."""
import json, re, sys
import requests
from bs4 import BeautifulSoup

URL = "https://caeq.ca/accredited-organizations/"
LABELS = ["ADDRESS","CITY","ZIP CODE","REGION","COUNTRY","PHONE","FAX","EMAIL","WEBSITE",
          "CAEQ CERTIFICATE NO.","CFIA ACCREDITATION NO.","ACCREDITATION DATE",
          "APPELLATION(S)","PRODUCT CATEGORIES","GEOGRAPHIC SCOPE"]

def parse(text):
    out = []
    for blk in re.split(r"\n(?=[^\n]+\n+SEE THE DETAILS)", text)[1:]:
        lines = [l.strip() for l in blk.splitlines() if l.strip() and l.strip() != "SHOW MORE"]
        rec, key = {"name": lines[0]}, None
        for l in lines[1:]:
            if l in LABELS: key = l; rec[key] = []
            elif key: rec[key].append(l)
        out.append({k: v for k, v in rec.items()})
    return out

if __name__ == "__main__":
    html = requests.get(URL, timeout=60).text
    data = parse(BeautifulSoup(html, "html.parser").get_text("\n"))
    json.dump(data, open("caeq_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Bodies scraped: {len(data)}")
