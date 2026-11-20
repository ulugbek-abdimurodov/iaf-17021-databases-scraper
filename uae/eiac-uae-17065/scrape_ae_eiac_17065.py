"""EIAC (UAE) register scraper - Product Certification Bodies, ISO/IEC 17065.

Derived from ../database/uae/scrape_ae_eiac.py (management systems, browser JS). The same endpoints are now
reachable from the shell, so this is plain Python:
  directory: GET https://eiac.gov.ae/directory/  (all ~970 cards server-rendered; filter main field below)
  detail:    GET <card href> (301 -> /directory-details/?tc=..&ID=..; retried on "There Are No Data")
             -> address, PO box, email, website, phone, initial/valid-since dates and the scope table
             (Certification Type/Scheme | Product Category | Type of Product | Applicable Standard | Status)
  pdf:       GET https://accreditation.eiac.gov.ae/api/return_pdf_file?file_name=<a.download-pdf data-file>
             certificate + scope (text layer; "Validity:" gives the expiry)
Filter: main field == "CB Products certification" (accreditation no. CB-PRD-xxx). The MS scraper used /Management/.

Outputs (--out, default ./eiac_17065):
  eiac_17065_raw.json  registration_no, id, name, address, phone, email, website, issued, expiry, annex_urls, ...
  scope_lines.csv      registration_no, source, row_index, product_text_raw
                       (source "register": scheme | category | product | standards | status; "annex:<pdf>": PDF lines)
  pdfs/<CB-PRD-xxx>.pdf
"""
import argparse, csv, html, json, os, re, time
import requests
from bs4 import BeautifulSoup

DIRECTORY = "https://eiac.gov.ae/directory/"
PDF_API = "https://accreditation.eiac.gov.ae/api/return_pdf_file?file_name="
PRODUCT_FIELD = "CB Products certification"
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0"}


def get(s, url, tries=4):
    for i in range(tries):
        try:
            r = s.get(url, timeout=90, headers=UA)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_listing(s):
    soup = BeautifulSoup(get(s, DIRECTORY).text, "html.parser")
    out = []
    for card in soup.select("div.card"):
        a = card.select_one("a[href*=directory-details]")
        p = a and a.find_next("p")
        if not a or not p or p.get_text(strip=True) != PRODUCT_FIELD:
            continue
        acc = card.find("p", string=re.compile("Accreditation No"))
        acc = card.select_one(".creation p span")
        status = card.select_one(".status-badge")
        loc = card.select_one(".location p")
        out.append({"name": a.get_text(strip=True), "href": a["href"],
                    "accreditation_no": acc.get_text(strip=True) if acc else "",
                    "status": status.get_text(strip=True) if status else "",
                    "location": re.sub(r"\s+", " ", loc.get_text(" ", strip=True)) if loc else ""})
    return out


def table_rows(table):
    """Expand rowspan/colspan into a grid of cell texts (body rows only)."""
    grid, pending = [], {}
    for tr in table.find_all("tr"):
        if tr.find("th"):
            continue
        row, col = [], 0
        cells = tr.find_all("td", recursive=False)
        ci = 0
        while ci < len(cells) or col in pending:
            if col in pending:
                txt, left = pending[col]
                row.append(txt)
                pending[col] = (txt, left - 1) if left > 1 else None
                if pending[col] is None:
                    del pending[col]
                col += 1
                continue
            td = cells[ci]; ci += 1
            txt = re.sub(r"\s+", " ", td.get_text(" ", strip=True))
            span, cs = int(td.get("rowspan", 1)), int(td.get("colspan", 1))
            for _ in range(cs):
                if span > 1:
                    pending[col] = (txt, span - 1)
                row.append(txt); col += 1
        grid.append(row)
    return grid


