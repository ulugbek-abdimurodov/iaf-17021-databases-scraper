"""Scrape IOAS (International Organic Accreditation Service, USA) ISO/IEC 17065 accredited certification bodies.

IOAS has no management-system (17021) program, so there is no MS scraper to derive from; this follows the
other US 17065 scrapers (../us_17065_common.py).

Register (WordPress / Toolset):
  bodies  : https://ioas.org/accredited-body-sitemap.xml   -> every /accredited-body/<slug>/ page
  status  : https://ioas.org/accredited-certification-bodies/  table "CB Name | CB Home Country | Also known as |
            Accredited Schemes | Applicant | Suspended Schemes"
  body    : Contract Number, name, also known as, phone, home country, email, web address, then an ACCREDITATIONS
            block: one <h4> per accreditation ("ISO/IEC 17065, GlobalG.A.P.", "ISO/IEC 17065, Regulation (EU)
            2018/848 ...", or non-17065 programs such as "IFOAM", "COSMOS", "COR"), followed by its
            "Accreditation Certificate" / "Accreditation Certificate Annex" PDF links.
The 17065 filter: only <h4> sections whose title contains "17065" (and their PDFs) are kept; a body without one
is skipped (listed in the summary). Certificates give issue / effective / renewal dates; annexes give the
"STANDARD | CATEGORIES | GEOGRAPHICAL SCOPE" table (text layer).
One record per body (registration_no = IOAS contract number).

Usage: python scrape_us_ioas_17065.py [--out DIR] [--limit N] [--no-files]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import us_17065_common as c  # noqa: E402

SITE = "https://ioas.org"
FOOT = re.compile(r"^(IOAS Executive Director|Scope of Accreditation|STANDARD CATEGORIES)", re.I)


def iso(d: str) -> str:
    d = d.strip().replace(".", "")
    for f in ("%b %d, %Y", "%B %d, %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(d.title() if "-" in d else d, f).date().isoformat()
        except ValueError:
            pass
    return d


def norm(s: str) -> str:
    return re.sub(r"\W+", " ", s).strip().lower()


def status_table(sess) -> dict:
    s = BeautifulSoup(c.get(sess, f"{SITE}/accredited-certification-bodies/").text, "html.parser")
    out = {}
    for tr in s.select("table tr"):
        td = [x.get_text(" ", strip=True) for x in tr.find_all("td")]
        if len(td) >= 6:
            out[norm(td[0])] = {"country": td[1], "aka": td[2], "accredited": td[3], "applicant": td[4],
                                "suspended": td[5]}
    return out


def body_page(sess, url: str) -> dict:
    s = BeautifulSoup(c.get(sess, url).text, "html.parser")
    for x in s(["script", "style", "header", "footer", "nav"]):
        x.decompose()
    text = s.get_text("\n", strip=True)

    def field(label):
        m = re.search(label + r":\s*(.+)", text)
        return m[1].strip() if m else ""

    h1 = s.find("h1")
    b = {"url": url, "contract": field("Contract Number"), "name": h1.get_text(" ", strip=True) if h1 else "",
         "aka": (re.search(r"Also known as\s*(.+)", text) or [0, ""])[1].strip(), "phone": field("Phone Number"),
         "country": field("Home Country"), "email": field("Email Address"), "website": field("Web Address"),
         "sections": []}
    web = s.find("a", string=re.compile("Web Address")) or next(
        (a for a in s.select("a[href]") if "Web Address" in a.get_text()), None)
    if web and web.get("href", "").startswith("http"):
        b["website"] = web["href"]
    head = next((h for h in s.find_all("h2") if "ACCREDITATIONS" in h.get_text()), None)
    cur = None
    for el in (head.find_all_next(["h4", "p", "a"]) if head else []):
        if el.name == "h4":
            cur = {"title": re.sub(r"\s+", " ", el.get_text(" ", strip=True)), "note": [], "pdfs": []}
            b["sections"].append(cur)
        elif el.name == "a" and el.get("href", "").lower().endswith(".pdf"):
            label = el.get_text(" ", strip=True) or el["href"].rsplit("/", 1)[-1]
            if cur is None:
                cur = {"title": "", "note": [], "pdfs": []}
                b["sections"].append(cur)
            if el["href"] not in [u for _, u in cur["pdfs"]]:
                cur["pdfs"].append((label, el["href"]))
        elif el.name == "p" and cur is not None:
            t = el.get_text(" ", strip=True)
            if t and not set(t) <= set("_ "):
                cur["note"].append(t)
    return b


def main() -> int:
    ap = argparse.ArgumentParser(description="IOAS ISO/IEC 17065 accredited certification bodies scraper")
    ap.add_argument("--out", type=Path, default=HERE / "ioas_17065")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    sess = c.session()

    urls = re.findall(r"<loc>([^<]+/accredited-body/[^<]+)</loc>", c.get(sess, f"{SITE}/accredited-body-sitemap.xml").text)
    urls = urls[: a.limit] if a.limit else urls
    statuses = status_table(sess)
    print(f"IOAS: {len(urls)} body pages, {len(statuses)} rows in the status table")

    records, scope_rows, stats, skipped = [], [], {}, []
    for n, url in enumerate(urls, 1):
        b = body_page(sess, url)
        secs = [x for x in b["sections"] if "17065" in x["title"]]
        # PDFs listed after a non-17065 heading but named 17065 (heading/link order varies on some pages)
        secs += [{"title": x["title"], "note": [], "pdfs": [p for p in x["pdfs"] if "17065" in p[1]]}
                 for x in b["sections"] if "17065" not in x["title"] and any("17065" in p[1] for p in x["pdfs"])]
        print(f"[{n}/{len(urls)}] {b['name']} ({len(secs)} x 17065)")
        if not secs:
            skipped.append(f"{b['name']}: {', '.join(x['title'] for x in b['sections']) or 'no accreditations'}")
            continue
        st = statuses.get(norm(b["name"])) or next((v for k, v in statuses.items()
                                                     if k and (k in norm(b["name"]) or norm(b["name"]) in k)), {})
        status = ("suspended" if "17065" in st.get("suspended", "") and "17065" not in st.get("accredited", "")
                  else "applicant" if "17065" in st.get("applicant", "") and "17065" not in st.get("accredited", "")
                  else "accredited")
        reg = b["contract"] or c.safe_name(b["name"])
        pdfs = [p for x in secs for p in x["pdfs"]]
        pdfs = list(dict.fromkeys(pdfs))
        rec = {"registration_no": reg, "id": url.rstrip("/").rsplit("/", 1)[-1], "name": b["name"], "address": "",
               "phone": b["phone"], "email": b["email"], "website": b["website"], "issued": "", "expiry": "",
               "annex_urls": [u for _, u in pdfs], "country": b["country"], "also_known_as": b["aka"],
               "status": status, "register_status": st, "schemes": [x["title"] for x in secs], "url": url,
               "other_programs": [x["title"] for x in b["sections"] if "17065" not in x["title"] and x["title"]]}
        k = 0
        for x in secs:
            for line in [x["title"], *x["note"]]:
                k += 1
                scope_rows.append((reg, "register", k, line))
        if not a.no_files:
            for i, (label, u) in enumerate(pdfs, 1):
                p = c.download_pdf(sess, u, a.out / "annexes" / f"{reg}_{c.safe_name(u.rsplit('/', 1)[-1])}", stats)
                pages = c.pdf_text(p) if p else []
                if p and not "".join(pages).strip():
                    stats["pdf_scanned"] = stats.get("pdf_scanned", 0) + 1
                    continue
                full = "\n".join(pages)
                if "annex" not in (label + u).lower():
                    dt = r"[:\s]*([A-Z][a-z]{2,8}\.? \d{1,2}, \d{4})"
                    m = re.search(r"Effective date of accreditation" + dt, full)
                    e = re.search(r"Accreditation renewal date" + dt, full)
                    if not e:  # label and value printed apart: last "Month dd, yyyy" in the text
                        ds = re.findall(r"[A-Z][a-z]{2,8}\.? \d{1,2}, \d{4}", full)
                        e = [0, max(ds, key=lambda d: iso(d.replace(".", "")))] if ds else None
                    ad = re.search(r"attests that\s*\n(.+?)\nContract No", full, re.S)
                    rec["issued"] = rec["issued"] or (iso(m[1]) if m else "")
                    rec["expiry"] = max(rec["expiry"], iso(e[1]) if e else "")
                    if ad and not rec["address"]:
                        parts = [l.strip(" ,") for l in ad[1].splitlines()[1:] if l.strip(" ,")]
                        rec["address"] = re.sub(r"\s+,", ",", ", ".join(parts))
                else:
                    lines = [l for pg in pages for l in c.clean_lines(pg) if not FOOT.search(l)]
                    scope_rows += [(reg, "annex", j, l) for j, l in enumerate(lines, 1)]
        records.append(rec)
    c.write_outputs(a.out, "ioas", records, scope_rows, stats)
    if skipped:
        print(f"  skipped (no ISO/IEC 17065 accreditation): {len(skipped)}")
        for s in skipped:
            print("    -", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
