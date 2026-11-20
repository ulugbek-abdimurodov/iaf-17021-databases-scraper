"""KENAS (Kenya) - Product Certification Bodies (ISO/IEC 17065) + schedule PDFs.

Register: https://kenas.go.ke/status (Nuxt SPA: cards are rendered client-side, so the static parsing in
scrape_ke_kenas.py no longer sees them). Filter = card category line "Certification Bodies, Product Certification"
(plus KENAS/CB/035, categorised "Process Certification"). The records were captured from the rendered DOM on
2026-11-20 into register_snapshot.py; use --live to re-capture with Playwright (if installed).
Outputs: kenas_17065_raw.json, scope_lines.csv, pdfs/
"""
import argparse, csv, json, re, sys
from pathlib import Path
import requests

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from register_snapshot import R

JS = r"""()=>[...document.querySelectorAll('.action-buttons')].map(ab=>{let c=ab.parentElement;
while(c.parentElement&&!/^\s*\S*AS\/\S+/.test(c.innerText))c=c.parentElement;
const t=c.innerText.split('\n').map(s=>s.trim()).filter(Boolean);const a=[...ab.querySelectorAll('a')];
return {t,cert:a[0]&&a[0].href,schedule:a[1]&&a[1].href}})"""


def live():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto("https://kenas.go.ke/status")
        pg.wait_for_timeout(5000)
        cards = pg.evaluate(JS)
        b.close()
    out = []
    for o in cards:
        t = o["t"]
        if len(t) > 40 or not re.search(r"Certification Bodies, (Product|Process)", " | ".join(t)):
            continue
        i, p_, e, k = t.index("Expiry Date/Status"), t.index("Phone"), t.index("Email"), t.index("VIEW CERTIFICATE")
        out.append((t[0], t[1], ", ".join(t[2:i]), t[i + 1], "; ".join(t[p_ + 1:e]), "; ".join(t[e + 1:k - 1]),
                    o["cert"], o["schedule"]))
    return out


def main():
    ap = argparse.ArgumentParser(description="KENAS Product Certification Bodies (ISO/IEC 17065)")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.out)
    rows = live() if a.live else R
    rows = rows[:a.limit] if a.limit else rows
    pdir = out / "pdfs"
    pdir.mkdir(exist_ok=True)
    recs, lines, got, failed = [], [], 0, 0
    for rid, name, addr, exp, ph, em, cert, sched in rows:
        if not a.no_files:
            for kind, u in (("certificate", cert), ("schedule", sched)):
                f = pdir / (re.sub(r"\W", "_", rid) + "_" + kind + ".pdf")
                try:
                    bts = requests.get(u, timeout=60).content
                except Exception:
                    failed += 1
                    continue
                i0 = bts.find(b"%PDF")  # some uploads are wrapped in multipart-form boundaries
                if i0 < 0:
                    failed += 1
                    continue
                i1 = bts.rfind(b"%%EOF")
                bts = bts[i0:i1 + 5] if i1 > i0 else bts[i0:]
                f.write_bytes(bts)
                got += 1
                if kind == "schedule":
                    try:
                        from pypdf import PdfReader
                        txt = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(f)).pages)
                        for n, l in enumerate(x.strip() for x in txt.split("\n") if x.strip()):
                            lines.append((rid, "annex_pdf", n, l))
                    except Exception:
                        pass
        recs.append({"registration_no": rid, "id": rid, "name": name, "address": addr, "phone": ph, "email": em,
                     "website": "", "issued": "", "expiry": exp, "annex_urls": [sched], "certificate_url": cert})
    (out / "kenas_17065_raw.json").write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"Bodies: {len(recs)} | Accreditations: {len(recs)} | Scope lines: {len(lines)} | PDFs ok: {got} failed: {failed}")


if __name__ == "__main__":
    main()
