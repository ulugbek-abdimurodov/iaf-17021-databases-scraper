#!/usr/bin/env python3
"""Download OLAS-accredited Product Certification Bodies (ISO/IEC 17065) from
portail-qualite.public.lu: body details, accreditation certificates, technical annexes
and OLAS's general documents.

Derived from ../olas_17021_scraper.py, whose client, page parser, discovery and downloader
are imported. Only the standard changes: the listing's "ISO/IEC 17065" filter
(activity "Organismes de certification de produits et de services") instead of
"ISO/IEC 17021-1". Robots.txt handling is the MS scraper's: by default only the known body
pages below are read; --discover opts in to the filter pages robots.txt disallows.

Run:  python scrape_lu_olas_17065.py [--out olas_17065] [--discover] [--limit N] [--no-files]
Output: the MS scraper's files (bodies.json, bodies.csv, bodies/<body>/..., general_documents/)
plus olas_17065_raw.json and scope_lines.csv for CertiFind.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import olas_17021_scraper as ms  # noqa: E402

ms.STANDARD = "ISO/IEC 17065"
ms.USER_AGENT = "olas-17065-scraper/1.0 (python-requests)"
# Found with the ISO/IEC 17065 filter on 2026-11-19. Ids can change on renewal; use --discover.
ms.KNOWN_BODY_PATHS = [
    "/fr/accreditation-notification/organismes-accredites/5/20235013.html",  # Luxcontrol a.s.b.l.
    "/fr/accreditation-notification/organismes-accredites/5/20235017.html",  # SIGNA Audit s.à.r.l
    "/fr/accreditation-notification/organismes-accredites/5/20235004.html",  # SNCH
]


def pdf_lines(path: Path):
    """Text lines of a PDF, [] when it has no text layer, None without a PDF library."""
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as exc:  # noqa: BLE001 - a bad PDF is reported, not fatal
        print(f"    cannot read {path.name}: {exc}", file=sys.stderr)
        return []
    return [ms.clean(t) for t in text.splitlines() if ms.clean(t)]


def is_annex(doc) -> bool:
    return bool(re.search(r"annexe|annex|port[ée]e|scope", doc["label"] + " " + doc["url"], re.I))


def write_certifind(out: Path) -> dict:
    data = json.loads((out / "bodies.json").read_text(encoding="utf-8"))
    raw, lines = [], []
    stats = {"annexes_with_text": 0, "annexes_without_text": [], "no_pdf_library": False}
    for body in data["bodies"]:
        reg = body["accreditation_number"] or body["name"]
        raw.append({
            "registration_no": reg, "id": ms.body_key(body["page_url"]), "name": body["name"],
            "address": ", ".join(body["address"]), "phone": "", "email": "", "website": "",
            "issued": body["issued_on"], "expiry": body["valid_until"],
            "standards": body["standards"], "activities": body.get("activities"),
            "domains": body.get("domains"), "page_url": body["page_url"],
            "annex_urls": [d["url"] for d in body["documents"] if is_annex(d)],
            "certificate_urls": [d["url"] for d in body["documents"] if not is_annex(d)],
        })
        for i, domain in enumerate(body.get("domains") or []):
            lines.append([reg, "register", i, domain])
        for doc in body["documents"]:
            if not is_annex(doc) or "file" not in doc or not doc["file"].lower().endswith(".pdf"):
                continue
            text = pdf_lines(out / doc["file"])
            if text is None:
                stats["no_pdf_library"] = True
            elif text:
                stats["annexes_with_text"] += 1
                name = Path(doc["file"]).name
                lines += [[reg, f"annex:{name}", i, t] for i, t in enumerate(text)]
            else:
                stats["annexes_without_text"].append(doc["file"])
    (out / "olas_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    with (out / "scope_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    stats["scope_lines"] = len(lines)
    stats["bodies"] = len(data["bodies"])
    stats["documents"] = sum("file" in d for b in data["bodies"] for d in b["documents"])
    stats["failed"] = sum("error" in d and d["error"] != "skipped (--no-files)"
                          for b in data["bodies"] for d in b["documents"])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_out = Path(__file__).resolve().parent / "olas_17065"
    parser.add_argument("--out", default=str(default_out), help="output folder (default: %(default)s)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--discover", action="store_true",
                        help="opt in to the filter pages robots.txt disallows (finds current bodies)")
    parser.add_argument("--limit", type=int, default=0, help="only the first N bodies")
    parser.add_argument("--no-files", action="store_true", help="skip document downloads")
    args = parser.parse_args()

    if args.limit:
        ms.KNOWN_BODY_PATHS = ms.KNOWN_BODY_PATHS[: args.limit]
        _discover = ms.discover
        ms.discover = lambda client, url: (lambda r: (r[0][: args.limit], r[1]))(_discover(client, url))
    if args.no_files:
        def _skip(client, document, folder, used, out):
            document["error"] = "skipped (--no-files)"
            return True
        ms.download_document = _skip

    sys.argv = [sys.argv[0], "--out", args.out, "--delay", str(args.delay)] + \
               (["--discover"] if args.discover else [])
    code = ms.main()
    out = Path(args.out)
    if not (out / "bodies.json").exists():
        return code or 1
    s = write_certifind(out)
    print(f"bodies: {s['bodies']}  scope lines: {s['scope_lines']}  documents downloaded: "
          f"{s['documents']} failed: {s['failed']}  annexes with text: {s['annexes_with_text']} "
          f"without text: {len(s['annexes_without_text'])}"
          + ("  (pdfplumber missing: annex text not extracted)" if s["no_pdf_library"] else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
