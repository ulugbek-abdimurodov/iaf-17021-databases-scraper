"""Scrape JASaff (MAFF, Japanese Agricultural Standards) accredited Product Certification Bodies, ISO/IEC 17065.
JASaff publishes no HTML register; MAFF posts three PDF lists (text layer, one table per page):
  general JAS (excluding organic), organic JAS domestic CBs, organic JAS overseas CBs.
No accreditation numbers or dates are published, so registration_no = <list>-<row #>.
Writes jasaff_17065/jasaff_17065_raw.json, scope_lines.csv and the source PDFs."""
import argparse, csv, json, os, re, sys, requests, pdfplumber

B = "https://www.maff.go.jp/e/policies/standard/"
LISTS = {"JAS": (B + "jas/attach/pdf/system-27.pdf", "JAS (excluding organic)"),
         "ORG": (B + "specific/attach/pdf/organic_JAS-114.pdf", "Organic JAS (domestic CB)"),
         "ORGOV": (B + "specific/attach/pdf/organic_JAS-115.pdf", "Organic JAS (overseas CB)")}
H = {"User-Agent": "Mozilla/5.0"}


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def rows(path):
    hdr, out = None, []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            for t in pg.extract_tables():
                for row in t:
                    if any("Name of organization" in (c or "") for c in row):
                        hdr = ["no"] + [clean(c) for c in row[1:]]
                        continue
                    if not hdr:
                        continue
                    d = {k: (v or "") for k, v in zip(hdr, row)}
                    if re.fullmatch(r"\d+", clean(d["no"])):
                        out.append(d)
                    elif out:  # continuation row (cell wrapped over a row/page break)
                        for k, v in d.items():
                            if v:
                                out[-1][k] += ("" if k == "HP Address" else "\n") + v
    return out


def items(text):
    parts = re.split(r"\n\s*-\s*|^\s*-\s*|\s-\s(?=[A-Z])", text)
    return [clean(p) for p in parts if clean(p)]


def main():
    ap = argparse.ArgumentParser(description="JASaff (MAFF) Product Certification Bodies, ISO/IEC 17065")
    ap.add_argument("--out", default="jasaff_17065")
    ap.add_argument("--limit", type=int, help="rows per list")
    ap.add_argument("--no-files", action="store_true", help="reuse already downloaded lists")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "lists"), exist_ok=True)
    recs, lines, ok, bad = [], [], 0, 0
    for code, (url, scheme) in LISTS.items():
        p = os.path.join(a.out, "lists", os.path.basename(url))
        if not (a.no_files and os.path.exists(p)):
            try:
                r = requests.get(url, headers=H, timeout=120)
                r.raise_for_status()
                open(p, "wb").write(r.content)
                ok += 1
            except Exception as e:
                bad += 1
                print("PDF failed", url, e, file=sys.stderr)
        if not os.path.exists(p):
            continue
        for i, d in enumerate(rows(p)[:a.limit], 1):
            no = f"{code}-{i}"  # position in the list: the printed row # restarts on every page
            area = next((v for k, v in d.items() if k.startswith("Certification business")), "")
            recs.append({"registration_no": no, "id": clean(d.get("Abbreviation")),
                         "name": clean(d.get("Name of organization")), "address": clean(d.get("Address")),
                         "phone": clean(d.get("Phone")), "email": "",
                         "website": re.sub(r"\s+", "", d.get("HP Address", "")), "issued": "", "expiry": "",
                         "scheme": scheme, "area_outside_japan": clean(area), "annex_urls": [url]})
            lines += [[no, "register", k, t] for k, t in enumerate(items(d.get("Item to be certified", "")))]
    with open(os.path.join(a.out, "jasaff_17065_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scope_lines.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in recs})}  accreditations: {len(recs)}  "
          f"scope lines: {len(lines)}  PDFs ok/failed: {ok}/{bad}")


if __name__ == "__main__":
    main()
