"""EAS (Ethiopia) ISO/IEC 17065 product certification bodies.
Register https://eas-eth.org/certification-bodies/ lists all bodies in one table; the product bodies are the
rows whose Disciplines mention 17065 (cert no. CPr####). Detail page -> contacts + schedule PDF.
Outputs (in --out): eas_17065_raw.json, scope_lines.csv, pdfs/<reg>.pdf"""
import argparse, csv, json, re, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://eas-eth.org/certification-bodies/"
H = {"User-Agent": "Mozilla/5.0"}
FILTER = re.compile(r"17065", re.I)


def get(url, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, headers=H, timeout=60, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            err = e
    raise err


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def pdf_lines(path):
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    out = []
    with pymupdf.open(path) as d:
        for p in d:
            out += [clean(l) for l in p.get_text().splitlines() if clean(l)]
    return out


def main():
    ap = argparse.ArgumentParser(description="EAS Ethiopia product certification bodies (ISO/IEC 17065)")
    ap.add_argument("--out", default=str(Path(__file__).parent / "eas_17065"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); (out / "pdfs").mkdir(parents=True, exist_ok=True)

    soup = BeautifulSoup(get(BASE).text, "html.parser")
    rows = []
    for tr in soup.select("article table tr"):
        td = tr.find_all("td")
        if len(td) >= 4 and td[0].find("a") and FILTER.search(td[3].get_text()):
            rows.append((clean(td[0].get_text()), td[0].find("a")["href"], clean(td[1].get_text()),
                         clean(td[2].get_text()), clean(td[3].get_text())))
    rows = rows[: a.limit] if a.limit else rows

    recs, lines, ok, fail = [], [], 0, 0
    for reg, url, name, loc, disc in rows:
        d = BeautifulSoup(get(url).text, "html.parser")
        f = {}
        for tr in d.select("article table tr"):
            td = tr.find_all("td")
            if len(td) >= 2:
                f[clean(td[0].get_text())] = (clean(td[1].get_text(" ")), td[1])
        g = lambda k: f.get(k, ("", None))[0]
        pdf = next((x["href"] for x in d.select("article a[href]") if x["href"].lower().endswith(".pdf")), None)
        recs.append(dict(registration_no=reg, id=reg, name=g("Name") or name, address=g("Physical Address") or loc,
                         phone=g("Telephone"), email=g("Representative Email"), website=g("Website"),
                         issued="", expiry="", annex_urls=[pdf] if pdf else [], page=url, disciplines=disc))
        lines.append((reg, "register", 0, disc))
        if pdf and not a.no_files:
            try:
                p = out / "pdfs" / f"{reg}.pdf"
                p.write_bytes(get(pdf).content)
                ls = pdf_lines(p)
                print(f"{reg}: pdf {len(ls)} text lines" + ("" if ls else " (NO text layer: scanned)"))
                lines += [(reg, "annex", i, l) for i, l in enumerate(ls, 1)]
                ok += 1
            except Exception as e:
                print(f"{reg}: pdf failed {e}", file=sys.stderr); fail += 1
    (out / "eas_17065_raw.json").write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf8") as fh:
        w = csv.writer(fh); w.writerow(["registration_no", "source", "row_index", "product_text_raw"]); w.writerows(lines)
    print(f"bodies={len(recs)} accreditations={len(recs)} scope_lines={len(lines)} pdfs_ok={ok} failed={fail}")
    for r in recs: print(" ", r["registration_no"], r["name"])


if __name__ == "__main__":
    main()
