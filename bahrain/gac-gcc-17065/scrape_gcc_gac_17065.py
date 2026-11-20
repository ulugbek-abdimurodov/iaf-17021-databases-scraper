"""Scrape GAC (GCC Accreditation Center) Product Certification Bodies, ISO/IEC 17065.

Same register as the MS scraper (database/gcc/scrape_gcc_gac.py, https://gac.org.sa/accredited-bodies/), but the
listing is fetched through the site's own AJAX call (cod_certifications.js):
  POST /wp-admin/admin-ajax.php action=certifications_action, page_no, status=0 (all), scopes[]=<id>
with scope ids from the page's "scopes" select:  8 = Product Certification (codes APC ####),
5 = Halal Product Certification (codes HPC ####; halal CBs are accredited to ISO/IEC 17065 + GSO 2055-2).
(The MS scraper parses only the unfiltered first page; MS = scope 4, codes MSC.)
Each card's modal (action=certifications_action, token, status) links a certificate PDF and a scope PDF.
Writes gac_17065/gac_17065_raw.json, scope_lines.csv, certificates/ and scopes/."""
import argparse, csv, json, os, re, sys
import requests, pdfplumber
from bs4 import BeautifulSoup

BASE = "https://gac.org.sa"
AJAX = BASE + "/wp-admin/admin-ajax.php"
SCOPES = {"8": "Product Certification", "5": "Halal Product Certification"}
STATUS = {"1": "Accredited", "2": "Suspended", "3": "Withdrawn", "4": "Expired"}


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def cards(s, scope):
    out, page, last = [], 1, 1
    while page <= last:
        b = BeautifulSoup(s.post(AJAX, data={"action": "certifications_action", "page_no": page, "status": 0,
                                             "country_id": "", "search_word": "", "scopes[]": scope,
                                             "from_date": "", "to_date": ""}, timeout=60).content, "html.parser")
        out += [(c["token"], c.get("status", "")) for c in b.select(".cab_details")]
        last = max([last] + [int(a["page_no"]) for a in b.select(".link_pagination") if a.get("page_no", "").isdigit()])
        page += 1
    return list(dict.fromkeys(out))


def modal(s, token, status):
    d = BeautifulSoup(s.post(AJAX, data={"action": "certifications_action", "token": token, "status": status},
                             timeout=60).content, "html.parser")
    links = [a["href"] for a in d.find_all("a", href=True)]
    valid = re.search(r"Valid Until\s*(.+?)$", d.get_text(" ", strip=True))
    return {"registration_no": clean(d.select_one(".accredited_bodies_code").get_text()),
            "name": clean(d.select_one(".title").get_text()),
            "country": clean(d.select_one(".badge_flag").get_text()) if d.select_one(".badge_flag") else "",
            "expiry": clean(valid.group(1)) if valid else "",
            "certificate": next((l for l in links if "/certificates/" in l), ""),
            "scope": next((l for l in links if "/scopes/" in l), "")}


def download(s, url, path):
    if not os.path.exists(path):  # resume
        r = s.get(url, timeout=120)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise ValueError("not a PDF")
        open(path, "wb").write(r.content)


def pdf_lines(path):
    try:
        with pdfplumber.open(path) as pdf:
            return [clean(l) for p in pdf.pages for l in (p.extract_text() or "").splitlines() if clean(l)]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description="GAC (GCC) Product Certification Bodies, ISO/IEC 17065")
    ap.add_argument("--out", default="gac_17065")
    ap.add_argument("--limit", type=int, help="bodies per scope")
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    for sub in ("certificates", "scopes"):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=5, backoff_factor=3, allowed_methods=None,
                                                      status_forcelist=[429, 500, 502, 503, 504])))
    recs, lines, ok, bad, notext = [], [], 0, 0, 0
    for sid, prog in SCOPES.items():
        cl = cards(s, sid)
        print(f"{prog}: {len(cl)} cards", file=sys.stderr)
        for token, st in cl[:a.limit]:
            try:
                m = modal(s, token, st)
            except Exception as e:
                print("Modal failed", token, e, file=sys.stderr)
                continue
            reg = m["registration_no"]
            recs.append({"registration_no": reg, "id": token, "name": m["name"], "address": m["country"],
                         "country": m["country"], "phone": "", "email": "", "website": "", "issued": "",
                         "expiry": m["expiry"], "status": STATUS.get(st, st), "program": prog,
                         "certificate_url": m["certificate"], "annex_urls": [m["scope"]] if m["scope"] else []})
            if a.no_files:
                continue
            fn = reg.replace(" ", "_")
            for kind, url in (("certificates", m["certificate"]), ("scopes", m["scope"])):
                if not url:
                    continue
                p = os.path.join(a.out, kind, f"{fn}.pdf")
                try:
                    download(s, url, p)
                    ok += 1
                except Exception as e:
                    bad += 1
                    print("PDF failed", reg, kind, e, file=sys.stderr)
                    continue
                if kind == "scopes":
                    pl = pdf_lines(p)
                    notext += not pl
                    lines += [[reg, "annex", i + 1, t] for i, t in enumerate(pl)]
    with open(os.path.join(a.out, "gac_17065_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in recs})}  accreditations: {len(recs)}  scope lines: {len(lines)}  "
          f"PDFs ok/failed: {ok}/{bad}  scope PDFs without text layer: {notext}")


if __name__ == "__main__":
    main()
