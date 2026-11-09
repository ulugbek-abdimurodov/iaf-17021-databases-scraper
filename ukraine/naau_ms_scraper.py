#!/usr/bin/env python3
"""
NAAU scraper: management system certification bodies (DSTU EN ISO/IEC 17021-1).

Sources, all linked from the NAAU register page:
  * Ukrainian XLSX: phones, validity history, scope summary, and the Google Drive
    links to each body's scope annex (the English DOC has none of these links).
  * English DOC: English names, validity history and scope summary.
  * Google Drive files: "Посилання на сферу" (annex) and "Скан-копія сфери" (scan).

Setup:  pip install requests beautifulsoup4 openpyxl pdfplumber
Run:    python naau_ms_scraper.py
        python naau_ms_scraper.py --out naau_data --status active --limit 5

Re-running is safe: files already downloaded are skipped, failures are retried.

Output:
  bodies.xlsx / bodies.csv / bodies.json   one record per body
  downloads.csv                            every file link and its result
  annexes/<certificate>/                   the PDFs, plus .txt where text exists
  register_raw/                            the source XLSX and DOC, unmodified
  run_report.txt                           counts and anything needing attention
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import struct
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import openpyxl
import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber  # optional, only used to extract annex text
except ImportError:
    pdfplumber = None

BASE_URL = "https://naau.org.ua"
DRIVE_URL = "https://drive.google.com/uc"
PAGE_UK = "/3-reiestr-akreditovanikh-oov"
PAGE_EN = "/en/3-reiestr-akreditovanikh-oov"
USER_AGENT = "Mozilla/5.0 (compatible; naau-register-scraper/1.0)"
DATE_RANGE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*[-–—]\s*(\d{2}\.\d{2}\.\d{4})")
EVENT = re.compile(
    DATE_RANGE.pattern + r"|(призупинена|поновлена|скасована)(?:\s+з)?\s*(\d{2}\.\d{2}\.\d{4})?",
    re.I,
)


def clean(value) -> str:
    """Collapse whitespace and drop Word control characters."""
    if value is None:
        return ""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(value).replace("\r", "\n"))
    return re.sub(r"\s+", " ", text).strip()


def cert_key(raw: str) -> str:
    """The register mixes Latin O, Cyrillic О and zero: 8O001, 8О001, 80143."""
    text = re.sub(r"\s", "", raw or "")
    return re.sub(r"^8[OОoо0]", "8O", text)[:5]


# ---------------------------------------------------------------- network

class Http:
    def __init__(self, delay: float):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay

    def get(self, url: str, **kwargs) -> requests.Response:
        last_error = None
        for attempt in range(4):
            if attempt:
                time.sleep(5 * 2 ** (attempt - 1))
            try:
                time.sleep(self.delay)
                response = self.session.get(url, timeout=120, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {response.status_code}"
                    continue
                return response
            except requests.RequestException as exc:
                last_error = str(exc)
        raise RuntimeError(f"{url}: {last_error}")


def find_register_links(http: Http) -> dict:
    """Read the current file links and published counts from the register pages."""
    found = {}
    for key, path, ext in (("xlsx", PAGE_UK, ".xlsx"), ("doc", PAGE_EN, ".doc")):
        response = http.get(BASE_URL + path)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            if link and "17021" in row.get_text() and unquote(link["href"]).lower().endswith(ext):
                found[key] = urljoin(BASE_URL + "/", link["href"])
                numbers = [clean(c.get_text()) for c in row.find_all("td")][-3:]
                if all(n.isdigit() for n in numbers):
                    found["published"] = dict(zip(("valid", "invalid", "total"), map(int, numbers)))
                break
        if key not in found:
            raise RuntimeError(f"No 17021-1 {ext} link found on {path}; the page layout may have changed")
    return found


# ---------------------------------------------------------------- parsing

def parse_xlsx(data: bytes) -> list[dict]:
    sheet = openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]
    header_row = next(
        (r for r in range(1, 11) if "Назва" in clean(sheet.cell(r, 2).value)), None
    )
    if header_row is None:
        raise RuntimeError("Header row not found in the XLSX; the layout may have changed")
    records = []
    for row in range(header_row + 1, sheet.max_row + 1):
        cells = [sheet.cell(row, col) for col in range(1, 9)]
        if not clean(cells[3].value):
            continue
        records.append({
            "cab_no": clean(cells[0].value),
            "certificate_no": cert_key(clean(cells[3].value)),
            "certificate_no_raw": clean(cells[3].value),
            "name_uk": clean(cells[1].value),
            "phones": clean(cells[2].value),
            "validity_uk": clean(cells[4].value),
            "scope_summary_uk": clean(cells[5].value),
            "scope_url": cells[6].hyperlink.target if cells[6].hyperlink else "",
            "scan_url": cells[7].hyperlink.target if cells[7].hyperlink else "",
        })
    return records


def read_ole_streams(data: bytes) -> dict:
    """Minimal reader for the OLE container of a .doc file."""
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise RuntimeError("The register DOC is not a Word 97-2003 file")
    sector = 1 << struct.unpack_from("<H", data, 30)[0]
    offset = lambda s: (s + 1) * sector
    fat_sectors = [v for v in struct.unpack_from("<109i", data, 76) if v >= 0]
    next_difat = struct.unpack_from("<i", data, 68)[0]
    while next_difat >= 0:
        entries = struct.unpack_from(f"<{sector // 4}i", data, offset(next_difat))
        fat_sectors += [v for v in entries[:-1] if v >= 0]
        next_difat = entries[-1]
    fat = []
    for s in fat_sectors:
        fat += struct.unpack_from(f"<{sector // 4}i", data, offset(s))

    def read_chain(start: int, size: int | None = None) -> bytes:
        parts, seen = [], set()
        while start >= 0 and start not in seen:
            seen.add(start)
            parts.append(data[offset(start): offset(start) + sector])
            start = fat[start]
        joined = b"".join(parts)
        return joined if size is None else joined[:size]

    directory = read_chain(struct.unpack_from("<i", data, 48)[0])
    mini_fat_raw = read_chain(struct.unpack_from("<i", data, 60)[0])
    mini_fat = struct.unpack(f"<{len(mini_fat_raw) // 4}i", mini_fat_raw[: len(mini_fat_raw) // 4 * 4])
    mini_size = 1 << struct.unpack_from("<H", data, 32)[0]
    cutoff = struct.unpack_from("<I", data, 56)[0]
    mini_stream = read_chain(struct.unpack_from("<i", directory, 116)[0])

    def read_mini(start: int, size: int) -> bytes:
        parts, seen = [], set()
        while start >= 0 and start not in seen:
            seen.add(start)
            parts.append(mini_stream[start * mini_size: (start + 1) * mini_size])
            start = mini_fat[start]
        return b"".join(parts)[:size]

    streams = {}
    for pos in range(0, len(directory) - 127, 128):
        name_len = struct.unpack_from("<H", directory, pos + 64)[0]
        if name_len < 2 or directory[pos + 66] != 2:
            continue
        name = directory[pos: pos + name_len - 2].decode("utf-16-le")
        start, size = struct.unpack_from("<iI", directory, pos + 116)
        if name in ("WordDocument", "0Table", "1Table"):
            streams[name] = read_chain(start, size) if size >= cutoff else read_mini(start, size)
    return streams


def doc_text(data: bytes) -> str:
    """Read Word 97-2003 text through its piece table.

    Text in a .doc is stored out of order, so scanning the raw bytes loses rows.
    """
    streams = read_ole_streams(data)
    word = streams["WordDocument"]
    table_name = "1Table" if struct.unpack_from("<H", word, 0x0A)[0] & 0x0200 else "0Table"
    table = streams[table_name]
    char_count = struct.unpack_from("<I", word, 0x4C)[0]
    pos = struct.unpack_from("<I", word, 0x1A2)[0]
    while table[pos] == 1:
        pos += 3 + struct.unpack_from("<H", table, pos + 1)[0]
    if table[pos] != 2:
        raise RuntimeError("Unexpected piece table in the DOC")
    size = struct.unpack_from("<I", table, pos + 1)[0]
    start = pos + 5
    count = (size - 4) // 12
    parts = []
    for i in range(count):
        cp_a, cp_b = struct.unpack_from("<II", table, start + i * 4)
        raw_fc = struct.unpack_from("<I", table, start + (count + 1) * 4 + i * 8 + 2)[0]
        fc = raw_fc & 0x3FFFFFFF
        length = cp_b - cp_a
        if raw_fc & 0x40000000:
            parts.append(word[fc // 2: fc // 2 + length].decode("cp1252", "replace"))
        else:
            parts.append(word[fc: fc + length * 2].decode("utf-16-le", "replace"))
    text = "".join(parts)[:char_count]
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)  # field instructions
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)
    return text.replace("\x15", "")


def parse_doc(data: bytes) -> dict:
    """Table rows look like: number, name, certificate, validity, scope."""
    cells = [clean(c) for c in doc_text(data).split("\x07")]
    english = {}
    for i, cell in enumerate(cells):
        if i and re.match(r"^8\s*[OОoо0]\s*\d{3}\b", cell) and i + 2 < len(cells):
            english[cert_key(cell)] = {
                "name_en": cells[i - 1],
                "validity_en": cells[i + 1],
                "scope_summary_en": cells[i + 2],
            }
    return english


def to_date(text: str):
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return None


def iso(day) -> str:
    return day.isoformat() if day else ""


def analyse_validity(text: str, today: date) -> dict:
    """Derive status from the history text; the order of events matters."""
    periods, last_event, suspended, restored, cancelled = [], "", "", "", ""
    for match in EVENT.finditer(text):
        if match.group(1):
            periods.append((match.group(1), match.group(2)))
            last_event = "period"
        else:
            last_event = match.group(3).lower()
            when = iso(to_date(match.group(4) or ""))
            if last_event == "призупинена":
                suspended = when
            elif last_event == "поновлена":
                restored = when
            else:
                cancelled = when
    start = to_date(periods[-1][0]) if periods else None
    end = to_date(periods[-1][1]) if periods else None
    if "скасована" in text.lower():
        status = "cancelled"
    elif last_event == "призупинена":
        status = "suspended"
    elif end and end >= today:
        status = "active"
    else:
        status = "expired"
    return {
        "status": status,
        "first_accredited": iso(to_date(periods[0][0])) if periods else "",
        "current_valid_from": iso(start),
        "current_valid_to": iso(end),
        "last_suspended": suspended,
        "last_restored": restored,
        "cancelled_on": cancelled,
    }


def list_standards(text: str) -> str:
    found = re.findall(r"ISO(?:/IEC)?\s*\d{4,6}(?:-\d+)?(?::\d{4})?", text)
    return "; ".join(sorted({re.sub(r"\s+", " ", s) for s in found}))


# ---------------------------------------------------------------- downloads

def drive_id(url: str) -> str:
    parsed = urlparse(url)
    if "google.com" not in parsed.netloc:
        return ""
    match = re.search(r"/d/([\w-]{10,})", parsed.path)
    if match:
        return match.group(1)
    return parse_qs(parsed.query).get("id", [""])[0]


def response_filename(response: requests.Response) -> str:
    header = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", header, re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)', header, re.I)
    if match:
        return match.group(1).strip()
    return Path(unquote(urlparse(response.url).path)).name


def fetch_file(http: Http, url: str) -> requests.Response:
    """Fetch a direct or Drive link, passing Drive's large-file confirmation page."""
    file_id = drive_id(url)
    if not file_id:
        return http.get(url.replace("http://", "https://", 1), stream=True)
    if "/folders/" in url:
        raise RuntimeError("Link is a Drive folder, not a file")
    response = http.get(DRIVE_URL, params={"export": "download", "id": file_id}, stream=True)
    if "text/html" not in response.headers.get("Content-Type", ""):
        return response
    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.find("form", id="download-form") or soup.find("form", action=re.compile("download"))
    if not form:
        title = clean(soup.title.get_text()) if soup.title else "unknown page"
        raise RuntimeError(f"Drive returned a page instead of the file: {title}")
    params = {i["name"]: i.get("value", "") for i in form.find_all("input", attrs={"name": True})}
    return http.get(urljoin(response.url, form["action"]), params=params, stream=True)


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[-150:] or "file"


