"""Scrape KOLAS (Korea Laboratory Accreditation Scheme, KATS) Product Certification Bodies, ISO/IEC 17065.

Register: https://www.knab.go.kr/usr/inf/srh/InfoProductInsttSearchList.do (제품인증기관, accredit code '07').
KAB (kab.or.kr) has no 17065 scheme (MS + persons only) and NIER accredits GHG verifiers (ISO 14065),
so KOLAS is the only Korean 17065 register.
List (10 rows/page, POST pageNo) -> detail (POST accredit, companyNo, accreditNo) -> accreditation
certificate PDFs (KR + EN) via /cmm/FileDownload.do?p=<token>. Certificates are scans (no text layer);
the product scope comes from the detail page table (대분류 / 중분류 / 비고).
Writes kolas_17065/kolas_17065_raw.json, scope_lines.csv and certificates/."""
import argparse, csv, json, os, re, sys, urllib.parse
import truststore
truststore.inject_into_ssl()  # knab.go.kr's chain is only trusted via the Windows certificate store
import requests
from bs4 import BeautifulSoup

BASE = "https://www.knab.go.kr"
LIST = BASE + "/usr/inf/srh/InfoProductInsttSearchList.do"
DETAIL = BASE + "/usr/inf/srh/InfoProductInsttDetail.do"
FILE = BASE + "/cmm/FileDownload.do?p="


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def soup(s, url, data):
    r = s.post(url, data=data, timeout=60)
    r.raise_for_status()
    return BeautifulSoup(r.content, "html.parser")


def list_rows(s):
    out, page = [], 1
    while True:
        b = soup(s, LIST, {"pageNo": page})
        rows = [tr for tr in b.select("table tbody tr") if tr.find("a", href=re.compile(r"detail\("))]
        for tr in rows:
            td = tr.find_all("td")
            m = re.search(r"detail\('(\w+)',\s*(\d+),\s*(\d+)\)", td[1].a["href"])
            files = [re.search(r"'([^']+)'", a["href"]).group(1) if a.get("href") and "fileUploadDownload" in a["href"] else ""
                     for a in (c.find("a") or {} for c in td[4:6])]
            valid = re.findall(r"\d{4}-\d\d-\d\d", td[2].get_text())
            out.append({"registration_no": clean(td[0].get_text()), "name": clean(td[1].get_text()),
                        "accredit": m.group(1), "companyNo": m.group(2), "accreditNo": m.group(3),
                        "issued": valid[0] if valid else "", "expiry": valid[1] if len(valid) > 1 else "",
                        "region": clean(td[3].get_text()), "iaf_mark": clean(td[6].get_text()) if len(td) > 6 else "",
                        "files": files})
        total = int(b.find("input", {"name": "totalCount"})["value"] or 0)
        if not rows or len(out) >= total:
            return out
        page += 1


def detail(s, r):
    b = soup(s, DETAIL, {"accredit": r["accredit"], "companyNo": r["companyNo"], "accreditNo": r["accreditNo"], "pageNo": 1})
    f = {}
    for tr in b.select("table tr"):
        c = [clean(x.get_text(" ")) for x in tr.find_all(["th", "td"])]
        for k, v in zip(c[::2], c[1::2]):
            f.setdefault(k, v)
    scope, hdr = [], None
    for tr in b.select("table tr"):
        c = [clean(x.get_text(" ")) for x in tr.find_all(["th", "td"])]
        if c[:2] == ["대분류", "중분류"]:
            hdr = c
            continue
        if hdr and len(c) == len(hdr):
            scope.append(" | ".join(x.lstrip("▶") for x in c if x))
    return f, scope


def main():
    ap = argparse.ArgumentParser(description="KOLAS Product Certification Bodies, ISO/IEC 17065")
    ap.add_argument("--out", default="kolas_17065")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    cdir = os.path.join(a.out, "certificates")
    os.makedirs(cdir, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    recs, lines, ok, bad, notext = [], [], 0, 0, 0
    for r in list_rows(s)[:a.limit]:
        f, scope = detail(s, r)
        urls = [FILE + urllib.parse.quote(t, safe="/=") for t in r["files"] if t]
        rec = {"registration_no": r["registration_no"], "id": r["companyNo"], "name": r["name"],
               "address": f.get("주소", ""), "phone": f.get("전화 번호", ""), "fax": f.get("팩스 번호", ""),
               "contact_person": f.get("담당자", ""), "email": "", "website": "",
               "issued": r["issued"], "expiry": r["expiry"], "region": r["region"], "iaf_mark": r["iaf_mark"],
               "scope_field": f.get("인정범위", ""), "annex_urls": urls}
        recs.append(rec)
        lines += [[rec["registration_no"], "register", i, t] for i, t in enumerate(scope)]
        for lang, u in zip(["kr", "en"], urls if not a.no_files else []):
            p = os.path.join(cdir, f"{rec['registration_no']}_{lang}.pdf")
            try:
                if not os.path.exists(p):  # resume
                    resp = s.get(u, timeout=120)
                    resp.raise_for_status()
                    if not resp.content.startswith(b"%PDF"):
                        raise ValueError("not a PDF")
                    open(p, "wb").write(resp.content)
                ok += 1
            except Exception as e:
                bad += 1
                print("PDF failed", rec["registration_no"], lang, e, file=sys.stderr)
                continue
            try:
                import pdfplumber
                with pdfplumber.open(p) as pdf:
                    txt = [clean(l) for pg in pdf.pages for l in (pg.extract_text() or "").splitlines() if clean(l)]
            except Exception:
                txt = []
            notext += not txt
            lines += [[rec["registration_no"], f"certificate_{lang}", i + 1, t] for i, t in enumerate(txt)]
        print(rec["registration_no"], rec["name"], len(scope), "scope rows", file=sys.stderr)
    with open(os.path.join(a.out, "kolas_17065_raw.json"), "w", encoding="utf-8") as fh:
        json.dump(recs, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in recs})}  accreditations: {len(recs)}  scope lines: {len(lines)}  "
          f"PDFs ok/failed: {ok}/{bad}  without text layer: {notext}")


if __name__ == "__main__":
    main()
