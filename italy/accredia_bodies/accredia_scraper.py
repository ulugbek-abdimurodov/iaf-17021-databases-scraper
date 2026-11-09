#!/usr/bin/env python3
"""
Accredia scraper  ->  PDFs + V3__seed_accredia_data.sql  (matches V1/V2 schema)

Phases (all resumable, results cached under --out):
  ids       collect company IDs from the search result list
  crawl     for every company: fetch page, parse, download ALL certificate PDFs
  scopes    (optional) derive ISO 9001/14001/45001/27001 x EA-sector scopes by
            replaying the site's own search filters
  sql       generate V3__seed_accredia_data.sql from the cached data
  all       ids + crawl + scopes + sql

Examples:
  python accredia_scraper.py ids
  python accredia_scraper.py crawl --limit 5          # smoke test
  python accredia_scraper.py scopes --discover        # print filter options, then verify
  python accredia_scraper.py all

Requires: pip install requests beautifulsoup4 pypdf
"""
import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from pypdf import PdfReader
except ImportError:  # page_count / is_scanned will be NULL / FALSE
    PdfReader = None

BASE = "https://services.accredia.it/ppsearch/accredia_orgmask.jsp"
BASE_PARAMS = {"ID_LINK": "1733", "area": "310"}
PAGE_URL = BASE + "?ID_LINK=1733&area=310&PPSEARCH_ORG_SEARCH_MASK_ORG={id}"
ORG_RE = re.compile(r"PPSEARCH_ORG_SEARCH_MASK_ORG=(\d+)")
DATE_RE = r"(\d{2}/\d{2}/\d{4})"
EXPECTED_COMPANIES = 738

# Accredia "Norma" -> accreditation standard code in V2 seed
STD_MAP = [
    (r"17021(?!-[2-9])", "ISO/IEC 17021-1"),
    (r"17065", "ISO/IEC 17065"),
    (r"17024", "ISO/IEC 17024"),
    (r"17025", "ISO/IEC 17025"),
    (r"15189", "ISO 15189"),
    (r"17020", "ISO/IEC 17020"),
]
# Certification standards available in the V2 seed
CERT_STD_MAP = {
    "9001": "ISO 9001",
    "14001": "ISO 14001",
    "45001": "ISO 45001",
    "27001": "ISO/IEC 27001",
}
LEGAL_TOKENS = {"srl", "srls", "spa", "snc", "sas", "sapa", "scarl", "scrl",
                "scpa", "sca", "rl", "ltd", "gmbh"}

log = logging.getLogger("accredia")


# ----------------------------------------------------------------- HTTP
class Http:
    def __init__(self, delay: float):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; CB-Finder-DataPrep/1.0; internal use)")
        retry = Retry(total=5, backoff_factor=2,
                      status_forcelist=(429, 500, 502, 503, 504))
        self.s.mount("https://", HTTPAdapter(max_retries=retry))
        self._last = 0.0

    def _wait(self):
        dt = time.time() - self._last
        if dt < self.delay:
            time.sleep(self.delay - dt)
        self._last = time.time()

    def get(self, url, params=None, **kw):
        self._wait()
        r = self.s.get(url, params=params, timeout=60, **kw)
        r.raise_for_status()
        return r


def soup_of(resp) -> BeautifulSoup:
    enc = (resp.encoding or "").lower()
    if enc in ("iso-8859-1", "latin-1", ""):
        enc = "cp1252"  # superset; page declares ISO-8859-1
    return BeautifulSoup(resp.content, "html.parser", from_encoding=enc)


# ------------------------------------------------------------ phase: ids
def ids_from_soup(soup, ids: "OrderedDict[str, str]"):
    for a in soup.find_all("a", href=True):
        m = ORG_RE.search(a["href"])
        if m:
            ids.setdefault(m.group(1), a.get_text(" ", strip=True))


