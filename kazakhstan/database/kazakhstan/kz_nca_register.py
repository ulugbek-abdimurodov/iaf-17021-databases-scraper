"""NCA Kazakhstan register of accredited bodies (the "Реестр субъектов аккредитации" linked from www.nca.kz).

  POST http://77.245.104.163/index.php?do=web_search   fldPage=N (0-based, 30 rows/page), fldActivityType[]=<id>
  GET  http://77.245.104.163/index.php?do=web_search&file=<file_id>     scope annex (.doc / .docx / .pdf)

Activity ids: 1 = product/process/service certification (ОПС П / ОПС ПиУ, ISO/IEC 17065),
7 = management system certification (ОПС СМ, ISO/IEC 17021-1), 8 persons, 12 inspection, 14 Halal, ...
The register lists current (valid) accreditations only.

techreg.kezekte.kz/ru/acc/subjects (used before Nov 2026) now shows an archive of mostly inactive records,
without detail pages or files, so it is no longer used.
"""
import re
import shutil
import subprocess
import time
import zipfile
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "http://77.245.104.163/index.php?do=web_search"
ACT_PRODUCT, ACT_MS = "1", "7"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (registry-scraper)"
LAT = str.maketrans("КОАЕВСМНРТХ", "KOAEBCMHPTX")  # the register mixes Cyrillic look-alikes into numbers


def req(method, url, **kw):
    for attempt in range(4):
        try:
            r = S.request(method, url, timeout=180, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def _cell_lines(td):
    return [ln.strip() for ln in td.get_text("\n").split("\n") if ln.strip()]


def parse_row(tds, region):
    name_l, cert_l, addr_l = _cell_lines(tds[1]), _cell_lines(tds[2]), _cell_lines(tds[3])
    dates = [x for x in cert_l if re.fullmatch(r"\d\d\.\d\d\.\d{4}", x)]
    cert_raw = " ".join(x for x in cert_l if x not in dates)
    m = re.search(r"[KК][ZЗ]\.\s*\S+", cert_raw)
    cert = m.group(0).translate(LAT).replace(" ", "") if m else cert_raw
    addr = " ".join(addr_l)
    end = dates[1] if len(dates) > 1 else ""
    try:
        d, mth, y = map(int, end.split("."))
        status = "Active" if date(y, mth, d) >= date.today() else "Expired"
    except ValueError:
        status = "Unknown"
    files = [{"id": re.search(r"file=(\d+)", a["href"]).group(1), "name": a.get_text(" ", strip=True)}
             for a in tds[4].find_all("a", href=re.compile(r"file=\d+"))]
    return {
        "row_no": tds[0].get_text(strip=True), "region": region,
        "name": " ".join(name_l), "registration_no": cert, "registration_raw": cert_raw,
        "branch_of": cert_raw.split("/")[0].strip() if "/" in cert_raw else "",
        "issued": dates[0] if dates else "", "expiry": end, "status": status,
        "address_block": addr,
        "phone": "; ".join(re.findall(r"(?:тел[^:]*:|факс[^:]*:)\s*([^a-zA-Z@]+?)(?=\s+[\w.-]+@|$|\s+www)", addr)),
        "email": "; ".join(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]*\w", addr)),
        "website": "; ".join(re.findall(r"(?:https?://|www\.)[^\s,;]+", addr)),
        "files": files,
    }


def fetch_list(activity: str) -> list[dict]:
    out, seen, page, total = [], set(), 0, None
    while True:
        r = req("POST", BASE, data={"fldPage": page, "fldActivityType[]": activity})
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        if page == 0:
            m = re.search(r"Всего найдено субъектов:\s*(\d+)", r.text)
            total = int(m.group(1)) if m else None
        new, region = 0, ""
        for tr in soup.find_all("tr"):
            if tr.find("tr"):
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) == 1 and tds[0].get_text(strip=True) and not tds[0].find("table"):
                region = tds[0].get_text(" ", strip=True)  # region header row
                continue
            if len(tds) < 5 or not tds[0].get_text(strip=True).isdigit():
                continue
            rec = parse_row(tds, region)
            if rec["row_no"] in seen:
                continue
            seen.add(rec["row_no"])
            out.append(rec)
            new += 1
        if not new or (total and len(out) >= total):
            break
        page += 1
    return out


