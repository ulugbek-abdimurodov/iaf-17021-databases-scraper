"""Scrape MNAS (Mongolia) public register https://e-accreditation.gov.mn/ for Product Certification Bodies, ISO/IEC 17065.

Same endpoints as ../scrape_mn_mnas.py (management systems, standard=3). Product certification bodies are
standard=7 (certificate prefix "PC").
Endpoints (public, no login): POST /ref/list {standard:7, status:0, CurrentPageNumber:n} -> HTML table rows
onclick=detail(id); POST /ref/show {id} -> detail HTML with phone/email, an accreditation table
(number, program, standard, scope, issued, expiry) and img[fileDir] -> certificate PDF at <fileDir>.pdf.

Outputs (in --out, default this folder):
  raw_17065.json            legacy per-registration records (unchanged format)
  mnas_17065_raw.json       CertiFind records: registration_no, id, name, address, phone, email, website,
                            issued, expiry, annex_urls (+ status, org name, local pdf paths)
  scope_lines.csv           registration_no, source, row_index, product_text_raw
                            (register scope column + PDF text when the PDF has a text layer)
  pdfs/<PC_xx>_<n>.pdf      downloaded certificates (skipped if already present; --no-files to skip)
"""
import argparse, csv, json, os, re, time
import requests
from bs4 import BeautifulSoup

B = "https://e-accreditation.gov.mn"
PRODUCT_STANDARD = 7
HERE = os.path.dirname(os.path.abspath(__file__))


def post(s, path, data, tries=3):
    for i in range(tries):
        try:
            r = s.post(B + path, data=data, timeout=60)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_listing(s):
    rows = {}
    for p in range(1, 50):
        soup = BeautifulSoup(post(s, "/ref/list", {"org": "", "activity": "", "status": 0,
                                                   "standard": PRODUCT_STANDARD, "CurrentPageNumber": p}), "html.parser")
        new = [(re.sub(r"\D", "", tr.get("onclick", "")), [td.get_text(strip=True) for td in tr.find_all("td")])
               for tr in soup.select("tbody tr")]
        new = [n for n in new if n[0] and n[0] not in rows]
        if not new:
            break
        rows.update(new)
    return rows


def fetch_detail(s, pid):
    d = BeautifulSoup(post(s, "/ref/show", {"id": pid}), "html.parser")
    t = d.get_text("\n")
    field = lambda lab: (re.search(lab + r":\s*(.*)", t) or [None, ""])[1].strip()
    scopes = []
    for tr in d.select("tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) >= 4 and tds[3]:  # columns: number, program, standard, scope, issued, expiry
            scopes.append(tds[3])
    return {"org": field("Байгууллагын нэр"), "phone": field("Утас"), "email": field("Мэйл"),
            "address": field("Хаяг"), "website": field("Вэб") or field("Веб"),
            "scopes": scopes, "pdfs": [B + i["filedir"] + ".pdf" for i in d.select("img[filedir]")]}


def download_pdf(s, url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        r = s.get(url, timeout=120)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            return False
        with open(path, "wb") as f:
            f.write(r.content)
        return True
    except requests.RequestException:
        return False


def pdf_lines(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:
        return []
    # drop scanner watermarks (CamScanner etc.) so scanned-only PDFs count as having no text layer
    return [l.strip() for l in text.splitlines()
            if len(l.strip()) > 2 and not re.search(r"camscanner|scanned with", l, re.I)]


def main():
    ap = argparse.ArgumentParser(description="MNAS Mongolia - Product Certification Bodies (ISO/IEC 17065) scraper")
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pdf_dir = os.path.join(a.out, "pdfs")
    s = requests.Session()

    rows = list(fetch_listing(s).items())
    if a.limit:
        rows = rows[:a.limit]
    legacy, recs, lines = [], [], []
    ok = fail = text_pdfs = 0
    for pid, c in rows:
        det = fetch_detail(s, pid)
        reg = c[1]
        legacy.append({"id": pid, "cert": reg, "name_mn": c[2], "issue": c[5], "expiry": c[6], "status_mn": c[7],
                       "phone": det["phone"], "email": det["email"], "pdfs": det["pdfs"]})
        for i, sc in enumerate(det["scopes"]):
            lines.append([reg, "register", i, sc])
        local = []
        if not a.no_files:
            os.makedirs(pdf_dir, exist_ok=True)
            for n, url in enumerate(det["pdfs"], 1):
                path = os.path.join(pdf_dir, f"{reg.replace(' ', '_')}_{n}.pdf")
                if download_pdf(s, url, path):
                    ok += 1
                    local.append(os.path.relpath(path, a.out))
                    pl = pdf_lines(path)
                    if pl:
                        text_pdfs += 1
                        lines += [[reg, f"annex:{os.path.basename(path)}", i, l] for i, l in enumerate(pl)]
                else:
                    fail += 1
        recs.append({"registration_no": reg, "id": pid, "name": c[2], "org_name": det["org"] or c[3],
                     "address": det["address"], "phone": det["phone"], "email": det["email"],
                     "website": det["website"], "issued": c[5], "expiry": c[6], "status": c[7],
                     "program": c[4], "annex_urls": det["pdfs"], "annex_files": local})

    json.dump(legacy, open(os.path.join(a.out, "raw_17065.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(recs, open(os.path.join(a.out, "mnas_17065_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in recs})}  Accreditations: {len(recs)}  Scope lines: {len(lines)}")
    print(f"PDFs downloaded: {ok}  failed: {fail}  with text layer: {text_pdfs}")


if __name__ == "__main__":
    main()
