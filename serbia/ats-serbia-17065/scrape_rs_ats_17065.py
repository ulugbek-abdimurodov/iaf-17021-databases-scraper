"""Download the ISO/IEC 17065 product certification bodies from the ATS register (Serbia).

Source: http://www.registar.ats.rs/ (Accreditation Body of Serbia). The search form's
"vrsta_akreditacije" select picks the accreditation type; product certification is
  14 = SRPS EN ISO/IEC 17065:2016, 12 = SRPS ISO/IEC 17065:2013, 6 = SRPS EN 45011 (predecessor)
queried with status=0 (accredited and withdrawn). All results come on one page. Each item has
basic data, status/dates, contact person and a scope PDF (/obim/<hash>, served as 2-04-NNN.pdf).
There is no MS scraper for Serbia (../prepare_certifind.py reads hand-downloaded 2-05 PDFs).

Outputs (default folder ats_17065/):
  bodies.csv           one row per accreditation, all register fields (Cyrillic + Latin name)
  ats_17065_raw.json   one record per accreditation (CertiFind input)
  scope_lines.csv      registration_no,source,row_index,product_text_raw
  scope_documents/     scope PDFs (skipped with --no-files; resumes)
  run_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "http://www.registar.ats.rs/"
TYPES = {"14": "SRPS EN ISO/IEC 17065:2016", "12": "SRPS ISO/IEC 17065:2013", "6": "SRPS EN 45011"}
USER_AGENT = "Mozilla/5.0 (ats-17065-scraper/1.0; accredited body register export)"

CYR = dict(zip("АБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШабвгдђежзијклмнопрстћуфхцчш",
               "ABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠabvgdđežzijklmnoprstćufhcčš"))
CYR.update({"Љ": "Lj", "Њ": "Nj", "Џ": "Dž", "љ": "lj", "њ": "nj", "џ": "dž"})
MONTHS = {m: i for i, m in enumerate(
    "јануар фебруар март април мај јун јул август септембар октобар новембар децембар".split(), 1)}
FIELDS = {  # register label -> output key
    "Број пр.": "file_no", "ПИБ": "pib", "Акр. број": "accreditation_no", "Web": "website",
    "Тел": "phone", "Факс": "fax", "Статус акр.": "status", "Статус суспензије": "suspension",
    "Датум прве акр.": "first_accreditation", "Датум последње акр.": "last_accreditation",
    "Датум истицања/укидања акр.": "expiry_or_withdrawal", "Име и презиме": "contact_name",
    "Функција": "contact_function", "Телефон": "contact_phone", "Е-маил": "email",
}

log = logging.getLogger("ats17065")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def latin(text: str) -> str:
    return "".join(CYR.get(c, c) for c in text)


def iso_date(text: str) -> str:
    """'21. септембар 2027.' -> '2027-09-21' ('' if not a date)."""
    m = re.match(r"(\d{1,2})\.\s*(\S+)\s+(\d{4})", text)
    if not m or m.group(2).lower() not in MONTHS:
        return ""
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def parse_results(html: str, type_id: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "lxml")
    count = None
    head = soup.select_one("#results h3")
    if head and (m := re.search(r"(\d+)", head.get_text())):
        count = int(m.group(1))
    items = []
    for item in soup.select("#s_items div.item"):
        header = item.select_one(".item_header")
        link = header.find("a", href=True)
        h3 = [clean(h.get_text()) for h in header.find_all("h3")]
        rec = {k: "" for k in FIELDS.values()}
        rec.update({
            "type_id": type_id, "type": TYPES[type_id],
            "predmet_id": re.sub(r"\D", "", link["href"]),
            "detail_url": urljoin(BASE, link["href"]),
            "name": re.sub(r"^\d+\.\s*", "", clean(link.get_text())),
            "address": h3[0] if h3 else "",
            "standard_text": h3[1] if len(h3) > 1 else "",
        })
        for tr in item.select(".item_details tr"):
            th, td = tr.find("th"), tr.find("td")
            key = FIELDS.get(clean(th.get_text()).rstrip(":")) if th and td else None
            if key and not rec[key]:
                rec[key] = clean(td.get_text(" "))
        scope = item.select_one(".download_obim a[href]")
        rec["scope_url"] = urljoin(BASE, scope["href"]) if scope else ""
        rec["name_latin"], rec["address_latin"] = latin(rec["name"]), latin(rec["address"])
        rec["status_latin"] = latin(rec["status"])
        for key in ("first_accreditation", "last_accreditation", "expiry_or_withdrawal"):
            rec[key + "_iso"] = iso_date(rec[key])
        items.append(rec)
    return items, count


class Client:
    def __init__(self, delay: float = 0.5, timeout: float = 90):
        self.delay, self.timeout = delay, timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=retry))

    def get(self, url: str, **kwargs) -> requests.Response:
        time.sleep(self.delay)
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response


def pdf_lines(path: Path) -> list[str] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    except Exception as exc:  # noqa: BLE001 - a broken PDF is reported, not fatal
        log.warning("cannot read %s: %s", path.name, exc)
        return []
    return [clean(t) for t in text.splitlines() if clean(t)]


def download_scope(client: Client, rec: dict, folder: Path) -> Path | None:
    name = re.sub(r"[^\w.-]+", "_", rec["file_no"] or rec["predmet_id"]) + ".pdf"
    target = folder / name
    if target.exists() and target.stat().st_size:
        return target
    try:
        data = client.get(rec["scope_url"]).content
    except requests.RequestException as exc:
        log.error("scope download failed %s: %s", rec["scope_url"], exc)
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def run(args: argparse.Namespace) -> int:
    client = Client(args.delay)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    records, counts = [], {}
    for type_id in TYPES:
        html = client.get(BASE, params={"vrsta_akreditacije": type_id, "status": "0"}).text
        items, count = parse_results(html, type_id)
        counts[TYPES[type_id]] = {"site_count": count, "parsed": len(items)}
        if count is not None and count != len(items):
            log.warning("%s: site says %s, parsed %d", TYPES[type_id], count, len(items))
        log.info("%s: %d records", TYPES[type_id], len(items))
        records += items
    if args.limit:
        records = records[: args.limit]

    stats = {"downloaded": 0, "failed": [], "pdf_with_text": 0, "pdf_scanned": [], "no_pypdf": False}
    lines: list[list] = []
    for rec in records:
        reg = rec["accreditation_no"] or rec["file_no"]
        rec["scope_file"] = ""
        if args.no_files or not rec["scope_url"]:
            continue
        path = download_scope(client, rec, out / "scope_documents")
        if not path:
            stats["failed"].append(rec["scope_url"])
            continue
        stats["downloaded"] += 1
        rec["scope_file"] = path.name
        text = pdf_lines(path)
        if text is None:
            stats["no_pypdf"] = True
        elif text:
            stats["pdf_with_text"] += 1
            lines += [[reg, f"annex:{path.name}", i, t] for i, t in enumerate(text)]
        else:
            stats["pdf_scanned"].append(path.name)
        log.info("%s %s (%s)", reg, rec["name_latin"], rec["status_latin"])

    raw = [{
        "registration_no": r["accreditation_no"] or r["file_no"], "id": r["predmet_id"],
        "name": r["name_latin"], "name_cyrillic": r["name"], "address": r["address_latin"],
        "phone": r["phone"], "email": r["email"], "website": r["website"],
        "issued": r["last_accreditation_iso"], "first_accreditation": r["first_accreditation_iso"],
        "expiry": r["expiry_or_withdrawal_iso"], "status": r["status_latin"],
        "suspension": latin(r["suspension"]), "standard": r["type"], "file_no": r["file_no"],
        "pib": r["pib"], "annex_urls": [r["scope_url"]] if r["scope_url"] else [],
    } for r in records]
    (out / "ats_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    columns = list(records[0]) if records else []
    with open(out / "bodies.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(records)
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        writer.writerows(lines)

    statuses: dict = {}
    for r in records:
        statuses[r["status_latin"]] = statuses.get(r["status_latin"], 0) + 1
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": BASE, "filter": {"vrsta_akreditacije": TYPES, "status": "0 (all)"},
              "per_type": counts, "records": len(records),
              "distinct_bodies": len({r["pib"] or r["name"] for r in records}),
              "statuses": statuses, "scope_lines": len(lines), **stats}
    (out / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"accreditations: {len(records)}  bodies: {report['distinct_bodies']}  "
          f"statuses: {statuses}  scope lines: {len(lines)}  PDFs downloaded: "
          f"{stats['downloaded']} failed: {len(stats['failed'])}  with text: "
          f"{stats['pdf_with_text']} scanned: {len(stats['pdf_scanned'])}"
          + ("  (pypdf missing)" if stats["no_pypdf"] else ""))
    return 1 if stats["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default=str(Path(__file__).parent / "ats_17065"))
    parser.add_argument("--no-files", action="store_true", help="skip scope PDF downloads")
    parser.add_argument("--limit", type=int, default=0, help="only the first N records")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
