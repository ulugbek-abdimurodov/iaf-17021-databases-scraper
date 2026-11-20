"""SADCAS Product Certification Bodies (ISO/IEC 17065) scrape.
Register: https://www.sadcas.org/accredited-organisations/product-certification-bodies
(sibling of the MS register .../management-bodies; the site 406s default clients, so a
browser User-Agent + Referer is used). Single page table, one PDF (Cert & SoA) per body.

Outputs (default folder sadcas_17065/):
  pdfs/<accr_no>.pdf, sadcas_17065_raw.json, scope_lines.csv
Usage: python scrape_sadc_sadcas_17065.py [--limit N] [--no-files] [--out DIR]
"""
import argparse, csv, json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pypdf

BASE = "https://www.sadcas.org"
LIST_URL = BASE + "/accredited-organisations/product-certification-bodies"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
       "Referer": LIST_URL, "Accept-Language": "en"}


def get(s, url, tries=3):
    for i in range(tries):
        try:
            r = s.get(url, headers=HDR, timeout=60)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return None


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def pdf_text(path):
    rd = pypdf.PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in rd.pages)


def parse_contacts(txt):
    flat = norm(txt)
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", flat)))
    tel = re.search(r"Tel\s*:\s*(\+?[\d /]+)", flat)
    addr = re.search(r"Permanent Address of [A-Za-z]+\s*:\s*(.*?)Postal Address", flat)
    return emails, norm(tel.group(1)) if tel else "", flat, addr


def scope_lines(txt):
    """Annex lines: split after the table header on ' <IAF code> <Title>' and standard ids."""
    flat = norm(txt)
    k = flat.find("IAF CODE")
    body = flat[k:] if k >= 0 else flat
    body = re.sub(r"ANNEXURE A.*?(?=IAF CODE)", "", body)
    body = re.sub(r"IAF CODE DESCRIPTION.*?PRODUCT ", "", body, flags=re.I)
    body = re.sub(r"Page \d of \d.*?(?=Original|$)|Pinkie J Malebe.*|Victor R Mundembe.*", "", body)
    body = re.split(r"Original date of accreditation[: \w]*?\d{4}", body)
    lines = []
    for chunk in body:
        parts = re.split(r"(?=\b(?:ZS|ZWS|TZS|CXS|EN|EAS)\s?\d)", chunk)
        lines += [norm(p) for p in parts if len(norm(p)) > 8]
    return lines


def main():
    ap = argparse.ArgumentParser(description="SADCAS product certification bodies (ISO/IEC 17065)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).parent / "sadcas_17065"))
    a = ap.parse_args()
    out = Path(a.out); (out / "pdfs").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    r = get(s, LIST_URL)
    if not r:
        sys.exit("listing unreachable")
    rows = BeautifulSoup(r.text, "html.parser").select("table tr")[1:]
    if a.limit:
        rows = rows[:a.limit]
    raw, csv_rows, ok, fail = [], [], 0, 0
    for tr in rows:
        c = [norm(td.get_text()) for td in tr.find_all("td")]
        link = tr.find("a", href=re.compile(r"\.pdf", re.I))
        no = c[1]
        rec = dict(registration_no=no, id=no, name=c[0], address="", phone="", email="",
                   website="", status=c[2], issued=c[5], expiry=c[6], annex_urls=[])
        if link:
            url = urljoin(BASE, link["href"]); rec["annex_urls"] = [url]
            if not a.no_files:
                dest = out / "pdfs" / (re.sub(r"\W+", "-", no) + ".pdf")
                pr = get(s, url)
                if pr and pr.content[:4] == b"%PDF":
                    dest.write_bytes(pr.content); ok += 1
                    txt = pdf_text(dest)
                    emails, tel, flat, addr = parse_contacts(txt)
                    rec["email"] = "; ".join(emails); rec["phone"] = tel
                    if addr: rec["address"] = norm(addr.group(1))
                    for n, l in enumerate(scope_lines(txt)):
                        csv_rows.append([no, "annex", n, l])
                else:
                    fail += 1
        raw.append(rec)
    (out / "sadcas_17065_raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), "utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(csv_rows)
    print(f"bodies={len(raw)} accreditations={len(raw)} scope_lines={len(csv_rows)} pdf_ok={ok} pdf_fail={fail}")


if __name__ == "__main__":
    main()
