#!/usr/bin/env python3
"""Download TURKAK Product Certification (ISO/IEC 17065, institution type "U") bodies and annexes.

Built on ../17021/turkak_scraper.py (same API, detail call and signed-PDF download); only the institution type
(U = Ürün / product, codes AB-nnnn-U) and the output folder differ.

    python scrape_tr_turkak_17065.py [--out turkak_17065] [--limit N] [--no-pdf] [--force]

Output (default ./turkak_17065): the MS scraper's files (accreditations.json/.csv, branches.csv, pdfs/) plus
    turkak_17065_raw.json  one record per accreditation
    scope_lines.csv        registration_no,source,row_index,product_text_raw: one row per annex table row,
                           cells joined with " | " (tables read with PyMuPDF from the English certificate,
                           or the Turkish one when no English certificate is published)
"""
import contextlib, csv, io, json, sys, warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "17021"))
import turkak_scraper as ts  # noqa: E402

ts.INSTITUTION_TYPE = "U"   # Product Certification
ts.CODE_SUFFIX = "-U"
warnings.filterwarnings("ignore")


def table_rows(pdf):
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    rows = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            with contextlib.redirect_stdout(io.StringIO()):
                tables = page.find_tables().tables
            for t in tables:
                for r in t.extract():
                    cells = []
                    for c in r:
                        c = " ".join((c or "").split())
                        if c and c not in cells:
                            cells.append(c)
                    if cells:
                        rows.append(" | ".join(cells))
    return rows


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--out" not in argv:
        argv = ["--out", str(HERE / "turkak_17065")] + argv
    out = Path(argv[argv.index("--out") + 1])
    with contextlib.redirect_stdout(io.StringIO()):
        code = ts.main(argv)
    records = json.loads((out / "accreditations.json").read_text(encoding="utf-8"))
    raw, lines = [], []
    for rec in records:
        d = rec.get("Detail") or {}
        reg = rec.get("Code", "")
        pdf = out / "pdfs" / f"{ts.safe_name(reg)}_EN.pdf"
        raw.append({"registration_no": reg, "id": rec.get("ID"), "name": rec.get("DisplayTitle", ""),
                    "address": d.get("FullAddress", ""), "city": d.get("CityName", ""),
                    "phone": d.get("PhoneNumber", ""), "email": d.get("EMail", ""), "website": d.get("Website", ""),
                    "issued": (d.get("AccreditationDate") or "")[:10], "expiry": (d.get("ValidityDate") or "")[:10],
                    "status": rec.get("StatusName", ""), "standard": d.get("StandardCode", ""),
                    "detail_url": d.get("HTMLPreviewLink", ""),
                    "annex_urls": [d["ShowENCert"]] if d.get("ShowENCert") else [],
                    "annex_lang": "en",
                    "branches": [{"title": b.get("Title"), "address": b.get("FullAddress"), "city": b.get("CityName")}
                                 for b in d.get("InstituteFacilities") or []]})
        source = d.get("ShowENCert", pdf.name)
        if not pdf.exists() and d.get("ShowTRCert") and "--no-pdf" not in argv:
            # no English certificate: fall back to the Turkish one, as the 17021 dataset does
            pdf = out / "pdfs" / f"{ts.safe_name(reg)}_TR.pdf"
            source = d["ShowTRCert"]
            guid = ts.guid_from_url(source)
            if guid and not ts.is_pdf(pdf):
                try:
                    ts.Scraper(ts.make_session(), ts.API_BASE, "tr", 0.5).download_pdf(guid, pdf)
                except Exception as exc:
                    print(f"{reg}: Turkish PDF failed: {exc}", file=sys.stderr)
            raw[-1]["annex_urls"] = [source]
            raw[-1]["annex_lang"] = "tr"
        if pdf.exists():
            for i, row in enumerate(table_rows(pdf)):
                lines.append({"registration_no": reg, "source": source,
                              "row_index": i, "product_text_raw": row})
    (out / "turkak_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(lines)
    print(f"Bodies: {len({r['name'] for r in raw})}\nAccreditations: {len(raw)}\n"
          f"Annex rows: {len(lines)}\nFetch failures: {0 if code == 0 else 'see failures.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
