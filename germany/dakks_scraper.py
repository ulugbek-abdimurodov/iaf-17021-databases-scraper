#!/usr/bin/env python3
"""Scrape DAkkS accredited bodies, their certificates and annexes.

Default target: management system certification bodies (type ZM), all statuses.

    pip install requests beautifulsoup4 openpyxl pypdf
    python dakks_scraper.py

Output (in ./dakks_ZM unless --out is given):
    accreditations.json / .csv   one row per accreditation number
    bodies.json / .csv           one row per body (e.g. D-ZM-11321)
    documents.csv                one row per PDF, with type, language, size, sha256
    dakks_ZM.xlsx                the three tables as sheets (needs openpyxl)
    pdf/<body>/<file>.pdf        certificates (-00) and annexes (-01, -02, ...)
    text/<body>/<file>.txt       PDF text (needs pypdf; skip with --no-text)
    cache/details/<id>.html      detail pages, reused when re-running
    run_report.json              counts, completeness check, failures

Safe to re-run: existing PDFs and cached detail pages are skipped, so an
interrupted run continues where it stopped. Use --refresh to re-download all.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.dakks.de/"
SEARCH_PATH = "de/akkreditierte-stellen-suche.html"
RESULT_PATH = "de/akkreditierte-stellen-suchergebnis.html"
DETAIL_PATH = "de/akkreditierte-stelle.html"

TYPES = {
    "PL": "Prüflaboratorium",
    "K": "Kalibrierlaboratorium",
    "ML": "Medizinisches Laboratorium",
    "IS": "Inspektionsstelle",
    "ZE": "Zertifizierungsstelle für Produkte, Prozesse und Dienstleistungen",
    "ZM": "Zertifizierungsstelle für Managementsysteme",
    "ZP": "Zertifizierungsstelle für Personen",
    "VS": "Verifizierungs-/Validierungsstelle",
    "EP": "Anbieter von Eignungsprüfungen",
    "RM": "Hersteller von Referenzmaterialien",
    "BB": "Biobanken",
}
STATUSES = {"all": None, "A": "Aktiv", "T": "Teilweise ausgesetzt",
            "R": "Vollständig ausgesetzt", "Z": "Zurückgezogen"}

ID_RE = re.compile(r"\bD-[A-Z]{1,3}-\d+-\d+-\d+\b")
# "D-ZM-11321-01-00 | Gültig seit: 22.08.2025" / "... | Zurückgezogen seit: 30.06.2026"
META_RE = re.compile(r"(D-[A-Z]{1,3}-\d+-\d+-\d+)\s*\|\s*(.+?)\s+seit:\s*(\d{2}\.\d{2}\.\d{4})")
HITS_RE = re.compile(r"Treffer:\s*(\d+)")
PDF_NAME_RE = re.compile(r"^(D-[A-Z]{1,3}-\d+-\d+-\d+)(e?)\.pdf$", re.I)

log = logging.getLogger("dakks")


# --------------------------------------------------------------------- HTTP
class Client:
    def __init__(self, delay: float, timeout: int = 60, retries: int = 5):
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "dakks-scraper/1.0 (python-requests)"
        self._last = 0.0

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        for attempt in range(1, self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.s.request(method, url, **kw)
            except requests.RequestException as e:
                err, retry_after = str(e), None
            else:
                if r.status_code < 400:
                    if "html" in r.headers.get("Content-Type", ""):
                        r.encoding = "utf-8"
                    return r
                if r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                err, retry_after = f"HTTP {r.status_code}", r.headers.get("Retry-After")
            if attempt == self.retries:
                raise RuntimeError(f"{method} {url} failed after {attempt} tries: {err}")
            pause = int(retry_after) if str(retry_after).isdigit() else 2 ** attempt
            log.warning("%s (try %d/%d), waiting %ds", err, attempt, self.retries, pause)
            time.sleep(pause)
        raise AssertionError("unreachable")


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def text_of(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


# ------------------------------------------------------------------ parsing
def parse_address(address: str) -> dict:
    parts = [p.strip() for p in address.split(",") if p.strip()]
    out = {"street": "", "postcode": "", "city": "", "country": ""}
    if len(parts) >= 2:
        out["country"] = parts[-1]
        m = re.match(r"^(\S*\d\S*)\s+(.+)$", parts[-2])
        if m:
            out["postcode"], out["city"] = m.groups()
        else:
            out["city"] = parts[-2]
        out["street"] = ", ".join(parts[:-2])
    return out


def parse_docs(teaser) -> list[dict]:
    docs = []
    for a in teaser.select("a.mod-as-list-teaser__link--download"):
        url = urljoin(BASE_URL, a.get("href", ""))
        name = urlsplit(url).path.rsplit("/", 1)[-1]
        m = PDF_NAME_RE.match(name)
        sub = m.group(1).rsplit("-", 1)[-1] if m else ""
        docs.append({
            "accreditation_id": m.group(1) if m else "",
            # Checked on real files: -00 is the Akkreditierungsurkunde,
            # the other suffixes are the Anlage zur Akkreditierungsurkunde.
            "document_type": "certificate" if sub == "00" else "annex" if sub else "unknown",
            "language": "EN" if m and m.group(2) else "DE",
            "label": text_of(a),
            "url": url,
            "filename": name,
        })
    return docs


def parse_meta(teaser) -> dict:
    raw = text_of(teaser.select_one(".mod-as-list-teaser__meta"))
    m = META_RE.search(raw)
    if m:
        label = m.group(2)
        status = "Aktiv" if label.lower().startswith("gültig") else label
        return {"accreditation_id": m.group(1), "status": status,
                "status_since": m.group(3), "meta_raw": raw}
    idm = ID_RE.search(raw)
    return {"accreditation_id": idm.group(0) if idm else "", "status": "",
            "status_since": "", "meta_raw": raw}


def parse_teaser(teaser) -> dict:
    head = teaser.select_one(".mod-as-list-teaser__headline")
    address = text_of(teaser.select_one(".mod-as-list-teaser__description"))
    rec = {"category": text_of(teaser.select_one(".mod-as-list-teaser__category")),
           "name": text_of(head), "address": address, **parse_address(address),
           **parse_meta(teaser), "documents": parse_docs(teaser)}
    aid = rec["accreditation_id"]
    rec["detail_url"] = urljoin(BASE_URL, f"{DETAIL_PATH}?id={aid}") if aid else ""
    return rec


def parse_results(html: str) -> tuple[int | None, list[dict]]:
    soup = soup_of(html)
    m = HITS_RE.search(soup.get_text(" "))
    hits = int(m.group(1)) if m else None
    teasers = [t for t in soup.select(".mod-as-list-teaser")
               if "mod-as-list-teaser--other" not in t.get("class", [])]
    return hits, [parse_teaser(t) for t in teasers]


def parse_detail(html: str) -> dict:
    soup = soup_of(html)
    main = None
    others = []
    for t in soup.select(".mod-as-list-teaser"):
        if "mod-as-list-teaser--other" in t.get("class", []):
            others.append(t)
        elif main is None:
            main = t
    if main is None:
        raise ValueError("no accreditation block on detail page")
    frame = soup.select_one("#js-as-reader-2 iframe")
    map_url = (frame.get("src") or frame.get("data-src") or "") if frame else ""
    return {
        **parse_teaser(main),
        "scope_de": text_of(soup.select_one("#js-as-reader-de .mod-as-reader__description")),
        "scope_en_machine_translated": text_of(
            soup.select_one("#js-as-reader-en .mod-as-reader__description")),
        "map_url": urljoin(BASE_URL, map_url) if map_url else "",
        "other_accreditations": [{**parse_meta(t), "documents": parse_docs(t)} for t in others],
    }


# ------------------------------------------------------------------ crawling
def search(client: Client, type_code: str, status: str) -> list[dict]:
    url = urljoin(BASE_URL, SEARCH_PATH)
    form = soup_of(client.request("GET", url).text).select_one("#as-search-form")
    if form is None:
        raise RuntimeError("search form #as-search-form not found; the site may have changed")

    # Send what a browser sends: the request token and the enabled fields, plus
    # only the search button. The form also has an as_reset button, and sending
    # that one clears the search and returns the empty form.
    data: list[tuple[str, str]] = []
    for el in form.select("input[name], select[name]"):
        name = el["name"]
        if el.has_attr("disabled") or el.find_parent("fieldset", disabled=True):
            continue
        if el.name == "select":
            opt = el.select_one("option[selected]") or el.select_one("option")
            value = opt.get("value", "") if opt else ""
            if el.has_attr("multiple"):
                continue
        else:
            kind = el.get("type", "text").lower()
            if kind in ("checkbox", "radio") and not el.has_attr("checked"):
                continue
            if kind in ("reset", "button", "image") or (kind == "submit" and name != "as_submit"):
                continue
            value = el.get("value", "")
        data.append((name, value))
    overrides = {"as_search_type": type_code, "as_search_status": status}
    data = [(k, overrides.get(k, v)) for k, v in data]

    r = client.request("POST", url, data=data)
    hits, records = parse_results(r.text)
    if hits is None:
        debug = Path("dakks_debug_search.html").resolve()
        debug.write_text(r.text, encoding="utf-8")
        raise RuntimeError(f"no 'Treffer: N' on the result page (HTTP {r.status_code}, {r.url}). "
                           f"Response saved to {debug}")
    log.info("Search %s/%s: %d hits", type_code, status, hits)

    seen = OrderedDict((rec["accreditation_id"], rec) for rec in records)
    page = 1
    while len(seen) < hits:
        page += 1
        r = client.request("GET", urljoin(BASE_URL, RESULT_PATH), params={"page": page})
        _, records = parse_results(r.text)
        if not records:
            break
        before = len(seen)
        seen.update((rec["accreditation_id"], rec) for rec in records)
        log.info("  page %d: %d/%d", page, len(seen), hits)
        if len(seen) == before:
            break
    if len(seen) != hits:
        log.warning("Site reports %d hits but %d were collected", hits, len(seen))
    return list(seen.values())


def get_detail(client: Client, aid: str, cache_dir: Path, refresh: bool) -> dict:
    path = cache_dir / f"{aid}.html"
    if path.exists() and not refresh:
        return parse_detail(path.read_text(encoding="utf-8"))
    r = client.request("GET", urljoin(BASE_URL, DETAIL_PATH), params={"id": aid})
    detail = parse_detail(r.text)  # parse first so a bad page is never cached
    write_atomic(path, r.text.encode("utf-8"))
    return detail


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def body_id(aid: str) -> str:
    return "-".join(aid.split("-")[:3])


def download_pdf(client: Client, doc: dict, out: Path, refresh: bool) -> None:
    """Fills local_path, size_bytes, sha256 and download_status on doc."""
    name, url = doc["filename"], doc["url"]
    if not PDF_NAME_RE.match(name) or urlsplit(url).netloc != urlsplit(BASE_URL).netloc:
        doc["download_status"] = "skipped: unexpected url"
        log.warning("Skipped unexpected document url: %s", url)
        return
    rel = Path("pdf") / body_id(doc["accreditation_id"]) / name
    path = out / rel
    status = "cached"
    if refresh or not is_pdf(path):
        r = client.request("GET", url)
        if not r.content.startswith(b"%PDF-"):
            doc["download_status"] = "failed: response is not a PDF"
            return
        write_atomic(path, r.content)
        status = "downloaded"
    blob = path.read_bytes()
    doc.update(local_path=rel.as_posix(), size_bytes=len(blob),
               sha256=hashlib.sha256(blob).hexdigest(), download_status=status)


def extract_text(doc: dict, out: Path, refresh: bool) -> None:
    """Writes the PDF text and pulls dates printed on the document."""
    from pypdf import PdfReader
    rel = Path("text") / body_id(doc["accreditation_id"]) / (Path(doc["filename"]).stem + ".txt")
    path = out / rel
    if refresh or not path.exists():
        reader = PdfReader(str(out / doc["local_path"]))
        pages = [(p.extract_text() or "") for p in reader.pages]
        write_atomic(path, "\f".join(pages).encode("utf-8"))
    text = path.read_text(encoding="utf-8")
    doc["text_path"] = rel.as_posix()
    doc["pages"] = text.count("\f") + 1
    for key, pattern in (("valid_from", r"(?:Gültig ab|Valid from)\s*:?\s*(\d{2}\.\d{2}\.\d{4})"),
                         ("issue_date", r"(?:Ausstellungsdatum|Date of issue)\s*:?\s*(\d{2}\.\d{2}\.\d{4})")):
        m = re.search(pattern, text)
        doc[key] = m.group(1) if m else ""


# -------------------------------------------------------------------- output
ACC_COLS = ["accreditation_id", "body_id", "name", "category", "status", "status_since",
            "street", "postcode", "city", "country", "address", "pdf_de_url", "pdf_en_url",
            "scope_de", "scope_en_machine_translated", "other_accreditation_ids",
            "detail_url", "map_url", "error"]
BODY_COLS = ["body_id", "name", "address", "street", "postcode", "city", "country",
             "accreditations_total", "active", "partially_suspended", "fully_suspended",
             "withdrawn", "certificates", "annexes", "latest_status_date", "accreditation_ids",
             "other_accreditation_ids"]
DOC_COLS = ["accreditation_id", "body_id", "name", "document_type", "language", "filename", "url",
            "local_path", "size_bytes", "sha256", "pages", "valid_from", "issue_date",
            "text_path", "download_status"]


def flatten(rec: dict) -> dict:
    docs = rec["documents"]
    pick = lambda lang: next((d["url"] for d in docs if d["language"] == lang), "")
    return {**rec, "body_id": body_id(rec["accreditation_id"]),
            "pdf_de_url": pick("DE"), "pdf_en_url": pick("EN"),
            "other_accreditation_ids": "; ".join(
                o["accreditation_id"] for o in rec.get("other_accreditations", []))}


def to_iso(d: str) -> str:
    return datetime.strptime(d, "%d.%m.%Y").date().isoformat() if d else ""


def build_bodies(records: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for rec in records:
        grouped.setdefault(body_id(rec["accreditation_id"]), []).append(rec)
    bodies = []
    for bid, recs in sorted(grouped.items()):
        first = next((r for r in recs if r["status"] == "Aktiv"), recs[0])
        st = Counter(r["status"] for r in recs)
        docs = [d for r in recs for d in r["documents"]]
        others = sorted({o["accreditation_id"] for r in recs
                         for o in r.get("other_accreditations", [])
                         if not o["accreditation_id"].startswith(bid + "-")})
        bodies.append({
            "body_id": bid, "name": first["name"], "address": first["address"],
            "street": first["street"], "postcode": first["postcode"], "city": first["city"],
            "country": first["country"], "accreditations_total": len(recs),
            "active": st["Aktiv"], "partially_suspended": st["Teilweise ausgesetzt"],
            "fully_suspended": st["Vollständig ausgesetzt"], "withdrawn": st["Zurückgezogen"],
            "certificates": sum(d["document_type"] == "certificate" for d in docs),
            "annexes": sum(d["document_type"] == "annex" for d in docs),
            "latest_status_date": max((to_iso(r["status_since"]) for r in recs), default=""),
            "accreditation_ids": "; ".join(r["accreditation_id"] for r in recs),
            "other_accreditation_ids": "; ".join(others),
        })
    return bodies


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    # utf-8-sig so Excel displays umlauts correctly
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def excel_safe(value):
    """Stays under Excel's cell limit and stops text being read as a formula."""
    if not isinstance(value, str):
        return value
    return ("'" + value if value.startswith("=") else value)[:32000]


