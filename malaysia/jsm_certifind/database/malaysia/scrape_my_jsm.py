#!/usr/bin/env python3
"""Download JSM ACB register records and their public accreditation schedules.

Run:
  pip install requests beautifulsoup4 lxml
  python database/malaysia/scrape_my_jsm.py
"""
from __future__ import annotations
import json, logging, re, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://cab.jsm.gov.my"
SEARCH_URL = BASE + "/cab-directories/srchAcb"
RESULT_URL = BASE + "/cab-directories/resultAcb"
OUT = Path(__file__).resolve().parents[2] / "data" / "jsm-malaysia"
PDF_DIR = OUT / "pdfs"
RAW_DIR = OUT / "raw"
UA = "CertiFindResearchBot/1.0 (public register research)"
LOG = logging.getLogger("jsm_scraper")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def get_soup(url, **kwargs):
    r = SESSION.get(url, timeout=45, **kwargs)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml"), r

def form_payload(soup):
    form = soup.find("form")
    if not form:
        raise RuntimeError("Could not locate search form on JSM ACB page.")
    payload = {}
    for el in form.select("input[name], select[name], textarea[name]"):
        name = el.get("name")
        if not name: continue
        if el.name == "select":
            selected = el.find("option", selected=True) or el.find("option")
            payload[name] = selected.get("value", "") if selected else ""
        elif el.get("type") in ("checkbox", "radio"):
            if el.has_attr("checked"): payload[name] = el.get("value", "on")
        else:
            payload[name] = el.get("value", "")
    programs = []
    for sel in form.select("select"):
        label = clean(sel.find_previous(["label"]).get_text(" ", strip=True)) if sel.find_previous("label") else ""
        opts = [(o.get("value", ""), clean(o.get_text(" ", strip=True))) for o in sel.select("option") if o.get("value")]
        if any("QMS" in name or "Management" in name or "FSSC" in name or "HACCP" in name for _, name in opts):
            programs = opts
    statuses = []
    for sel in form.select("select"):
        opts = [(o.get("value", ""), clean(o.get_text(" ", strip=True))) for o in sel.select("option") if o.get("value")]
        if any(v in ("ST001","ST003","ST004","ST005") for v,_ in opts):
            statuses = opts
    return form, payload, programs, statuses

def extract_row(tr, programme, status, source_url):
    cells = tr.find_all("td", recursive=False)
    if len(cells) < 4: return None
    body_cell, prog_cell, id_cell = cells[1], cells[2], cells[3]
    link = id_cell.find("a", href=True)
    if not link: return None
    body_text = body_cell.get_text("\n", strip=True)
    lines = [clean(x) for x in body_text.splitlines() if clean(x)]
    name = lines[0] if lines else ""
    phone = email = website = ""
    mail = body_cell.select_one('a[href^="mailto:"]')
    tel = body_cell.select_one('a[href^="tel:"]')
    web = next((a for a in body_cell.select("a[href]") if a.get("href","").startswith(("http://","https://"))), None)
    if mail: email = mail.get("href","").replace("mailto:","").strip()
    if tel: phone = tel.get_text(" ", strip=True)
    if web: website = web.get("href","")
    # Remove the organisation name, contact-person labels and fax/contact metadata from address.
    address_lines = []
    for line in lines[1:]:
        low = line.lower()
        if low.startswith(("fax no:", "website:", "contact person:")): continue
        if "@" in line or re.search(r"\b\d{2,4}[- ]\d{3,}", line): continue
        address_lines.append(line)
    return {
        "name": name, "registration_no": clean(link.get_text(" ", strip=True)).replace(" ", ""),
        "programme": programme, "programme_status": status,
        "address_raw": ", ".join(address_lines), "phone": phone, "email": email,
        "website": website, "register_url": source_url,
        "proof_url": urljoin(BASE, link["href"]),
    }

def find_result_table(soup):
    for table in soup.find_all("table"):
        headers = clean(table.get_text(" ", strip=True)).lower()
        if "certification body" in headers and ("acb no" in headers or "programme" in headers):
            return table
    return None

def parse_result(soup, programme, status):
    table = find_result_table(soup)
    if not table: return []
    found = []
    for tr in table.select("tbody tr") or table.select("tr"):
        rec = extract_row(tr, programme, status, RESULT_URL)
        if rec: found.append(rec)
    return found

def submit_search(form, payload):
    action = urljoin(SEARCH_URL, form.get("action") or RESULT_URL)
    method = (form.get("method") or "get").lower()
    if method == "post":
        response = SESSION.post(action, data=payload, timeout=45)
    else:
        response = SESSION.get(action, params=payload, timeout=45)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")

def main():
    OUT.mkdir(parents=True, exist_ok=True); PDF_DIR.mkdir(exist_ok=True); RAW_DIR.mkdir(exist_ok=True)
    soup, _ = get_soup(SEARCH_URL)
    form, base_payload, programs, statuses = form_payload(soup)
    if not programs: raise RuntimeError("No programme options discovered; inspect saved HTML and update form detection.")
    if not statuses: statuses = [("ST001", "ACCREDITED")]
    LOG.info("Discovered %d programme options and %d status options", len(programs), len(statuses))
    records = {}
    raw_html = []
    for pval, pname in programs:
        for sval, sname in statuses:
            payload = dict(base_payload)
            # Set each select by identifying the select whose option list contains the selected value.
            for sel in form.select("select[name]"):
                if sel.find("option", value=pval): payload[sel["name"]] = pval
                if sel.find("option", value=sval): payload[sel["name"]] = sval
            try:
                result = submit_search(form, payload)
                raw_html.append(result.prettify())
                for rec in parse_result(result, pname, sname):
                    key = (rec["registration_no"], rec["programme"], rec["programme_status"])
                    records[key] = rec
                time.sleep(0.25)
            except Exception as exc:
                LOG.exception("Search failed for %s / %s: %s", pname, sname, exc)
    (RAW_DIR/"search_results.html").write_text("\n<!-- QUERY -->\n".join(raw_html), encoding="utf-8")
    rows = list(records.values())
    (OUT/"register_records.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    pdf_done = set()
    for rec in rows:
        url = rec["proof_url"]
        if url in pdf_done: continue
        pdf_done.add(url)
        target = PDF_DIR / f'{rec["registration_no"]}.pdf'
        if target.exists() and target.stat().st_size > 1000: continue
        try:
            r = SESSION.get(url, timeout=90); r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                LOG.warning("Not a PDF: %s (content-type %s)", url, r.headers.get("content-type"))
                continue
            target.write_bytes(r.content)
            time.sleep(0.25)
        except Exception:
            LOG.exception("PDF download failed: %s", url)
    LOG.info("Register records: %d; unique ACB IDs: %d; schedules downloaded: %d",
             len(rows), len({r['registration_no'] for r in rows}), len(list(PDF_DIR.glob('*.pdf'))))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
