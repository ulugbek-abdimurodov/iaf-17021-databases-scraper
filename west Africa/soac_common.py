"""Shared scraping logic for SOAC-WAAS accredited CAB registers (https://soacwaas.org).
Listing page per scheme -> one card per CAB -> attestation detail page -> PDF certificate + scope annex.
Note: the /download_attestation/ endpoint serves a PDF with a text/html content type, so check magic bytes.
"""
import json, re, sys, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://soacwaas.org"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
       "Accept-Language": "en"}
norm = lambda t: re.sub(r"\s+", " ", t or "").strip()


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


def parse_detail(html):
    t = norm(BeautifulSoup(re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S), "html.parser").get_text(" "))
    g = lambda pat: (re.search(pat, t) or [None, ""])[1].strip()
    cert = g(r"CERTIFICATE (N°\S+(?: version \d+)?) ACCREDITATION STANDARDS")
    phone_email = g(r"Phone / Email (.*?) CERTIFICATE N°")
    email = ", ".join(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", phone_email))
    return dict(
        address=g(r"Address (.*?) Country / City"),
        country_city=g(r"Country / City (.*?) Mailbox"),
        mailbox=g(r"Mailbox (.*?) Phone / Email"),
        phone=norm(re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "", phone_email)),
        email=email,
        certificate_no=cert,
        standard=g(r"ACCREDITATION STANDARDS (.*?) START DATE"),
        start_date=g(r"START DATE (.*?) END DATE"),
        end_date=g(r"END DATE (.*?) STATUS"),
        status=g(r"STATUS (\w+)"),
    )


def pdf_text(path):
    try:
        import pypdf
    except ImportError:
        sys.exit("pip install pypdf")
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)


def run(slug, out_dir, limit=None, no_files=False):
    """slug: referentiel slug on the register. Writes <out>/raw.json, <out>/pdfs/*.pdf, <out>/annex_text/*.txt."""
    out = Path(out_dir); (out / "pdfs").mkdir(parents=True, exist_ok=True); (out / "annex_text").mkdir(exist_ok=True)
    list_url = f"{BASE}/en/oec/referentiel/{slug}"
    s = requests.Session()
    r = get(s, list_url)
    if not r:
        sys.exit("listing unreachable")
    soup = BeautifulSoup(r.text, "html.parser")
    cards, seen = [], set()
    for a in soup.select('h3 a[href*="/attestation/"]'):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        cards.append((norm(a.get_text()), href))
    if limit:
        cards = cards[:limit]
    raw, ok, fail = [], 0, 0
    for name, href in cards:
        att = href.rstrip("/").split("/")[-1]
        d = get(s, href)
        rec = dict(name=name, attestation_id=att, source_url=href, list_url=list_url)
        if d:
            rec.update(parse_detail(d.text))
        pdf_url = f"{BASE}/fr/download_attestation/{att}"
        rec["pdf_url"] = pdf_url
        if not no_files:
            pr = get(s, pdf_url)
            if pr and pr.content[:4] == b"%PDF":
                p = out / "pdfs" / f"{att}.pdf"; p.write_bytes(pr.content); ok += 1
                try:
                    (out / "annex_text" / f"{att}.txt").write_text(pdf_text(p), "utf-8")
                except Exception as e:
                    rec["pdf_error"] = str(e)
            else:
                fail += 1
        raw.append(rec)
    (out / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), "utf-8")
    print(f"bodies={len(raw)} pdf_ok={ok} pdf_fail={fail}")