def write_xlsx(path: Path, sheets: dict[str, tuple[list[dict], list[str]]]) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        log.warning("openpyxl not installed: skipping the Excel file")
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for title, (rows, cols) in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(cols)
        for row in rows:
            ws.append([excel_safe(row.get(c, "")) for c in cols])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(cols, 1):
            width = max([len(col)] + [len(str(row.get(col, ""))) for row in rows[:200]])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(width + 2, 50)
    wb.save(path)
    return True


# ---------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> int:
    out = Path(args.out or f"dakks_{args.type}")
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.delay)
    failures: list[dict] = []

    records = search(client, args.type, args.status)
    expected = len(records)
    if args.limit:
        records = records[:args.limit]

    do_text = not args.no_text and not args.no_pdfs
    if do_text:
        try:
            import pypdf  # noqa: F401
        except ImportError:
            log.warning("pypdf not installed: skipping PDF text extraction")
            do_text = False

    merged = []
    for i, rec in enumerate(records, 1):
        aid = rec["accreditation_id"]
        log.info("[%d/%d] %s %s", i, len(records), aid, rec["name"][:50])
        try:
            rec = {**rec, **get_detail(client, aid, out / "cache" / "details", args.refresh)}
        except Exception as e:
            # Keep the search-result data: one bad page must not lose the record.
            failures.append({"id": aid, "step": "detail", "error": str(e)})
            rec["error"] = str(e)
        docs = list(rec["documents"])
        if args.related_pdfs:
            for other in rec.get("other_accreditations", []):
                docs += other["documents"]
        if not args.no_pdfs:
            for doc in docs:
                try:
                    download_pdf(client, doc, out, args.refresh)
                except Exception as e:
                    doc["download_status"] = f"failed: {e}"
                    failures.append({"id": doc["filename"], "step": "pdf", "error": str(e)})
                    continue
                if do_text and doc.get("local_path"):
                    try:
                        extract_text(doc, out, args.refresh)
                    except Exception as e:
                        failures.append({"id": doc["filename"], "step": "text", "error": str(e)})
        merged.append(rec)
        if i % 25 == 0:  # checkpoint, so a crash still leaves usable data
            write_atomic(out / "accreditations.json",
                         json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8"))

    docs_rows = []
    for rec in merged:
        all_docs = list(rec["documents"])
        if args.related_pdfs:
            all_docs += [d for o in rec.get("other_accreditations", []) for d in o["documents"]]
        for d in all_docs:
            docs_rows.append({**d, "name": rec["name"], "body_id": body_id(d["accreditation_id"] or rec["accreditation_id"])})
    flat = [flatten(r) for r in merged]
    bodies = build_bodies(merged)

    write_atomic(out / "accreditations.json", json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8"))
    write_atomic(out / "bodies.json", json.dumps(bodies, ensure_ascii=False, indent=2).encode("utf-8"))
    write_csv(out / "accreditations.csv", flat, ACC_COLS)
    write_csv(out / "bodies.csv", bodies, BODY_COLS)
    write_csv(out / "documents.csv", docs_rows, DOC_COLS)
    write_xlsx(out / f"dakks_{args.type}.xlsx", {"Bodies": (bodies, BODY_COLS),
                                                 "Accreditations": (flat, ACC_COLS),
                                                 "Documents": (docs_rows, DOC_COLS)})

    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": args.type, "status_filter": args.status, "hits_on_site": expected,
        "accreditations_saved": len(merged), "bodies": len(bodies),
        "complete": len(merged) == expected and not failures and not args.limit,
        "status_counts": Counter(r["status"] for r in merged),
        "documents": len(docs_rows),
        "documents_on_disk": sum(bool(d.get("local_path")) for d in docs_rows),
        "certificates": sum(d["document_type"] == "certificate" for d in docs_rows),
        "annexes": sum(d["document_type"] == "annex" for d in docs_rows),
        "records_without_pdf": sum(not r["documents"] for r in merged),
        "failures": failures,
    }
    write_atomic(out / "run_report.json", json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    log.info("Done: %d accreditations, %d bodies, %d/%d PDFs, %d failures -> %s",
             len(merged), len(bodies), report["documents_on_disk"], len(docs_rows), len(failures), out)
    return 1 if failures or len(merged) != (args.limit or expected) else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Scrape the DAkkS database of accredited bodies.")
    p.add_argument("--type", default="ZM", choices=TYPES, help="body type (default ZM: management systems)")
    p.add_argument("--status", default="all", choices=STATUSES, help="A, T, R, Z or all (default)")
    p.add_argument("--out", help="output folder (default dakks_<type>)")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    p.add_argument("--limit", type=int, help="only the first N records, for a test run")
    p.add_argument("--no-pdfs", action="store_true", help="metadata only")
    p.add_argument("--no-text", action="store_true", help="no PDF text extraction")
    p.add_argument("--related-pdfs", action="store_true",
                   help="also download PDFs of the body's other accreditations (labs, etc.)")
    p.add_argument("--refresh", action="store_true", help="ignore cached pages and PDFs")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        return run(args)
    except KeyboardInterrupt:
        log.warning("Interrupted. Run the same command again to continue.")
        return 130
    except Exception as e:
        log.error("%s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())