def collect_ids(http: Http, params=None, max_pages=300):
    """Collect company IDs from a result list, following pagination links."""
    ids: "OrderedDict[str, str]" = OrderedDict()
    queue = [(BASE, params)]
    visited = set()
    pager = re.compile(r"^(\d+|»|›|>|>>|succ\w*|avanti|next)$", re.I)
    while queue and len(visited) < max_pages:
        url, p = queue.pop(0)
        r = http.get(url, params=p)
        if r.url in visited:
            continue
        visited.add(r.url)
        soup = soup_of(r)
        before = len(ids)
        ids_from_soup(soup, ids)
        log.info("list page %s: +%d ids (total %d)", len(visited),
                 len(ids) - before, len(ids))
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"])
            if ("accredia_orgmask.jsp" in href and not ORG_RE.search(href)
                    and pager.match(a.get_text(strip=True))
                    and href not in visited and (href, None) not in queue):
                queue.append((href, None))
    return ids


def phase_ids(args, http):
    out = args.out
    ids: "OrderedDict[str, str]" = OrderedDict()
    if args.list_html_dir:  # fallback: pages saved manually from the browser
        for f in sorted(Path(args.list_html_dir).glob("*.htm*")):
            ids_from_soup(BeautifulSoup(f.read_bytes(), "html.parser"), ids)
    else:
        params = dict(BASE_PARAMS, submitBtn="Cerca")
        for k in ("ORG", "STANDARDS", "SCHEMI_ALTRI_STD", "CITTA", "PROVINCIA",
                  "REGIONE", "STATO", "SCOPO", "PDFACCREDITAMENTO"):
            params[f"PPSEARCH_ORG_SEARCH_MASK_{k}"] = ""
        params["PPSEARCH_ODC_SEARCH_MASK_SETTORE_ACCR"] = ""
        ids = collect_ids(http, params)
    (out / "company_ids.json").write_text(json.dumps(ids, indent=1, ensure_ascii=False))
    log.info("collected %d company ids (expected %d)", len(ids), EXPECTED_COMPANIES)
    if len(ids) != EXPECTED_COMPANIES:
        log.warning("Count differs from %d. If the list is paginated in a way the "
                    "script did not follow, save every result page from your browser "
                    "into a folder and run:  ids --list-html-dir <folder>",
                    EXPECTED_COMPANIES)
    return ids


# --------------------------------------------------------- parsing helpers
def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t not in LEGAL_TOKENS]
    return " ".join(toks) or re.sub(r"\s+", " ", s).strip()


def to_date(s):
    return datetime.strptime(s, "%d/%m/%Y").date().isoformat() if s else None


def map_standard(norma: str):
    for rx, code in STD_MAP:
        if norma and re.search(rx, norma):
            return code
    return None


LABELS = ["Schema di accreditamento:", "Norma:", "Accreditamento N.:", "Emesso il:",
          "Sito Web:", "Tel:", "Fax:", "Email:", "Schema:"]
POSTAL = re.compile(r"^(\d{5})\s*-\s*(.+?)\s*\(([A-Za-z]{2})\)\s*$")


def parse_sites(lines):
    sites, cur = [], None
    for i, l in enumerate(lines):
        m = POSTAL.match(l)
        if m:
            prev = lines[i - 1] if i else None
            if prev and any(prev.startswith(x) for x in LABELS):
                prev = None
            cur = {"street": prev, "postal_code": m.group(1),
                   "city": m.group(2).title(), "province": m.group(3).upper(),
                   "region": None, "tel": None, "fax": None, "email": None}
            sites.append(cur)
        elif cur is not None:
            if l.startswith("Tel:"):
                cur["tel"] = l[4:].strip() or None
            elif l.startswith("Fax:"):
                cur["fax"] = l[4:].strip() or None
            elif l.startswith("Email:"):
                cur["email"] = l[6:].strip() or None
            elif cur["region"] is None:
                cur["region"] = l
    return sites


