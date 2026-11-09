#!/usr/bin/env python3
"""
Cofrac management-system certification-body scraper.

Collects every certification body accredited by Cofrac (the French
accreditation body) under ISO/IEC 17021-1 (management systems), in every
country, from the public registry at https://tools.cofrac.fr/en/easysearch
plus the public suspensions/terminations/withdrawals list (rrs.php).

Read-only. No login, no writes, no CAPTCHA bypass. Public data only.

Outputs (default ./cofrac_ms_output):
  all_cases.json            everything, one entry per accreditation
  cases/<ident>.json        one file per accreditation
  bodies.csv                one row per accreditation
  scopes.csv                one row per appendix/scope pointer
  addresses.csv             listed locations
  documents/<ident>/...     certificate / technical-appendix PDFs
  documents.csv             source URL, file name, size

Usage:
  python cofrac_ms_scraper.py --out cofrac_ms_output --delay 0.6
  python cofrac_ms_scraper.py --no-pdf        # skip PDF downloads
"""
import argparse, csv, json, os, re, sys, time, html
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    sys.exit("Install dependency:  pip install requests")

BASE = "https://tools.cofrac.fr"
SEARCH_URL = BASE + "/en/easysearch/index.php"
RRS_URL = BASE + "/en/easysearch/rrs.php"
KEYWORD = '"17021-1"'          # matches all ISO/IEC 17021-1 appendices
PER_PAGE = 30

# status codes used by the suspensions/withdrawals list
ETATS = {
    "SUS": "Suspended on Cofrac's decision",
    "SUSVO": "Suspended on the body's request",
    "RESI": "Terminated by the body",
    "TRANS": "Terminated as a result of a transfer of accreditation",
    "RET": "Withdrawn",
    "RUPCYC": "Expired",
}

COUNTRY_MAP = {
    "FRANCE": "France", "MAROC": "Morocco", "ITALIE": "Italy",
    "USA": "United States", "ETATS-UNIS": "United States",
    "ESPAGNE": "Spain", "ALLEMAGNE": "Germany", "BELGIQUE": "Belgium",
    "SUISSE": "Switzerland", "TUNISIE": "Tunisia", "PORTUGAL": "Portugal",
    "LUXEMBOURG": "Luxembourg", "ROYAUME-UNI": "United Kingdom",
    "PAYS-BAS": "Netherlands",
}


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "accreditation-registry-scraper (public data)"})
    return s


def get(session, url, delay, retries=4, **kw):
    for i in range(retries):
        try:
            r = session.request(kw.pop("method", "GET"), url, timeout=40, **kw)
            if r.status_code == 200:
                time.sleep(delay)
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(delay * (2 ** i))
    raise RuntimeError(f"Failed {url}: {last}")


def search_page(session, page, delay):
    data = {
        "easykeywords": KEYWORD, "selsearch": "-1", "porteefilter": "",
        "currentPage": str(page), "selsearch0": "-1",
        "easykeywords0": KEYWORD, "activite": "", "selby": "",
    }
    return get(session, SEARCH_URL, delay, method="POST", data=data).text


def normalize_country(parts):
    if not parts:
        return ""
    last = parts[-1].strip()
    if last.upper() in COUNTRY_MAP:
        return COUNTRY_MAP[last.upper()]
    if re.match(r"^\d{5}\b", last):      # French postcode, no explicit country
        return "France"
    if re.match(r"^[A-Za-zÀ-ÿ'\- ]+$", last):
        return last[:1] + last[1:].lower()
    return ""


def parse_active(htmltext):
    out = []
    for p in htmltext.split("class=entite")[1:]:
        m = re.search(r"File\s*:\s*(\d-\d{4})", p)
        if not m:
            continue
        ident = m.group(1)
        name = clean((re.search(r"</h2>\s*<b>(.*?)</b>\s*<br", p, re.S) or [None, ""])[1])
        addr_m = re.search(r"</b><br/?>\s*(.*?)<br/?>\s*Tel\.", p, re.S)
        addr = clean(addr_m.group(1)) if addr_m else ""
        tel_m = re.search(r"Tel\.\s*:\s*(.*?)\s*\|\s*Fax\s*:\s*(.*?)<br", p, re.S)
        phone = clean(tel_m.group(1)) if tel_m else ""
        fax = clean(tel_m.group(2)) if tel_m else ""
        type_m = re.search(r"Type\s*:\s*<font[^>]*><b>(.*?)</b>", p, re.S)
        typ = clean(type_m.group(1)) if type_m else ""
        act_m = re.search(r"Activity\s*:\s*<font[^>]*><b>(.*?)</b>", p, re.S)
        activity = clean(act_m.group(1)) if act_m else ""
        parts = [x.strip() for x in addr.split("|") if x.strip()]
        out.append({
            "ident": ident, "company": name, "accreditation_name": name,
            "country": normalize_country(parts), "state": "Active",
            "standard": "ISO/IEC 17021-1" if "17021-1" in activity else "",
            "activity": activity, "type": typ, "address": addr,
            "address_parts": parts, "phone": phone, "fax": fax,
            "certificate_pdf": BASE + "/annexes/sect4/%s.pdf" % ident,
            "source_url": SEARCH_URL,
        })
    return out