def file_url(fid: str) -> str:
    return f"{BASE}&file={fid}"


def download(fid: str, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower() or ".bin"
    p = dest_dir / f"{fid}{ext}"
    if p.exists() and p.stat().st_size:
        return p
    p.write_bytes(req("GET", file_url(fid)).content)
    return p


WORD_PS = r"""
$w = New-Object -ComObject Word.Application
$w.Visible = $false; $w.DisplayAlerts = 0
Get-ChildItem -LiteralPath '__DIR__' -Recurse -File | Where-Object { $_.Extension -in '.doc', '.docx', '.rtf' } |
  ForEach-Object {
    $htm = [IO.Path]::ChangeExtension($_.FullName, '.htm')
    if (-not (Test-Path -LiteralPath $htm)) {
      try { $d = $w.Documents.Open($_.FullName, $false, $true); $d.WebOptions.Encoding = 65001; $d.SaveAs2($htm, 10, $false, '', $false, '', $false, $false, $false, $false, $false, 65001); $d.Close($false) }
      catch { Write-Output ("failed " + $_.FullName) }
    }
  }
$w.Quit()
"""


def convert_with_word(folder: Path) -> bool:
    """Save every .doc/.docx under folder as filtered UTF-8 .htm next to it (Microsoft Word via COM), so table
    rows survive. Many NCA .doc annexes are too large for antiword ("Big Block Depot is damaged")."""
    if not shutil.which("powershell"):
        return False
    ps = WORD_PS.replace("__DIR__", str(folder.resolve()))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip()[-2000:])
    return r.returncode == 0


def _clean(ln: str) -> str:
    ln = ln.replace("\t", " | ").replace("\x07", " | ")
    return re.sub(r"\s+", " ", ln).strip(" |")


def html_lines(html: str) -> list[str]:
    """One line per table row (cells joined with ' | '), one per paragraph outside tables."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for el in soup.find_all(["tr", "p", "h1", "h2", "h3", "li"]):
        if el.name != "tr" and el.find_parent("tr"):
            continue
        if el.name == "tr":
            if el.find("tr"):
                continue
            ln = " | ".join(re.sub(r"\s+", " ", td.get_text(" ")).strip() for td in el.find_all(["td", "th"]))
        else:
            ln = el.get_text(" ")
        ln = _clean(ln)
        if ln:
            out.append(ln)
    return out


def text_lines(p: Path) -> list[str]:
    """Text lines of a scope annex: the Word-made .htm beside a .doc/.docx when present (one line per table row),
    else .docx via its XML, .doc via antiword, .pdf via pypdf. Empty list when there is no text layer/tool."""
    try:
        htm = p.with_suffix(".htm")
        if p.suffix.lower() in (".doc", ".docx", ".rtf") and htm.exists():
            b = htm.read_bytes()
            m = re.search(rb"charset=([\w-]+)", b[:3000])
            return html_lines(b.decode(m.group(1).decode() if m else "utf-8", "ignore"))
        else:
            head = p.read_bytes()[:8]
            if head.startswith(b"%PDF"):
                from pypdf import PdfReader
                t = "\n".join(pg.extract_text() or "" for pg in PdfReader(p).pages)
            elif head.startswith(b"PK"):
                with zipfile.ZipFile(p) as z:
                    xml = z.read("word/document.xml").decode("utf-8", "ignore")
                xml = re.sub(r"</w:tc>", "\t", xml)
                xml = re.sub(r"</w:p>|</w:tr>", "\n", xml)
                t = re.sub(r"<[^>]+>", "", xml)
            elif head.startswith(b"\xd0\xcf\x11\xe0") and shutil.which("antiword"):
                t = subprocess.run(["antiword", "-m", "UTF-8.txt", "-w", "0", str(p)], capture_output=True, timeout=120).stdout.decode(
                    "utf-8", "ignore")
            else:
                return []
    except Exception:
        return []
    return [c for c in (_clean(ln) for ln in re.split(r"[\r\n]+", t)) if c]
