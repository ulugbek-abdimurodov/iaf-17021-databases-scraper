"""TUNAC ISO/IEC 17065 register scrape (domain "Cert.Produit").

Usage: python scrape_tn_tunac_17065.py [out dir (default ./tunac_17065)] [--force]

Reads the register's JSON agent (same endpoint as ../tunac_scraper.py), keeps the Cert.Produit /
ISO/IEC 17065 records, downloads each technical annex and writes:
  tunac_17065_raw.json  one record per accreditation
  scope_lines.csv       registration_no,source,row_index,product_text_raw (annex text, one row per line)
Scanned annexes (no text layer) are OCRed with PyMuPDF + Tesseract when available, otherwise
annex_transcription.csv (the annex tables transcribed by reading the scans) is used.
"""
import csv, json, re, ssl, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import tunisia.tunac_data.tunac_scraper as ts  # noqa: E402
import warnings; warnings.filterwarnings("ignore")

API = ts.DEFAULT_API
with open(HERE / "annex_transcription.csv", encoding="utf-8") as _fh:  # scans read by eye, one row per table row
    TRANSCRIPTION = list(csv.DictReader(_fh))


def contact(html):
    parts = ts.split_br(html)
    name = ts.strip_tags(parts[0]) if parts else ""
    phone = email = ""
    addr = []
    for p in parts[1:]:
        t = ts.strip_tags(p)
        m = re.search(r"T[ée]l\s*:\s*([^-]*)", t)
        if m:
            phone = m.group(1).strip()
        elif ts.EMAIL_RE.search(t):
            email = ts.EMAIL_RE.search(t).group(0)
        elif addr or re.search(r"\d|rue|avenue|bp|zone|b[âa]timent", t, re.I):
            addr.append(t)
    return name, phone, email, ", ".join(a for a in addr if a)


def links(html):
    out = {}
    for href, label in re.findall(r"href='([^']+)'[^>]*>([^<]*)<", html):
        out.setdefault(label.strip() or "doc", href)
    return out


def pdf_lines(data):
    import pymupdf as fitz
    doc = fitz.open(stream=data, filetype="pdf")
    lines = []
    for page in doc:
        text = page.get_text()
        if len(text.strip()) < 20:
            try:
                text = page.get_textpage_ocr(language="fra+eng", dpi=300, full=True).extractText()
            except Exception:
                text = ""
        lines += [l.strip() for l in text.splitlines() if l.strip()]
    return lines


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else HERE / "tunac_17065"
    force = "--force" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    raw = json.loads(ts.fetch(API, ctx).decode("utf-8", "replace"))
    recs, rows = [], []
    for r in raw:
        dom = ts.strip_tags(r.get("domaine", ""))
        if "17065" not in dom and "Produit" not in dom:
            continue
        reg = ts.strip_tags(r.get("boidps", ""))
        name, phone, email, addr = contact(r.get("ExtNamePS", ""))
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", r.get("logbs", ""))
        docs = links(r.get("attachefiles", ""))
        annex = [u for k, u in docs.items() if k.lower().startswith("annexe")]
        recs.append({"registration_no": reg, "id": r.get("id"), "name": name, "address": addr, "phone": phone,
                     "email": email, "website": "", "issued": dates[0] if dates else "",
                     "expiry": dates[1] if len(dates) > 1 else "", "status": r.get("etatdoc", ""),
                     "descript": ts.strip_tags(r.get("descript", "")), "annex_urls": annex,
                     "certificate_urls": [u for k, u in docs.items() if u not in annex]})
        for u in annex:
            f = out / "pdfs" / f"{reg}.pdf"
            f.parent.mkdir(exist_ok=True)
            if force or not f.exists() or f.stat().st_size < 5000:
                f.write_bytes(ts.fetch(u, ctx))
            lines = pdf_lines(f.read_bytes())
            src = u
            if not lines:  # scanned annex, no OCR engine: use the checked-in transcription
                lines = [t["line"] for t in TRANSCRIPTION if t["registration_no"] == reg]
                src = u + "#transcription"
            for i, line in enumerate(lines):
                rows.append({"registration_no": reg, "source": src, "row_index": i, "product_text_raw": line})
    (out / "tunac_17065_raw.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(rows)
    print(f"Bodies: {len({r['name'] for r in recs})}\nAccreditations: {len(recs)}\n"
          f"Annex lines: {len(rows)}\nAnnexes: {sum(len(r['annex_urls']) for r in recs)}")


if __name__ == "__main__":
    main()
