"""Scrape ANAB (ANSI National Accreditation Board) ISO/IEC 17065 Product Certification Bodies.

Derived from ../database/usa/scrape_us_anab.py (MS). The MS register (anabdirectory.remoteauditor.com) holds
management systems only: its standard list has no 17065 entry, and the product group on search.anab.org is
empty. ANAB's product certification bodies are in the separate ANSI product directory
(linked from anab.ansi.org/resource/product-certification-bodies-accreditation-directory/):

  listing : https://anabpd.ansi.org/Accreditation/product-certification/AllDirectoryListing?prgID=1&statusID=<s>
            prgID=1 = "Product Certification Accreditation Program"; statusID 4 = accredited (113 on 2026-11-19),
            3 = applicant, 7 = scope extension, 1/5/6 = other lists (no label on the page); all are collected
            and the statusID is kept per record.
  detail  : AllDirectoryDetails.aspx?prgID=1&OrgId=<id>&statusID=<s>  table rows "label | value":
            Accreditation ID, Organization (name + address), Letter Code, Website, Accreditation Certificate
            (/Accreditation/FileServer.aspx link), then "Accredited Scopes": nested <h6> headings, one per scope line.

anabpd.ansi.org is behind a Cloudflare browser check, so (like the 2026-11-10 MS run) the collection runs in a
normal logged-out browser tab on anabpd.ansi.org, with the JS printed by --print-js. It saves
anab_17065_browser.json (Downloads). This script then converts that file:

  python scrape_us_anab_17065.py --print-js            # paste into the console on an anabpd.ansi.org page
  python scrape_us_anab_17065.py --from-json <path>    # -> anab_17065/anab_17065_raw.json, scope_lines.csv
Scopes come from the register HTML, so no PDF is needed; the certificate URLs are kept in annex_urls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import us_17065_common as c  # noqa: E402

STATUS = {"1": "status 1", "3": "applicant", "4": "accredited", "5": "status 5", "6": "status 6",
          "7": "scope extension"}

JS = r"""
(async () => {
  const LIST = '/Accreditation/product-certification/AllDirectoryListing';
  const STATUSES = [4, 3, 7, 5, 6, 1];
  const out = [];
  const parse = h => new DOMParser().parseFromString(h, 'text/html');
  for (const s of STATUSES) {
    const d = parse(await (await fetch(`${LIST}?prgID=1&statusID=${s}`)).text());
    const links = [...d.querySelectorAll('a[href*="Details"]')];
    for (const a of links) {
      const url = new URL(a.getAttribute('href'), location.href).href;
      const row = a.closest('tr');
      const rec = {status_id: s, list_name: a.textContent.trim(), url, fields: {}, scopes: [], files: [],
                   list_id: row ? row.cells[row.cells.length - 1].textContent.trim() : ''};
      try {
        const dd = parse(await (await fetch(url)).text());
        dd.querySelectorAll('script,style').forEach(x => x.remove());
        for (const tr of dd.querySelectorAll('tr')) {
          const td = [...tr.children].filter(x => x.tagName === 'TD');
          if (td.length === 2) rec.fields[td[0].innerText.trim()] = td[1].innerText.trim();
        }
        rec.files = [...dd.querySelectorAll('a[href*="FileServer"]')].map(x => ({label: x.textContent.trim(),
                     url: new URL(x.getAttribute('href'), location.href).href}));
        rec.websites = [...dd.querySelectorAll('a[href^="http"]')].map(x => x.href)
                       .filter(h => !/ansi\.org|remoteauditor/.test(h));
        const h3 = [...dd.querySelectorAll('h3')].find(x => /Accredited Scopes/.test(x.textContent));
        const box = h3 ? h3.closest('tr').nextElementSibling : null;
        if (box) for (const h6 of box.querySelectorAll('h6')) {
          let depth = 0, e = h6.parentElement;
          while (e && e !== box) { if (e.tagName === 'DIV') depth++; e = e.parentElement; }
          rec.scopes.push({depth, text: h6.textContent.replace(/\s+/g, ' ').trim()});
        }
      } catch (err) { rec.error = String(err); }
      out.push(rec);
      await new Promise(r => setTimeout(r, 300));
    }
    console.log('statusID', s, links.length);
  }
  const blob = new Blob([JSON.stringify(out)], {type: 'application/json'});
  const a = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob),
                          download: 'anab_17065_browser.json'});
  document.body.appendChild(a); a.click();
  return out.length;
})();
"""


def field(f: dict, *names: str) -> str:
    for n in names:
        for k, v in f.items():
            if k.lower().rstrip(":") == n.lower():
                return v
    return ""


def convert(src: Path, out: Path) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    records, scope_rows, seen = [], [], set()
    for r in data:
        if re.search(r"\bTEST CB\b", r["list_name"], re.I):
            continue
        f = r.get("fields", {})
        lid = r.get("list_id", "")
        reg = field(f, "Accreditation ID") or (lid if re.fullmatch(r"\d+", lid) else "") or (re.search(r"OrgId=(\d+)", r["url"]) or [0, ""])[1]
        key = (reg, r["status_id"])
        if key in seen:
            continue
        seen.add(key)
        org = field(f, "Organization")
        name = r["list_name"]
        address = org[len(name):].lstrip(" ,") if org.startswith(name) else org
        web = field(f, "Website") or next(iter(r.get("websites", [])), "")
        rec = {"registration_no": reg, "id": (re.search(r"OrgId=(\d+)", r["url"]) or [0, ""])[1], "name": name,
               "address": address, "phone": field(f, "Phone", "Telephone"), "email": field(f, "Email", "E-mail"),
               "website": web, "issued": field(f, "Initial Accreditation Date", "Accreditation Date"),
               "expiry": field(f, "Expiration Date", "Expiry Date"),
               "annex_urls": [x["url"] for x in r.get("files", [])], "status": STATUS.get(str(r["status_id"]),
                                                                                         str(r["status_id"])),
               "status_id": r["status_id"], "letter_code": field(f, "Letter Code"), "url": r["url"],
               "fields": {k: v for k, v in f.items() if k != "Accredited Scopes"}}
        if r.get("error"):
            rec["error"] = r["error"]
        records.append(rec)
        path: list[str] = []
        for i, s in enumerate(r.get("scopes", []), 1):
            path = path[: s["depth"]] + [s["text"]]
            scope_rows.append((reg, "register", i, " > ".join(path)))
    c.write_outputs(out, "anab", records, scope_rows, {})


def main() -> int:
    ap = argparse.ArgumentParser(description="ANAB ISO/IEC 17065 Product Certification Bodies scraper")
    ap.add_argument("--print-js", action="store_true", help="print the browser collector")
    ap.add_argument("--from-json", type=Path, help="anab_17065_browser.json saved by the collector")
    ap.add_argument("--out", type=Path, default=HERE / "anab_17065")
    a = ap.parse_args()
    if a.print_js or not a.from_json:
        print(JS)
        return 0
    convert(a.from_json, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
