"""Scrape A2LA (American Association for Laboratory Accreditation) ISO/IEC 17065 Product Certification Bodies.

A2LA has no management-system (17021) program, so there is no MS scraper to derive from; this follows the
same structure as the other US 17065 scrapers (../us_17065_common.py).

Register: https://customer.a2la.org/index.cfm?event=directory.index (TouchStone directory)
  search : POST index.cfm?event=directory.search, JSON {"criteria": {"programIds": [87], ...}}
           program 87 = "ISO/IEC 17065:2012 Product Certification Bodies" (data-fieldpath "A2LA : ISO/IEC 17065:2012")
           returns one row per accreditation (labPID, accreditationCode, labName, location, country,
           accreditationCommercialCode, accreditationExpirationDate); no status filter -> all statuses.
  detail : GET index.cfm?event=directory.detail&labPID=<labPID>  (web, address, contact, email, phone, and one
           block per accreditation: "<code>: <program>", expiry, commercial code, document links)
  PDF    : index.cfm?event=directory.getDocument&accreditationPID=..&documentPID=..  "Accreditation Scope &
           Certificate"; page 1 = header, following pages = scheme / product category / standard table
           (text layer), last page = certificate.
A lab's detail page also lists its 17025/17020 accreditations; only blocks whose title holds 17065 are kept.

Usage: python scrape_us_a2la_17065.py [--out DIR] [--limit N] [--no-files]
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

BASE = "https://customer.a2la.org/index.cfm"
PROGRAM_17065 = 87
SKIP = re.compile(r"^\(A2LA Cert\. No\.|^Page \d+ of \d+|^Revised \d|^Certification Scheme( Product Type.*)?$|"
                  r"^Product Type ?/ ?Category|^Standards ?/ ?Requirements|^Peter Unger|^President|"
                  r"^For the Accreditation Council|^Certificate Number|^Valid to", re.I)


def iso(d: str) -> str:
    for f in ("%m/%d/%Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(d.strip(), f).date().isoformat()
        except ValueError:
            pass
    return d.strip()


def search(sess) -> list[dict]:
    crit = {"keyword": "", "programIds": [PROGRAM_17065], "labId": "", "accreditationId": "",
            "accreditationCommercialId": "", "countryIds": []}
    r = sess.post(f"{BASE}?event=directory.search", json={"criteria": crit}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return c.json.loads(d) if isinstance(d, str) else d


def detail(sess, lab_pid: str) -> dict:
    html = c.get(sess, f"{BASE}?event=directory.detail&labPID={lab_pid}").text
    s = BeautifulSoup(html, "html.parser")
    for x in s(["script", "style"]):
        x.decompose()
    lines = [l for l in s.get_text("\n", strip=True).splitlines()]

    def after(label, stop=None):
        try:
            i = lines.index(label)
        except ValueError:
            return []
        out = []
        for l in lines[i + 1:]:
            if l.endswith(":") or (stop and l == stop):
                break
            out.append(l)
        return out

    info = {"website": " ".join(after("Web:")), "address": ", ".join(after("Address:")),
            "email": " ".join(after("email:")), "phone": " ".join(after("phone:")),
            "contact": " ".join(after("Contact(s):")), "accs": {}}
    for h4 in s.find_all("h4"):
        m = re.match(r"([\d.]+):\s*(.+)", h4.get_text(" ", strip=True).replace("\xa0", " "))
        if not m:
            continue
        block = h4.find_parent(class_="row-fluid")
        sibs = []
        for sib in block.find_next_siblings(class_="row-fluid"):
            if sib.find("h4"):
                break
            sibs.append(sib)
        txt = " ".join(x.get_text(" ", strip=True) for x in sibs)
        docs = [(a.get_text(" ", strip=True), BASE + a["href"].split("index.cfm", 1)[-1])
                for x in sibs for a in x.select("a[href*='getDocument']")]
        info["accs"][m[1]] = {"program": m[2], "text": txt, "docs": docs,
                              "commercial": (re.search(r"Commercial Code:\s*(.+?\))", txt) or [0, ""])[1],
                              "expiry": (re.search(r"Expiration Date:\s*([\d/]+)", txt) or [0, ""])[1]}
    return info


def parse_pdf(pages: list[str]) -> tuple[list[str], str]:
    """Scope lines (pages 2..n-1, or all but the certificate page) and the certificate issue date if shown."""
    issued = ""
    full = "\n".join(pages)
    m = re.search(r"Presented this (\d+)\w* day of (\w+) (\d{4})", full)
    if m:
        issued = iso(f"{m[1]} {m[2]} {m[3]}")
    cert = re.compile(r"Presented this|A2LA has accredited|please refer to the organization", re.I)
    body = [p for p in pages if not cert.search(p)]
    if body and re.search(r"SCOPE OF ACCREDITATION", body[0], re.I):  # page-1 header: keep only after the intro
        head = body[0]
        k = max(head.find("Certification Scheme"), -1)
        body[0] = head[k:] if k >= 0 else ""
    lines = [l for p in body for l in c.clean_lines(p) if not SKIP.search(l)]
    return lines, issued


def main() -> int:
    ap = argparse.ArgumentParser(description="A2LA ISO/IEC 17065 Product Certification Bodies scraper")
    ap.add_argument("--out", type=Path, default=HERE / "a2la_17065")
    ap.add_argument("--limit", type=int, default=0, help="only the first N bodies (trial)")
    ap.add_argument("--no-files", action="store_true", help="skip PDF downloads")
    a = ap.parse_args()

    sess = c.session()
    rows = search(sess)
    print(f"A2LA program {PROGRAM_17065}: {len(rows)} accreditations")
    labs: dict[str, list[dict]] = {}
    for r in rows:
        labs.setdefault(r["labPID"], []).append(r)
    pids = list(labs)[: a.limit] if a.limit else list(labs)

    records, scope_rows, stats = [], [], {}
    for n, pid in enumerate(pids, 1):
        first = labs[pid][0]
        print(f"[{n}/{len(pids)}] {first['labName'].strip()}")
        info = detail(sess, pid)
        for r in labs[pid]:
            code = r["accreditationCode"]
            acc = info["accs"].get(code, {})
            if acc and "17065" not in acc["program"]:
                continue
            rec = {"registration_no": code, "id": pid, "name": r["labName"].strip(),
                   "address": info["address"], "phone": info["phone"], "email": info["email"],
                   "website": info["website"], "issued": "",
                   "expiry": iso(acc.get("expiry") or r.get("accreditationExpirationDate", "")),
                   "annex_urls": [u for _, u in acc.get("docs", [])], "country": r.get("country", ""),
                   "location": r.get("location", ""), "contact": info["contact"],
                   "status": acc.get("commercial") or r.get("accreditationCommercialCode", ""),
                   "program": acc.get("program", r.get("programFieldPath", ""))}
            if not a.no_files:
                for i, (label, url) in enumerate(acc.get("docs", []), 1):
                    p = c.download_pdf(sess, url, a.out / "annexes" / f"{code}_{i}_{c.safe_name(label)}.pdf", stats)
                    if not p:
                        continue
                    pages = c.pdf_text(p)
                    if not "".join(pages).strip():
                        stats["pdf_scanned"] = stats.get("pdf_scanned", 0) + 1
                        rec["annex_scanned"] = True
                        continue
                    lines, issued = parse_pdf(pages)
                    rec["issued"] = rec["issued"] or issued
                    scope_rows += [(code, "annex", k, l) for k, l in enumerate(lines, 1)]
            records.append(rec)
    c.write_outputs(a.out, "a2la", records, scope_rows, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
