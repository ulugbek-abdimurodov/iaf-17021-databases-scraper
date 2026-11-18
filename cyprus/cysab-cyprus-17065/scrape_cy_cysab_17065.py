"""Scrape CYS-CYSAB (Cyprus) ISO/IEC 17065 product certification bodies -> raw JSON + scope_lines.csv.

Register: https://www.gov.cy/meci-cysab/documents/diapisteymenoi-foreis/  (one DataTables <table>, all rows in HTML)
Columns: Αριθμός Πιστοποιητικού | Όνομα (+ τηλ.) | Τομέας | Πρότυπο | Ημερομηνία Διαπίστευσης | Πεδίο Εφαρμογής (PDF) | Σχόλια
17065 rows: Πρότυπο contains "17065"; registration numbers ΦΠ0NN[-rev].
gov.cy sits behind an Azure WAF JS challenge: if a download returns HTML instead of PDF, save the page
as <out>/register.html and the annexes as <out>/pdf/<ΦΠxxx>.pdf from a browser, then re-run (cache is reused).

Usage: python scrape_cy_cysab_17065.py [out_dir]   (default cysab_17065)
"""
import csv, json, logging, re, sys
from datetime import datetime
from pathlib import Path

import pdfplumber, requests
from bs4 import BeautifulSoup

REGISTER = "https://www.gov.cy/meci-cysab/documents/diapisteymenoi-foreis/"
UA = {"User-Agent": "Mozilla/5.0 CertiFind-scraper"}
COLS = ["registration_no", "source", "page", "row_index", "product_text_raw"]
WS = re.compile(r"\s+")
PAGE_NO = re.compile(r"^(σελίδα|σελ\.|page)?\s*\d+\s*(/|από|of)\s*\d+$", re.I)
PHONE = re.compile(r"τηλ\.?:?\s*([+\d][\d\s\-]{6,})", re.I)
log = logging.getLogger("cysab17065")


def clean(t):
    return WS.sub(" ", t or "").strip()


def iso(d):
    try:
        return datetime.strptime(clean(d), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def get(s, url, path, binary=False):
    """Cached GET; returns None (and logs) when the WAF challenge comes back instead of content."""
    if path.exists():
        return path.read_bytes() if binary else path.read_text(encoding="utf-8")
    try:
        r = s.get(url, timeout=60)
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
        return None
    if r.status_code != 200 or (binary and not r.content.startswith(b"%PDF")) or "Azure WAF" in r.text[:2000]:
        log.warning("GET %s blocked (HTTP %s / WAF) - save it manually to %s", url, r.status_code, path)
        return None
    path.write_bytes(r.content) if binary else path.write_text(r.text, encoding="utf-8")
    return r.content if binary else r.text


# ---------------------------------------------------------------- register
def fetch(out):
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(UA)
    page = get(s, REGISTER, out / "register.html")
    if page is None:
        sys.exit(f"Register blocked by WAF: save {REGISTER} as {out / 'register.html'} and re-run")
    bodies = []
    for tr in BeautifulSoup(page, "html.parser").select("table tbody tr"):
        td = tr.find_all("td")
        if len(td) < 6 or "17065" not in td[3].get_text():
            continue
        reg = clean(td[0].get_text()).replace(" ", "")
        name_cell = clean(td[1].get_text(" "))
        m = PHONE.search(name_cell)
        name = clean(PHONE.sub("", name_cell)).rstrip(" ,")
        urls = [a["href"] for a in td[5].find_all("a", href=True)]
        bodies.append({
            "registration_no": reg, "id": reg.split("-")[0], "name": name,
            "address": "", "phone": clean(m.group(1)) if m else "", "email": "", "website": "",
            "sector": clean(td[2].get_text(" ")), "standard": clean(td[3].get_text(" ")),
            "issued": iso(td[4].get_text()), "expiry": "",
            "comments": clean(td[6].get_text(" ")) if len(td) > 6 else "",
            "annex_urls": urls,
        })
    for b in bodies:
        b["annex_files"] = []
        for k, u in enumerate(b["annex_urls"], 1):
            fn = f"{b['id']}{'' if k == 1 else f'_{k}'}.pdf"
            if get(s, u, out / "pdf" / fn, binary=True) is not None:
                b["annex_files"].append(fn)
    json.dump(bodies, open(out / "cysab_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return bodies


# ---------------------------------------------------------------- annexes
def is_continuation(prev, line):
    if not prev:
        return False
    if re.match(r"^[a-zα-ωά-ώ(\)\],;.:/&]", line) and not re.match(r"^[a-zα-ω]\)\s", line):
        return True
    if prev.endswith((",", "-", "–", "/", "(", " και", " and", " of", " για", " του", " της", " των")):
        return True
    return prev.count("(") > prev.count(")")


def pdf_lines(path):
    """Yield (page, text): table rows joined with ' | ', other text line by line, top-to-bottom per page."""
    with pdfplumber.open(path) as pdf:
        for pno, p in enumerate(pdf.pages, 1):
            items, tables = [], p.find_tables()
            for t in tables:
                for row, texts in zip(t.rows, t.extract()):
                    cells = [clean(x) for x in texts if clean(x)]
                    if cells:
                        items.append((row.bbox[1], " | ".join(cells)))
            outside = p
            for t in tables:
                outside = outside.filter(lambda o, b=t.bbox: not (b[0] - 1 <= o.get("x0", -9) and o.get("x1", 9e9) <= b[2] + 1
                                                                  and b[1] - 1 <= o.get("top", -9) and o.get("bottom", 9e9) <= b[3] + 1))
            for ln in outside.extract_text_lines():
                t = clean(ln["text"])
                if t and not PAGE_NO.match(t):
                    items.append((ln["top"], t))
            for _, t in sorted(items, key=lambda x: x[0]):
                yield pno, t


def scope_lines(body, out):
    rows = []
    for fn in body["annex_files"]:
        pending = None
        for pno, t in pdf_lines(out / "pdf" / fn):
            if pending and "|" not in t and "|" not in pending["product_text_raw"] and is_continuation(pending["product_text_raw"], t):
                pending["product_text_raw"] += " " + t
                continue
            if pending:
                rows.append(pending)
            pending = {"source": fn, "page": pno, "product_text_raw": t}
        if pending:
            rows.append(pending)
        if not body["expiry"]:  # "Ημερομηνία Λήξης / Expiry date: dd/mm/yyyy" on the certificate page
            txt = " ".join(r["product_text_raw"] for r in rows[:40])
            m = re.search(r"(λήξη|ισχύ\w* έως|valid until|expiry)\D{0,40}(\d{2}/\d{2}/\d{4})", txt, re.I)
            if m:
                body["expiry"] = iso(m.group(2))
    for i, r in enumerate(rows, 1):
        r["registration_no"], r["row_index"] = body["registration_no"], i
    return rows


def main(out_dir="cysab_17065"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=out / "scrape_17065.log", filemode="w", level=logging.INFO,
                        format="%(levelname)s %(message)s")
    bodies = fetch(out)
    total, zero = 0, []
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        for b in bodies:
            rows = scope_lines(b, out)
            w.writerows(rows)
            total += len(rows)
            if not rows:
                zero.append(b["registration_no"])
                log.warning("reg %s: ZERO scope lines (annex missing?)", b["registration_no"])
    json.dump(bodies, open(out / "cysab_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Bodies: {len(bodies)}\nAnnexes: {sum(len(b['annex_files']) for b in bodies)}\n"
          f"Scope lines: {total}\nZero-line bodies: {len(zero)} {' '.join(zero)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
