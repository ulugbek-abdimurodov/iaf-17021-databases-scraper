"""TISI / NSC (Thailand) register scraper - Product Certification Bodies, ISO/IEC 17065.

Derived from ../v3/scrape_th_tisi.py (management systems). Same public endpoints:
  list:   GET /report/certificate/data_list?draw=1&start=0&length=-1&sort=CB  (JSON, DataTables)
  detail: GET /report/certificate-en?id=<b64 id>&certify=Q0I
          -> address, "Certification standard", scope dates, contact, certificate PDF + scope PDF (a.attach_pdf)
Filter: certify == 'CB' and the detail page's "Certification standard" contains 17065.
(Accreditation no. prefixes seen for 17065: PRODUCT / Product / TOURIST; TLS and GHG are not 17065.)
center.tisi.go.th serves an incomplete TLS chain, so the Windows/OS trust store is used via `truststore`.

Outputs (--out, default ./tisi_17065):
  tisi_17065_raw.json   registration_no, id, name, address, phone, email, website, issued, expiry, annex_urls, ...
  scope_lines.csv       registration_no, source, row_index, product_text_raw (PDF text layer lines)
  pdfs/<cert_no>_{cert,scope}.pdf
"""
import argparse, base64, csv, html, json, os, re, time
import truststore
truststore.inject_into_ssl()
import requests

BASE = "https://center.tisi.go.th"
HERE = os.path.dirname(os.path.abspath(__file__))


def get(s, url, tries=3, **kw):
    for i in range(tries):
        try:
            r = s.get(url, timeout=90, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_listing(s):
    data = get(s, f"{BASE}/report/certificate/data_list",
               params={"draw": 1, "start": 0, "length": -1, "sort": "CB"}).json()["data"]
    return [r for r in data if r["certify"] == "CB"]


def field(h, label):
    m = re.search(re.escape(label) + r"\s*:?\s*</p>\s*<p[^>]*>(.*?)</p>", h, re.S)
    return html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(1))).strip() if m else ""


def fetch_detail(s, url):
    h = get(s, url).text
    m = re.search(r"scope from :</p>\s*<p[^>]*>(.*?)</p>.*?to\s*</p>\s*<p[^>]*>(.*?)</p>", h, re.S)
    contact = re.search(r"Contact person :\s*</p>\s*<p[^>]*>(.*?)</p>", h, re.S)
    ct = html.unescape(re.sub(r"<br\s*/?>", "\n", contact.group(1))) if contact else ""
    ct = re.sub(r"<[^>]+>", "", ct)
    cert = re.search(r"Certificate :\s*</p>\s*<p[^>]*>\s*<a href=\"([^\"]+)\"", h)
    return {
        "name_en": field(h, "Certification"), "address": field(h, "Address"),
        "standard": field(h, "Certification standard"),
        "first": field(h, "First certified date"), "last": field(h, "Last accreditation date"),
        "scope_from": m.group(1).strip() if m else "", "scope_to": m.group(2).strip() if m else "",
        "contact": ct.strip().split("\n")[0].strip(),
        "phone": (re.search(r"(?:Telephone|Mobile phone)\s*:\s*([^\n]+)", ct) or [None, ""])[1].strip(),
        "email": (re.search(r"E-Mail\s*:\s*([^\s<]+)", ct) or [None, ""])[1].strip(),
        "cert_pdf": html.unescape(cert.group(1)) if cert else "",
        "scope_pdfs": [html.unescape(u) for u in re.findall(r'<a href="([^"]+)" class="attach_pdf"', h)],
    }


def download_pdf(s, url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        r = get(s, url)
    except requests.RequestException:
        return False
    if not r.content.startswith(b"%PDF"):
        return False
    with open(path, "wb") as f:
        f.write(r.content)
    return True


def pdf_lines(path):
    from pypdf import PdfReader
    try:
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:
        return []
    return [l.strip() for l in text.splitlines()
            if len(l.strip()) > 2 and not re.search(r"camscanner|scanned with", l, re.I)]


def main():
    ap = argparse.ArgumentParser(description="TISI/NSC Thailand - Product Certification Bodies (ISO/IEC 17065) scraper")
    ap.add_argument("--out", default=os.path.join(HERE, "tisi_17065"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    pdf_dir = os.path.join(a.out, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    s = requests.Session()

    rows = fetch_listing(s)
    recs, lines = [], []
    ok = fail = text_pdfs = 0
    for r in rows:
        url = re.search(r'href="([^"]+)"', r["action"]).group(1).replace("certificate-th", "certificate-en")
        d = fetch_detail(s, url)
        if "17065" not in d["standard"]:
            continue
        reg = r["certificate_no"]
        acc = r["accereditatio_no"].replace("หน่วยรับรอง", "").strip()
        annex = [u for u in [d["cert_pdf"], *d["scope_pdfs"]] if u]
        local = []
        if not a.no_files:
            for kind, u in [("cert", d["cert_pdf"])] + [(f"scope{i or ''}", u) for i, u in enumerate(d["scope_pdfs"])]:
                if not u:
                    continue
                path = os.path.join(pdf_dir, f"{reg}_{kind}.pdf")
                if download_pdf(s, u, path):
                    ok += 1
                    local.append(os.path.relpath(path, a.out))
                    pl = pdf_lines(path)
                    if pl:
                        text_pdfs += 1
                        lines += [[reg, f"annex:{os.path.basename(path)}", i, l] for i, l in enumerate(pl)]
                else:
                    fail += 1
        recs.append({"registration_no": reg, "accreditation_no": acc,
                     "id": base64.b64decode(re.search(r"id=([^&]+)", url).group(1) + "==").decode(errors="ignore"),
                     "name": d["name_en"] or r["name"], "name_th": r["name"], "address": d["address"],
                     "phone": d["phone"], "email": d["email"], "website": "", "contact": d["contact"],
                     "standard": d["standard"], "first_certified": d["first"], "last_accreditation": d["last"],
                     "issued": d["scope_from"], "expiry": d["scope_to"], "detail_url": url,
                     "annex_urls": annex, "annex_files": local})
        if a.limit and len(recs) >= a.limit:
            break

    json.dump(recs, open(os.path.join(a.out, "tisi_17065_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"CB rows checked: {len(rows)}  Bodies: {len({x['name_th'] for x in recs})}  Accreditations: {len(recs)}  "
          f"Scope lines: {len(lines)}")
    print(f"PDFs downloaded: {ok}  failed: {fail}  with text layer: {text_pdfs}")


if __name__ == "__main__":
    main()
