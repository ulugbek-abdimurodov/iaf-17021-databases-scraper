"""Scrape UAF (United Accreditation Foundation) ISO/IEC 17065 Product Certification Bodies.

Derived from ../database/united-states/scrape_us_uaf.py (MS-CAB procedure, programme 'Management Systems'
26a769cf-...). Same API, with the programme swapped:
  programme list : https://newprodapi.uafaccreditation.org/api/global/programme/list/
                   -> 'Product Certification Bodies' = 271dd4e3-1b3c-46a4-a037-9e9af95c78c2
  list   : /api/account/cab/home/list/data/pagination/?user_programmes=<PRD>&is_cab_visible=true&page_size=500
           (no is_cab_active/suspended/withdraw flag -> every status; the flags are read per CAB)
  detail : /api/account/cab/details/filter/?id=<user>  -> programme_with_cluster (schemes / standards / clusters)
  docs   : /api/cab/filter/documents/?cab=<user>       -> only documents whose programme is PRD are kept
           (the same CAB also has MS / VVB / inspection certificates).
The 'Certificate and Schedule' PDF has a text layer: page 1 certificate (issue, valid from, expiry), page 2+
schedule ("Accredited to ISO/IEC 17065 | Accreditation Number | Valid Date | Valid Up to" table, standards and
the scope). Unlike the MS schedules there are no IAF / EA codes.

Usage: python scrape_us_uaf_17065.py [--out DIR] [--limit N] [--no-files]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import us_17065_common as c  # noqa: E402

API = "https://newprodapi.uafaccreditation.org/api"
PRD = "271dd4e3-1b3c-46a4-a037-9e9af95c78c2"  # Product Certification Bodies
BOILER = re.compile(r"^(Doc\. No\.|Rev No\.|Effective Date:|Page \d+|Director$|Dated:|\(DIRECTOR\))", re.I)


def iso(d: str) -> str:
    for f in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(d.strip().title(), f).date().isoformat()
        except ValueError:
            pass
    return d.strip()


def parse_pdf(pages: list[str]) -> dict:
    full = "\n".join(pages)
    r = {"issued": "", "expiry": "", "number": "", "lines": []}
    m = re.search(r"Accreditation Number.*?\n.*?(\d{6,})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})", full, re.S)
    if m:
        r["number"], r["issued"], r["expiry"] = m[1], iso(m[2]), iso(m[3])
    else:
        f = re.search(r"VALID FROM\s*(\d{2}/\d{2}/\d{4})", full)
        e = re.search(r"EXPIRY\s*(\d{2}/\d{2}/\d{4})", full)
        r["issued"], r["expiry"] = iso(f[1]) if f else "", iso(e[1]) if e else ""
    loc = re.search(r"Key Location:\s*(.+)", full)
    r["address"] = re.sub(r"\s+", " ", loc[1]).strip() if loc else ""
    lines = [l for p in pages[1:] for l in c.clean_lines(p) if not BOILER.search(l)]
    k = next((i for i, l in enumerate(lines) if re.search(r"SCOPE OF ACCREDITATION", l, re.I)), None)
    if k is None:  # no scope heading: everything after the standards list's last "UAF-"/"IAF" line
        idx = [i for i, l in enumerate(lines) if re.match(r"(UAF-|IAF MD|ISO/IEC 17065:2012)", l)]
        k = idx[-1] if idx else 0
    r["lines"] = lines[k + 1:]
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="UAF ISO/IEC 17065 Product Certification Bodies scraper")
    ap.add_argument("--out", type=Path, default=HERE / "uaf_17065")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    sess = c.session()

    lst = c.get(sess, f"{API}/account/cab/home/list/data/pagination/?user_programmes={PRD}"
                      "&is_cab_visible=true&page_size=500").json()
    cabs = lst["results"][: a.limit] if a.limit else lst["results"]
    print(f"UAF programme {PRD}: {lst['count']} CABs")

    records, scope_rows, stats = [], [], {}
    for n, cab in enumerate(cabs, 1):
        uid, cd = cab["user"], cab["cab_data"]
        print(f"[{n}/{len(cabs)}] {cd['company']}")
        det = c.get(sess, f"{API}/account/cab/details/filter/?id={uid}").json()["results"][0]
        prog = [p for p in det.get("programme_with_cluster", []) if p["programme"]["id"] == PRD]
        docs = [d for d in c.get(sess, f"{API}/cab/filter/documents/?cab={uid}").json() if d["programme"] == PRD]
        status = ("withdrawn" if cd.get("is_cab_withdraw") else "suspended" if cd.get("is_cab_suspended")
                  else "active" if cd.get("is_cab_active") else "inactive")
        rec = {"registration_no": cd.get("short_code") or uid, "id": uid, "name": cd["company"].strip(),
               "address": ", ".join(x for x in [cd.get("address"), det.get("city"), det.get("state"),
                                                 det.get("zip_code"), det.get("country")] if x),
               "phone": det.get("phone") or det.get("mobile") or "", "email": cd.get("email", ""),
               "website": cd.get("company_web") or "", "issued": "", "expiry": "",
               "annex_urls": [d["file"] for d in docs], "status": status, "short_code": cd.get("short_code"),
               "schemes": [{"scheme": s["name"], "standards": [st["name"] for st in s["standards"]],
                            "clusters": [cl["name"] for st in s["standards"] for cl in st["clusters"]]}
                           for p in prog for s in p["schemes"]]}
        for s in rec["schemes"]:
            scope_rows += [(rec["registration_no"], "register", k, f"{s['scheme']} | {cl}")
                           for k, cl in enumerate(s["clusters"], len(scope_rows) + 1)]
        if not a.no_files:
            for d in docs:
                p = c.download_pdf(sess, d["file"], a.out / "annexes" / c.safe_name(d["file"].rsplit("/", 1)[-1]), stats)
                pages = c.pdf_text(p) if p else []
                if p and not "".join(pages).strip():
                    stats["pdf_scanned"] = stats.get("pdf_scanned", 0) + 1
                    continue
                if pages:
                    r = parse_pdf(pages)
                    if r["address"]:
                        rec["register_address"], rec["address"] = rec["address"], r["address"]
                    if r["number"]:
                        rec["registration_no"] = r["number"]
                    rec["issued"], rec["expiry"] = rec["issued"] or r["issued"], rec["expiry"] or r["expiry"]
                    scope_rows = [(rec["registration_no"] if x[0] == rec["short_code"] else x[0], *x[1:])
                                  for x in scope_rows]
                    scope_rows += [(rec["registration_no"], "annex", k, l) for k, l in enumerate(r["lines"], 1)]
        records.append(rec)
    c.write_outputs(a.out, "uaf", records, scope_rows, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