def extract_text(path: Path) -> dict:
    info = {"pages": "", "annex_issue": "", "has_text": "", "contains_certificate_page": ""}
    if path.suffix.lower() != ".pdf" or pdfplumber is None:
        return info
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        return info
    text = "\n".join(pages)
    info["pages"] = len(pages)
    info["has_text"] = "yes" if len(text.strip()) > 50 else "no (scan)"
    if info["has_text"] == "yes":
        path.with_suffix(".txt").write_text(text, encoding="utf-8")
        match = re.search(r"Додаток\s+від[^\n]*", text)
        info["annex_issue"] = clean(match.group(0)) if match else ""
        info["contains_certificate_page"] = (
            "yes" if re.search(r"АТЕСТАТ\s+ПРО\s+АКРЕДИТАЦІЮ", text) else "no"
        )
    return info


def download(http: Http, url: str, cert: str, kind: str, root: Path, previous: dict) -> dict:
    result = {"certificate_no": cert, "kind": kind, "url": url, "result": "", "file": "",
              "bytes": "", "sha256": "", "pages": "", "annex_issue": "", "has_text": "",
              "contains_certificate_page": "", "error": ""}
    earlier = previous.get((cert, kind, url))
    if earlier and earlier.get("file") and (root / earlier["file"]).exists():
        result.update(earlier)
        result["result"] = "already downloaded"
        return result
    try:
        response = fetch_file(http, url)
        response.raise_for_status()
        folder = root / "annexes" / cert
        folder.mkdir(parents=True, exist_ok=True)
        original = safe_name(response_filename(response))
        target = folder / f"{cert}_{kind}_{original}"
        partial = target.with_name(target.name + ".part")
        digest, size, head = hashlib.sha256(), 0, b""
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(65536):
                if not head:
                    head = chunk[:8]
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if target.suffix.lower() == ".pdf" and not head.startswith(b"%PDF"):
            partial.unlink()
            raise RuntimeError("Response was not a PDF")
        partial.replace(target)
        result.update(result="downloaded", file=target.relative_to(root).as_posix(),
                      bytes=size, sha256=digest.hexdigest(), **extract_text(target))
    except Exception as exc:
        result.update(result="failed", error=str(exc)[:300])
    return result


