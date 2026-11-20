"""Scrape IAJapan (NITE, ASNITE) Product Certification Bodies, ISO/IEC 17065, from
https://www.nite.go.jp/en/iajapan/asnite/lab/index_asnite_product_e.html
Each body has 3 table rows: id/name, scope (per-programme PDF links), address/contact. Only the
[Product Certification] part of the scope and its PDF are kept (bodies may also hold C/T/RMP accreditations).
Writes iajapan_17065/iajapan_17065_raw.json, scope_lines.csv and annex PDFs."""
import argparse, csv, json, os, re, sys, requests
from bs4 import BeautifulSoup, NavigableString

BASE = "https://www.nite.go.jp"
URL = BASE + "/en/iajapan/asnite/lab/index_asnite_product_e.html"
H = {"User-Agent": "Mozilla/5.0"}
PROD = "Product Certification"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse(html):
    rows = BeautifulSoup(html, "html.parser").find_all("tr")
    out = []
    for i, tr in enumerate(rows):
        tds = tr.find_all(["td", "th"])
        if not tds or not re.match(r"ASNITE \d+", clean(tds[0].get_text(" "))):
            continue
        idt = clean(tds[0].get_text(" "))
        reg = re.match(r"ASNITE \d+", idt).group(0)
        nm = clean(tds[1].get_text(" ")) if len(tds) > 1 else ""
        jcn = re.search(r"JCN\s*(\d+)", nm)
        name = clean(re.sub(r"JCN\s*\d+", "", nm))
        prog, scope, pdfs = None, [], []
        for el in rows[i + 1].find(["td", "th"]).descendants:
            if isinstance(el, NavigableString):
                for part in re.split(r"(\[[^\]]+\]:)", str(el)):
                    m = re.match(r"\[([^\]]+)\]:", part)
                    if m:
                        prog = m.group(1)
                    elif prog == PROD:
                        scope.append(part)
            elif el.name == "a" and prog == PROD and el.get("href", "").endswith(".pdf"):
                pdfs.append(BASE + el["href"] if el["href"].startswith("/") else el["href"])
        ac = [clean(td.get_text(" ")) for td in rows[i + 2].find_all(["td", "th"])]
        contact = ac[1] if len(ac) > 1 else ""
        out.append({"registration_no": reg, "id": jcn.group(1) if jcn else "", "name": name,
                    "address": ac[0] if ac else "",
                    "phone": "; ".join(p.strip() for p in re.findall(r"\+?\d[\d\-() ]{7,}\d", contact)),
                    "email": "", "website": "", "issued": "", "expiry": "",
                    "programs": idt.replace(reg, "").strip(),
                    "scope": clean(re.sub(r"\[PDF:[^\]]*\]", "", " ".join(scope))), "annex_urls": pdfs})
    return out


def pdf_lines(path):
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return [clean(l) for p in pdf.pages for l in (p.extract_text() or "").splitlines() if clean(l)]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description="IAJapan (ASNITE) Product Certification Bodies, ISO/IEC 17065")
    ap.add_argument("--out", default="iajapan_17065")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "annexes"), exist_ok=True)
    recs = parse(requests.get(URL, headers=H, timeout=60).content)[:a.limit]
    lines, ok, bad, notext = [], 0, 0, 0
    for r in recs:
        if r["scope"]:
            lines.append([r["registration_no"], "register", 0, r["scope"]])
        for u in [] if a.no_files else r["annex_urls"]:
            p = os.path.join(a.out, "annexes", f"{r['registration_no'].replace(' ', '_')}_{os.path.basename(u)}")
            try:
                if not os.path.exists(p):  # resume
                    resp = requests.get(u, headers=H, timeout=120)
                    resp.raise_for_status()
                    open(p, "wb").write(resp.content)
                ok += 1
            except Exception as e:
                bad += 1
                print("PDF failed", u, e, file=sys.stderr)
                continue
            pl = pdf_lines(p)
            notext += not pl
            lines += [[r["registration_no"], "annex", k + 1, l] for k, l in enumerate(pl)]
    with open(os.path.join(a.out, "iajapan_17065_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len(recs)}  accreditations: {len(recs)}  scope lines: {len(lines)}  "
          f"PDFs ok/failed: {ok}/{bad}  without text layer: {notext}")


if __name__ == "__main__":
    main()