def parse_rrs(htmltext):
    out = []
    for m in re.finditer(r"<tr>\s*<td class=TDA_([A-Z]+)>.*?</tr>", htmltext, re.S):
        if m.group(1) != "CERTSM":          # management systems only
            continue
        block = m.group(0)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)
        ident_m = re.search(r">(\d-\d{4})<", block)
        ident = ident_m.group(1) if ident_m else ""
        code_m = re.search(r"TDE_([A-Z]+)", block)
        code = code_m.group(1) if code_m else ""
        out.append({
            "ident": ident, "company": clean(tds[2] if len(tds) > 2 else ""),
            "accreditation_name": clean(tds[2] if len(tds) > 2 else ""),
            "country": "", "state": ETATS.get(code, code),
            "status_code": code, "standard": "ISO/IEC 17021-1",
            "activity": "Certification of management systems (ISO/IEC 17021-1)",
            "status_date": clean(tds[3] if len(tds) > 3 else ""),
            "comment": clean(tds[4] if len(tds) > 4 else ""),
            "certificate_pdf": BASE + "/Annexes/RRS/%s.pdf" % ident,
            "source_url": RRS_URL,
        })
    return out


def download_pdfs(session, cases, outdir, delay):
    docrows = []
    for c in cases:
        url = c["certificate_pdf"]
        d = os.path.join(outdir, "documents", c["ident"])
        os.makedirs(d, exist_ok=True)
        fname = c["ident"] + ".pdf"
        path = os.path.join(d, fname)
        size = ""
        try:
            r = get(session, url, delay)
            if r.content[:4] == b"%PDF":
                with open(path, "wb") as f:
                    f.write(r.content)
                size = len(r.content)
            else:
                size = "NOT_PDF"
        except Exception as e:
            size = "ERROR: %s" % e
        docrows.append({"ident": c["ident"], "source_url": url,
                        "file_name": fname, "size": size})
    return docrows


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="cofrac_ms_output")
    ap.add_argument("--delay", type=float, default=0.6)
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(os.path.join(args.out, "cases"), exist_ok=True)
    s = make_session()

    # --- active records ---
    first = search_page(s, 0, args.delay)
    tm = re.search(r"<b>(\d+)</b>\s*result", first)
    total = int(tm.group(1)) if tm else None
    pages = (total + PER_PAGE - 1) // PER_PAGE if total else 1
    active = parse_active(first)
    for pg in range(1, pages):
        active += parse_active(search_page(s, pg, args.delay))

    if total is not None and len(active) != total:
        raise SystemExit("INCOMPLETE: parsed %d of reported %d" % (len(active), total))

    # --- suspensions / terminations / withdrawals (management systems) ---
    rrs = parse_rrs(get(s, RRS_URL, args.delay).text)

    cases = active + rrs

    # all_cases.json + per-case files
    with open(os.path.join(args.out, "all_cases.json"), "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=1)
    for c in cases:
        with open(os.path.join(args.out, "cases", c["ident"] + ".json"),
                  "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)

    # bodies.csv
    bh = ["ident", "url", "company", "country", "accreditation_name", "state",
          "standard", "company_number", "address", "contact_name", "phone",
          "email", "website", "started", "renewed", "expires", "scope_entries"]
    brows = []
    for c in cases:
        brows.append({"ident": c["ident"], "url": c["certificate_pdf"],
                      "company": c["company"], "country": c["country"],
                      "accreditation_name": c["accreditation_name"],
                      "state": c["state"], "standard": c["standard"],
                      "company_number": c["ident"], "address": c.get("address", ""),
                      "phone": c.get("phone", ""), "expires": c.get("status_date", ""),
                      "scope_entries": 1})
    write_csv(os.path.join(args.out, "bodies.csv"), bh, brows)

    # scopes.csv
    sh = ["ident", "company", "country", "scheme_title", "scheme_url",
          "published", "row_type", "column1", "column2", "comment"]
    srows = [{"ident": c["ident"], "company": c["company"], "country": c["country"],
              "scheme_title": "Accreditation certificate / technical appendix",
              "scheme_url": c["certificate_pdf"], "row_type": "appendix_pdf",
              "column1": c["activity"], "column2": c.get("type", ""),
              "comment": "Full scope detailed in PDF appendix"} for c in cases]
    write_csv(os.path.join(args.out, "scopes.csv"), sh, srows)

    # addresses.csv
    ah = ["ident", "company", "country", "address_line", "locality", "raw"]
    arows = []
    for c in active:
        pp = c.get("address_parts", [])
        arows.append({"ident": c["ident"], "company": c["company"],
                      "country": c["country"], "address_line": pp[0] if pp else "",
                      "locality": pp[1] if len(pp) > 1 else "", "raw": c["address"]})
    write_csv(os.path.join(args.out, "addresses.csv"), ah, arows)

    # documents
    if args.no_pdf:
        docrows = [{"ident": c["ident"], "source_url": c["certificate_pdf"],
                    "file_name": c["ident"] + ".pdf", "size": "skipped"} for c in cases]
    else:
        docrows = download_pdfs(s, cases, args.out, args.delay)
    write_csv(os.path.join(args.out, "documents.csv"),
              ["ident", "source_url", "file_name", "size"], docrows)

    print("Active (incl. non-MS keyword hits): %d" % len(active))
    print("Management-system active: %d" % sum(1 for c in active if c["standard"]))
    print("Suspended/terminated/withdrawn (MS): %d" % len(rrs))
    cc = {}
    for c in active:
        cc[c["country"] or "(blank)"] = cc.get(c["country"] or "(blank)", 0) + 1
    print("Active by country:", cc)
    print("Output in: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