# ---------------------------------------------------------------- output

COLUMNS = [
    "cab_no", "certificate_no", "certificate_no_raw", "status", "name_uk", "name_en", "phones",
    "first_accredited", "current_valid_from", "current_valid_to", "last_suspended",
    "last_restored", "cancelled_on", "standards_iso", "scope_summary_uk", "scope_summary_en",
    "validity_uk", "validity_en", "scope_url", "scan_url", "scope_file", "scan_file",
    "annex_issue", "annex_pages", "contains_certificate_page",
]
DOWNLOAD_COLUMNS = [
    "certificate_no", "kind", "url", "result", "file", "bytes", "sha256", "pages",
    "annex_issue", "has_text", "contains_certificate_page", "error",
]


def write_table(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_workbook(path: Path, rows: list[dict], downloads: list[dict]) -> None:
    book = openpyxl.Workbook()
    sheets = [(book.active, "Bodies", COLUMNS, rows),
              (book.create_sheet(), "Downloads", DOWNLOAD_COLUMNS, downloads)]
    for sheet, title, columns, data in sheets:
        sheet.title = title
        sheet.append(columns)
        for row in data:
            # Keep text from being read as a formula when opened in Excel.
            sheet.append([("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v
                          for v in (row.get(c, "") for c in columns)])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = openpyxl.styles.Font(bold=True)
    book.save(path)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", default="naau_ms_certification_bodies", help="output folder")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--status", choices=["all", "active", "suspended", "expired", "cancelled"],
                        default="all", help="only download files for bodies with this status")
    parser.add_argument("--limit", type=int, default=0, help="only download files for N bodies (test run)")
    parser.add_argument("--no-files", action="store_true", help="collect the data only")
    args = parser.parse_args()

    root = Path(args.out)
    (root / "register_raw").mkdir(parents=True, exist_ok=True)
    http = Http(args.delay)

    print("Reading the register pages...")
    links = find_register_links(http)
    raw = {}
    for key in ("xlsx", "doc"):
        response = http.get(links[key])
        response.raise_for_status()
        raw[key] = response.content
        (root / "register_raw" / safe_name(unquote(links[key].rsplit("/", 1)[-1]))).write_bytes(raw[key])

    records = parse_xlsx(raw["xlsx"])
    english = parse_doc(raw["doc"])
    today = date.today()
    for record in records:
        record.update(english.get(record["certificate_no"], {}))
        record.update(analyse_validity(record["validity_uk"], today))
        record["standards_iso"] = list_standards(record["scope_summary_uk"])
    print(f"Register: {len(records)} bodies, {len(english)} English entries")

    manifest_path = root / "downloads.json"
    previous = {}
    if manifest_path.exists():
        for item in json.loads(manifest_path.read_text(encoding="utf-8")):
            if item.get("file"):
                previous[(item["certificate_no"], item["kind"], item["url"])] = item

    downloads = []
    selected = [r for r in records if args.status == "all" or r["status"] == args.status]
    if args.limit:
        selected = selected[: args.limit]
    if not args.no_files:
        jobs = [(r, kind, r[f"{kind}_url"]) for r in selected for kind in ("scope", "scan")
                if r[f"{kind}_url"]]
        for number, (record, kind, url) in enumerate(jobs, 1):
            item = download(http, url, record["certificate_no"], kind, root, previous)
            downloads.append(item)
            print(f"[{number}/{len(jobs)}] {record['certificate_no']} {kind}: "
                  f"{item['result']} {item['error']}".rstrip())
            manifest_path.write_text(json.dumps(downloads, ensure_ascii=False, indent=1), encoding="utf-8")

    by_job = {(d["certificate_no"], d["kind"]): d for d in downloads}
    for record in records:
        scope = by_job.get((record["certificate_no"], "scope"), {})
        scan = by_job.get((record["certificate_no"], "scan"), {})
        record["scope_file"] = scope.get("file", "")
        record["scan_file"] = scan.get("file", "")
        record["annex_issue"] = scope.get("annex_issue", "")
        record["annex_pages"] = scope.get("pages", "")
        record["contains_certificate_page"] = scope.get("contains_certificate_page", "")

    write_table(root / "bodies.csv", COLUMNS, records)
    write_table(root / "downloads.csv", DOWNLOAD_COLUMNS, downloads)
    write_workbook(root / "bodies.xlsx", records, downloads)
    (root / "bodies.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    failed = [d for d in downloads if d["result"] == "failed"]
    no_link = [r["certificate_no"] for r in records if not r["scope_url"] and not r["scan_url"]]
    no_english = [r["certificate_no"] for r in records if not r.get("name_en")]
    published = links.get("published", {})
    lines = [
        f"Run date: {today}",
        f"Register XLSX: {links['xlsx']}",
        f"Register DOC:  {links['doc']}",
        f"Bodies: {len(records)}  {counts}",
        f"NAAU page counts: {published}",
    ]
    if published and (published["total"] != len(records) or published["valid"] != counts.get("active", 0)):
        lines.append("CHECK: counts differ from the NAAU page. The page and files can be dated differently.")
    lines += [
        f"Links attempted: {len(downloads)}, failed: {len(failed)}",
        f"Bodies with no file link in the register ({len(no_link)}): {', '.join(no_link)}",
        f"Bodies with no English entry ({len(no_english)}): {', '.join(no_english)}",
    ]
    if pdfplumber is None:
        lines.append("pdfplumber is not installed: PDF text, page counts and annex dates were skipped.")
    lines += [f"FAILED {d['certificate_no']} {d['kind']} {d['url']}: {d['error']}" for d in failed]
    report = "\n".join(lines)
    (root / "run_report.txt").write_text(report + "\n", encoding="utf-8")
    print("\n" + report + f"\n\nSaved to: {root.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