def fetch_detail(s, url):
    for k in range(6):
        h = get(s, url).text
        if "Main Field" in h:
            break
        time.sleep(1.5)
    soup = BeautifulSoup(h, "html.parser")
    tx = re.sub(r"\s+", " ", soup.get_text(" "))
    # only the header/contact block: from "Directory Details" up to the scope table (avoids footer words like "Website")
    i = tx.rfind("Directory Details")
    tx = tx[i if i >= 0 else 0:]
    tx = tx[:tx.find("Certification Type/Scheme")] if "Certification Type/Scheme" in tx else tx[:4000]
    labels = r"(?:Initial Accreditation Date:|Contacts Info|Address|PO box / Zip Code|Email|Website|Phone No\.|Mobile No\.|Main Field|Valid Since:|Download Certificate|Terms & Conditions)"

    def g(label, _unused=None):
        m = re.search(label + r" ?(.*?) ?(?=" + labels + "|$)", tx)
        v = m.group(1).strip() if m else ""
        return "" if v.lower() in ("undefined", "null", "-") else v
    pdf = soup.select_one(".download-pdf")
    scope = []
    for t in soup.find_all("table"):
        if "Certification Type/Scheme" not in t.get_text():
            continue
        for r in table_rows(t):
            if len(set(r)) == 1 and r[0]:
                scope.append(r[0])  # full-width section header, e.g. "Product Certification based on ISO/ IEC 17065"
            elif len(r) >= 5:
                scope.append(" | ".join(x for x in r[:5]))
    return {"address": g("Address"), "po_box": g("PO box / Zip Code"), "email": g("Email"),
            "website": g("Website"), "phone": " / ".join(x for x in (g(r"Phone No\."), g(r"Mobile No\.")) if x),
            "initial": g("Initial Accreditation Date:"), "valid_since": g("Valid Since:"),
            "main_field": g("Main Field"),
            "pdf_file": pdf["data-file"] if pdf else "", "scope": scope}


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


def pdf_text(path):
    from pypdf import PdfReader
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="EIAC UAE - Product Certification Bodies (ISO/IEC 17065) scraper")
    ap.add_argument("--out", default=os.path.join(HERE, "eiac_17065"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    pdf_dir = os.path.join(a.out, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    s = requests.Session()

    rows = fetch_listing(s)
    print(f"Directory cards with main field '{PRODUCT_FIELD}': {len(rows)}")
    if a.limit:
        rows = rows[:a.limit]
    recs, lines = [], []
    ok = fail = text_pdfs = 0
    for r in rows:
        d = fetch_detail(s, r["href"])
        reg = r["accreditation_no"] or os.path.splitext(d["pdf_file"])[0]
        lines += [[reg, "register", i, x] for i, x in enumerate(d["scope"])]
        pdf_url = PDF_API + requests.utils.quote(d["pdf_file"]) if d["pdf_file"] else ""
        local, validity = [], ""
        if pdf_url and not a.no_files:
            path = os.path.join(pdf_dir, f"{reg}.pdf")
            if download_pdf(s, pdf_url, path):
                ok += 1
                local.append(os.path.relpath(path, a.out))
                t = pdf_text(path)
                validity = (re.search(r"Validity:\s*([^\n]*)", t) or [None, ""])[1].strip()
                pl = [l.strip() for l in t.splitlines() if len(l.strip()) > 2]
                if pl:
                    text_pdfs += 1
                    lines += [[reg, f"annex:{reg}.pdf", i, l] for i, l in enumerate(pl)]
            else:
                fail += 1
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}|\w+ \d{1,2},? \d{4}) *(?:to|-|–) *(\d{1,2}/\d{1,2}/\d{4}|\w+ \d{1,2},? \d{4})", validity)
        recs.append({"registration_no": reg, "id": (re.search(r"ID=(\d+)", r["href"]) or [None, ""])[1],
                     "name": r["name"], "address": d["address"] or r["location"], "po_box": d["po_box"],
                     "phone": d["phone"], "email": d["email"], "website": d["website"],
                     "initial_accreditation": d["initial"], "issued": d["valid_since"],
                     "expiry": m.group(2) if m else "", "validity_raw": validity,
                     "status": r["status"], "main_field": d["main_field"], "detail_url": r["href"],
                     "annex_urls": [pdf_url] if pdf_url else [], "annex_files": local})

    json.dump(recs, open(os.path.join(a.out, "eiac_17065_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    reg_lines = sum(1 for l in lines if l[1] == "register")
    print(f"Bodies: {len({x['name'] for x in recs})}  Accreditations: {len(recs)}  "
          f"Scope lines: {len(lines)} (register {reg_lines}, annex {len(lines) - reg_lines})")
    print(f"PDFs downloaded: {ok}  failed: {fail}  with text layer: {text_pdfs}")


if __name__ == "__main__":
    main()