def parse_company(html: bytes, enc: str, org_id: str):
    """Returns (record, {filename: download_url})."""
    soup = BeautifulSoup(html, "html.parser", from_encoding=enc)
    for t in soup(["script", "style"]):
        t.decompose()

    website = None
    node = soup.find(string=re.compile(r"Sito Web", re.I))
    if node:
        a = node.find_next("a", href=True)
        if a and "CERTFILENAME" not in a["href"] and \
                re.match(r"(https?://|www\.)", a.get_text(strip=True), re.I):
            website = a["href"].strip()
            if not website.lower().startswith("http"):
                website = "http://" + website

    name = None
    for h in soup.find_all("h2"):
        t = h.get_text(" ", strip=True)
        if t and t.lower() != "organismi accreditati":
            name = t
            break

    page_url = PAGE_URL.format(id=org_id)
    urls = {}
    for a in soup.find_all("a", href=True):
        if "CERTFILENAME=" in a["href"]:
            full = urljoin(page_url, a["href"])
            fn = parse_qs(urlparse(full).query)["CERTFILENAME"][0]
            urls[fn] = full
            a.replace_with(f"\n[[PDF|{full}]]\n")

    # line breaks only at <br> / block elements, so inline <b>CITY</b> stays on its line
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                              "li", "ul", "tr", "td", "th", "table"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text("")
    for lab in LABELS:  # glue "Label:\nvalue" back together
        text = re.sub(re.escape(lab) + r"[ \t]*\n\s*", lab + " ", text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # restrict to the main content (the footer holds Accredia's own address/VAT!)
    start = next((i for i, l in enumerate(lines)
                  if l.lower().startswith("organismo accreditato")), 0)
    end = next((i for i, l in enumerate(lines) if i > start and (
        l in ("Sede legale", "Sede distaccata") or l.startswith("Privacy policy")
        or "twitter.com" in l)), len(lines))
    body = lines[start:end]

    def idx(pred, default):
        return next((i for i, l in enumerate(body) if pred(l)), default)

    i_sites = idx(lambda l: l.startswith("Sedi Accreditate"), 0)
    i_acc = idx(lambda l: l == "Accreditamenti", len(body))
    i_scheme = idx(lambda l: l.startswith("Schema:"), i_acc)
    sites = parse_sites(body[i_sites + 1:min(i_scheme, i_acc)])
    schemes = next((l[7:].strip() for l in body if l.startswith("Schema:")), None)

    acc_text = "\n".join(body[i_acc + 1:])
    accreditations = []
    for chunk in re.split(r"(?m)^(?=Schema di accreditamento:)", acc_text):
        if not chunk.startswith("Schema di accreditamento:"):
            continue
        parts = re.split(r"\[\[PDF\|([^\]]+)\]\]", chunk)
        head = parts[0]

        def val(label):
            m = re.search(re.escape(label) + r"\s*(.+)", head)
            return m.group(1).strip() if m else None

        norma = val("Norma:")
        m = re.search(r"Emesso il:\s*" + DATE_RE, head)
        scope_lines, seen_emesso = [], False
        for l in head.split("\n"):
            if seen_emesso and l.strip():
                scope_lines.append(l.strip())
            if l.startswith("Emesso il:"):
                seen_emesso = True
        docs = OrderedDict()
        for k in range(1, len(parts), 2):
            fn = parse_qs(urlparse(parts[k]).query)["CERTFILENAME"][0]
            info = re.sub(r"\s+", " ", parts[k + 1])
            d = docs.setdefault(fn, {"filename": fn, "rev": None,
                                     "issued_date": None, "expires": None})
            r_ = re.search(r"(?<!Data )Rev\. (\d+)", info)
            di = re.search(r"Data Rev\. " + DATE_RE, info)
            ds = re.search(r"Data Scad\. " + DATE_RE, info)
            d["rev"] = d["rev"] or (r_.group(1) if r_ else None)
            d["issued_date"] = d["issued_date"] or (to_date(di.group(1)) if di else None)
            d["expires"] = d["expires"] or (to_date(ds.group(1)) if ds else None)
            d["kind"] = ("ACCREDITATION_CERTIFICATE" if fn.endswith("_CERT")
                         else "ACCREDITATION_SCHEDULE" if "_ALL_" in fn else "OTHER")
        accreditations.append({
            "scheme_label": val("Schema di accreditamento:"),
            "norma": norma,
            "std_code": map_standard(norma),
            "nab_no": (val("Accreditamento N.:") or "").split()[0] if val("Accreditamento N.:") else None,
            "accredited_since": to_date(m.group(1)) if m else None,
            "scope_text": "\n".join(scope_lines) or None,
            "docs": list(docs.values()),
        })

    status = "ACTIVE"
    full = " ".join(body)
    if re.search(r"sospes", full, re.I):
        status = "SUSPENDED"
    elif re.search(r"revocat|ritirat", full, re.I):
        status = "WITHDRAWN"

    rec = {"id": org_id, "url": page_url, "name": name, "website": website,
           "schemes": schemes, "status": status, "sites": sites,
           "accreditations": accreditations, "complete": False}
    return rec, urls


# --------------------------------------------------------------- PDFs
def pdf_meta(path: Path):
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    pages, scanned = None, False
    if PdfReader:
        try:
            rd = PdfReader(str(path))
            pages = len(rd.pages)
            txt = "".join((rd.pages[i].extract_text() or "")
                          for i in range(min(2, pages)))
            scanned = len(txt.strip()) < 20
        except Exception as e:  # noqa
            log.warning("pdf parse failed %s: %s", path.name, e)
    return sha, pages, scanned


def download_pdf(http: Http, url: str, dest: Path, referer: str):
    if dest.exists() and dest.read_bytes()[:4] == b"%PDF":
        return
    r = http.get(url, headers={"Referer": referer})
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"not a PDF (content-type={r.headers.get('content-type')})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(dest)


# --------------------------------------------------------------- crawl
def crawl_company(args, http, org_id):
    jf = args.out / "companies" / f"{org_id}.json"
    if jf.exists() and not args.force:
        if json.loads(jf.read_text()).get("complete"):
            return "cached"
    url = PAGE_URL.format(id=org_id)
    r = http.get(url)
    (args.out / "html").mkdir(parents=True, exist_ok=True)
    (args.out / "html" / f"{org_id}.html").write_bytes(r.content)
    enc = "cp1252" if (r.encoding or "").lower() in ("iso-8859-1", "latin-1", "") else r.encoding
    rec, urls = parse_company(r.content, enc, org_id)
    if not rec["name"]:
        raise ValueError("company name not found - page layout changed?")
    ok = True
    if not args.no_pdf:
        # session-bound (IUXSID) links: download right away, same session
        for acc in rec["accreditations"]:
            for d in acc["docs"]:
                rel = Path("pdfs") / org_id / f"{d['filename']}.pdf"
                try:
                    download_pdf(http, urls[d["filename"]], args.out / rel, url)
                    d["path"] = rel.as_posix()
                    d["sha256"], d["pages"], d["scanned"] = pdf_meta(args.out / rel)
                except Exception as e:  # noqa
                    ok = False
                    d["error"] = str(e)
                    log.error("[%s] %s: %s", org_id, d["filename"], e)
    rec["complete"] = ok
    rec["fetched_at"] = date.today().isoformat()
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    return "ok" if ok else "pdf-errors"


def phase_crawl(args, http, ids):
    keys = list(ids)[: args.limit] if args.limit else list(ids)
    stats = {}
    for n, oid in enumerate(keys, 1):
        try:
            res = crawl_company(args, http, oid)
        except Exception as e:  # noqa
            res = "failed"
            log.error("[%s] %s", oid, e)
        stats[res] = stats.get(res, 0) + 1
        log.info("(%d/%d) %s -> %s", n, len(keys), oid, res)
    log.info("crawl summary: %s", stats)


# -------------------------------------------------------------- scopes
def discover_filters(http):
    r = http.get(BASE, params=BASE_PARAMS)
    out = {}
    for sel in soup_of(r).find_all("select"):
        out[sel.get("name")] = [(o.get("value", ""), o.get_text(strip=True))
                                for o in sel.find_all("option")]
    return out


def phase_scopes(args, http):
    filt = discover_filters(http)
    std_f = filt.get("PPSEARCH_ORG_SEARCH_MASK_STANDARDS", [])
    sec_f = filt.get("PPSEARCH_ODC_SEARCH_MASK_SETTORE_ACCR", [])
    if args.discover:
        for k, v in filt.items():
            print(f"\n[{k}]")
            for val, txt in v:
                print(f"  {val!r:20} {txt}")
        return
    stds = [(v, t, code) for v, t in std_f for k, code in CERT_STD_MAP.items()
            if re.search(rf"\b{k}\b", t) or re.search(rf"\b{k}\b", v)]
    secs = []
    for v, t in sec_f:
        m = re.match(r"^\s*(?:EA\s*)?(\d{1,2})\b", t) or re.match(r"^\s*(\d{1,2})$", v)
        if m and 1 <= int(m.group(1)) <= 39:
            secs.append((v, int(m.group(1))))
    log.info("matched %d standard options and %d sector options", len(stds), len(secs))
    if not stds:
        log.error("No ISO 9001/14001/45001/27001 option found in the STANDARDS filter. "
                  "Run `scopes --discover` and adjust CERT_STD_MAP matching.")
        return
    rows = []
    for sv, st, code in stds:
        for secv, ea in (secs or [("", None)]):
            params = dict(BASE_PARAMS, submitBtn="Cerca")
            params["PPSEARCH_ORG_SEARCH_MASK_STANDARDS"] = sv
            params["PPSEARCH_ODC_SEARCH_MASK_SETTORE_ACCR"] = secv
            found = collect_ids(http, params, max_pages=50)
            log.info("%s x EA %s -> %d CBs", code, ea, len(found))
            rows += [{"org": o, "std": code, "ea": ea} for o in found]
    (args.out / "scopes.json").write_text(json.dumps(rows, indent=1))


# ----------------------------------------------------------------- SQL
def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\x00", "").replace("'", "''") + "'"


def batches(rows, n=100):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def phase_sql(args):
    recs = [json.loads(f.read_text()) for f in
            sorted((args.out / "companies").glob("*.json"), key=lambda p: int(p.stem))]
    warnings, unknown_std = [], {}
    today = date.today()

    # ---- certification bodies
    cbs, used = [], {}
    for r in recs:
        if not r.get("name"):
            continue
        legal = re.sub(r"\s+", " ", r["name"].replace('"', "")).strip()
        norm = normalize_name(legal)
        if norm in used:
            warnings.append(f"name collision '{norm}' ({used[norm]} vs {r['id']}) -> suffixed")
            norm = f"{norm} {r['id']}"
        used[norm] = r["id"]
        r["_norm"], r["_legal"] = norm, legal
        s0 = (r["sites"] or [{}])[0]
        extra = [f"{s['street']}, {s['postal_code']} {s['city']} ({s['province']})"
                 for s in (r["sites"] or [])[1:] if s.get("street")]
        notes = f"Accredia org ID {r['id']}; schemes: {r.get('schemes') or '-'}"
        if extra:
            notes += "; other accredited sites: " + " | ".join(extra)
        cbs.append((legal[:300], norm[:300], (s0.get("street") or None) and s0["street"][:400],
                    s0.get("city"), s0.get("postal_code"), (s0.get("tel") or None) and s0["tel"][:60],
                    (s0.get("email") or None) and s0["email"][:200],
                    (r.get("website") or None) and r["website"][:300], notes))
        if not r.get("website"):
            warnings.append(f"[{r['id']}] {legal}: no website")

    # ---- source documents (dedupe by sha256) & accreditations
    docs, shas, accs = [], set(), OrderedDict()
    for r in recs:
        if "_norm" not in r:
            continue
        for a in r["accreditations"]:
            if not a["std_code"]:
                unknown_std.setdefault(a["norma"], []).append(r["id"])
                continue
            for d in a["docs"]:
                if d.get("sha256") and d["sha256"] not in shas:
                    shas.add(d["sha256"])
                    docs.append((d["kind"], d["filename"] + ".pdf", d["path"], d["sha256"],
                                 d.get("pages"), bool(d.get("scanned")), d["issued_date"], r["url"]))
            cert = next((d for d in a["docs"] if d["kind"] == "ACCREDITATION_CERTIFICATE"
                         and d.get("sha256")), None)
            exp = [d["expires"] for d in a["docs"] if d["expires"]]
            vuntil = max(exp) if exp else None
            vfrom = cert["issued_date"] if cert else None
            if vfrom and vuntil and vuntil < vfrom:
                warnings.append(f"[{r['id']}] valid_until < valid_from, valid_from dropped")
                vfrom = None
            status = r["status"]
            if status == "ACTIVE" and vuntil and vuntil < today.isoformat():
                status = "EXPIRED"
            key = (r["_norm"], a["std_code"], a["nab_no"] or "")
            if key in accs:
                warnings.append(f"[{r['id']}] duplicate accreditation {key[1:]} merged")
                accs[key]["scopes"].append(a["scope_text"])
                continue
            accs[key] = {"since": a["accredited_since"], "vfrom": vfrom, "vuntil": vuntil,
                         "status": status, "sha": cert["sha256"] if cert else None,
                         "url": r["url"], "scopes": [a["scope_text"]]}

    # ---- management-system scopes (from `scopes` phase)
    ms_scopes = set()
    sf = args.out / "scopes.json"
    if sf.exists():
        by_org = {r["id"]: r for r in recs if "_norm" in r}
        for s in json.loads(sf.read_text()):
            r = by_org.get(s["org"])
            if not r:
                continue
            k = next((k for k in accs if k[0] == r["_norm"] and k[1] == "ISO/IEC 17021-1"), None)
            if not k:
                warnings.append(f"[{s['org']}] in {s['std']} filter but has no 17021-1 accreditation")
                continue
            ms_scopes.add((k, s["std"], s["ea"]))

    def cb_join():
        return ("JOIN country c ON c.iso_code = 'IT'\n"
                "JOIN certification_body cb ON cb.normalized_name = v.cb_norm AND cb.country_id = c.id")

    out = [f"-- =====================================================================",
           f"-- V3__seed_accredia_data.sql  (GENERATED {today.isoformat()} by accredia_scraper.py)",
           f"-- {len(cbs)} certification bodies, {len(docs)} source documents, {len(accs)} accreditations",
           f"-- Source: https://services.accredia.it  (area 310)",
           f"-- =====================================================================", ""]

    out.append("-- 1. CERTIFICATION BODIES")
    for b in batches(cbs):
        out.append("INSERT INTO certification_body\n"
                   "    (legal_name, normalized_name, country_id, address, city, postal_code, phone, email, website, notes)\n"
                   "SELECT v.legal_name, v.normalized_name, c.id, v.address, v.city, v.postal_code, v.phone, v.email, v.website, v.notes\n"
                   "FROM (VALUES")
        out.append(",\n".join("    (" + ", ".join(q(x) for x in row) + ")" for row in b))
        out.append(") AS v(legal_name, normalized_name, address, city, postal_code, phone, email, website, notes)\n"
                   "JOIN country c ON c.iso_code = 'IT'\n"
                   "ON CONFLICT (country_id, normalized_name) DO NOTHING;\n")

    out.append("-- 2. SOURCE DOCUMENTS (PDFs stored under storage_path)")
    for b in batches(docs):
        out.append("INSERT INTO source_document\n"
                   "    (country_id, doc_type, file_name, storage_path, sha256, page_count, is_scanned, issued_date, source_url)\n"
                   "SELECT c.id, v.doc_type, v.file_name, v.storage_path, v.sha256, v.page_count::int, v.is_scanned::boolean, v.issued_date::date, v.source_url\n"
                   "FROM (VALUES")
        out.append(",\n".join("    (" + ", ".join(q(x) for x in row) + ")" for row in b))
        out.append(") AS v(doc_type, file_name, storage_path, sha256, page_count, is_scanned, issued_date, source_url)\n"
                   "JOIN country c ON c.iso_code = 'IT'\n"
                   "ON CONFLICT (sha256) DO NOTHING;\n")

    out.append("-- 3. ACCREDITATIONS")
    rows = [(k[0], k[1], k[2] or None, v["since"], v["vfrom"], v["vuntil"], v["status"], v["sha"], v["url"])
            for k, v in accs.items()]
    for b in batches(rows):
        out.append("INSERT INTO accreditation\n"
                   "    (cb_id, accreditation_standard_id, nab_certificate_no, accredited_since, valid_from, valid_until,\n"
                   "     status, source_document_id, source_url, last_verified_at)\n"
                   "SELECT cb.id, s.id, v.nab_no, v.since::date, v.vfrom::date, v.vuntil::date, v.status, sd.id, v.source_url,\n"
                   f"       DATE '{today.isoformat()}'\n"
                   "FROM (VALUES")
        out.append(",\n".join("    (" + ", ".join(q(x) for x in row) + ")" for row in b))
        out.append(") AS v(cb_norm, std_code, nab_no, since, vfrom, vuntil, status, cert_sha, source_url)\n"
                   + cb_join() + "\n"
                   "JOIN standard s ON s.code = v.std_code\n"
                   "LEFT JOIN source_document sd ON sd.sha256 = v.cert_sha\n"
                   "ON CONFLICT DO NOTHING;\n")

    scope_rows = []
    for k, v in accs.items():
        for t in OrderedDict.fromkeys(x for x in v["scopes"] if x):
            scope_rows.append((k[0], k[1], k[2] or None, None, None, t))
    for k, std, ea in sorted(ms_scopes, key=str):
        scope_rows.append((k[0], k[1], k[2] or None, std, ea, None))
    out.append("-- 4. ACCREDITATION SCOPES")
    for b in batches(scope_rows):
        out.append("INSERT INTO accreditation_scope (accreditation_id, certification_standard_id, ea_sector_code, scope_text)\n"
                   "SELECT a.id, cs.id, v.ea::smallint, v.scope_text\n"
                   "FROM (VALUES")
        out.append(",\n".join("    (" + ", ".join(q(x) for x in row) + ")" for row in b))
        out.append(") AS v(cb_norm, acc_std, nab_no, cert_std, ea, scope_text)\n"
                   + cb_join() + "\n"
                   "JOIN standard ast ON ast.code = v.acc_std\n"
                   "JOIN accreditation a ON a.cb_id = cb.id AND a.accreditation_standard_id = ast.id\n"
                   "                    AND COALESCE(a.nab_certificate_no, '') = COALESCE(v.nab_no, '')\n"
                   "LEFT JOIN standard cs ON cs.code = v.cert_std\n"
                   "ON CONFLICT DO NOTHING;\n")

    if unknown_std:
        out.append("-- Accreditations SKIPPED: accreditation standard not in V2 seed")
        for n, o in unknown_std.items():
            out.append(f"--   {n}: {len(o)} CBs (e.g. org IDs {', '.join(o[:5])})")
    sql_path = args.out / "V3__seed_accredia_data.sql"
    sql_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    rep = [f"companies parsed: {len(recs)}", f"CBs in SQL: {len(cbs)}",
           f"accreditations: {len(accs)}", f"source documents: {len(docs)}",
           f"MS scope rows (std x EA): {len(ms_scopes)}",
           f"incomplete crawls: {[r['id'] for r in recs if not r.get('complete')]}",
           "unknown accreditation standards (skipped): " + json.dumps(
               {k: len(v) for k, v in unknown_std.items()}, ensure_ascii=False),
           "", "WARNINGS:"] + warnings
    (args.out / "report.txt").write_text("\n".join(rep), encoding="utf-8")
    log.info("wrote %s\n%s", sql_path, "\n".join(rep[:8]))


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["ids", "crawl", "scopes", "sql", "all"])
    ap.add_argument("--out", type=Path, default=Path("accredia_out"))
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--limit", type=int, help="crawl only the first N companies")
    ap.add_argument("--force", action="store_true", help="re-crawl cached companies")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--discover", action="store_true", help="scopes: print filter options and exit")
    ap.add_argument("--list-html-dir", help="ids: parse saved result pages instead of fetching")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    http = Http(args.delay)

    def load_ids():
        f = args.out / "company_ids.json"
        return json.loads(f.read_text()) if f.exists() else phase_ids(args, http)

    if args.phase in ("ids", "all"):
        phase_ids(args, http)
    if args.phase in ("crawl", "all"):
        phase_crawl(args, http, load_ids())
    if args.phase in ("scopes", "all"):
        phase_scopes(args, http)
    if args.phase in ("sql", "all"):
        phase_sql(args)


if __name__ == "__main__":
    sys.exit(main())