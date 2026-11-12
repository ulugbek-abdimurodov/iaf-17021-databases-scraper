#!/usr/bin/env python3
"""
KAB (Korea Accreditation Board) Management-System Certification Body scraper.

Collects the public KAB management-system CAB directory, each CAB profile,
scheme/accreditation details, source HTML, and linked public documents.
It deliberately distinguishes KAB accreditation records from certificates
issued by a CAB to its clients.

Usage:
  python kab_ms_scraper.py
  python kab_ms_scraper.py --browser
  python kab_ms_scraper.py --limit 5 --delay 1.5

Install:
  pip install -r requirements-kab.txt
  # For --browser:
  playwright install chromium

The site may change its HTML or access controls. The scraper logs unresolved
records and never silently treats a failed page as an empty result.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import mimetypes
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://www.kab.or.kr"
ENG = "https://eng.kab.or.kr"
LIST_URL = f"{BASE}/kor/kcn/kcn/list.do?menuNo=400010&pSiteId=kor&schParent=1"
DETAIL_URL = f"{ENG}/eng/kcn/kcn/view.do"
OUT = Path("kab_ms_data")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SCHEME_CODES = [
    "QMS", "EMS", "TL", "OHSMS", "FSMS", "ISMS", "GMS", "EnMS",
    "FSSC", "RTSMS", "BCMS", "FMS", "ABMS", "AQMS", "EOMS",
    "MDQMS", "CMS", "PIMS", "NQMS", "AIMS", "SDGMS",
]
LOG = logging.getLogger("kab_scraper")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def safe_name(s: str, fallback: str = "unnamed") -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s or "").strip(" ._")
    return (s[:120] or fallback)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    retry = Retry(
        total=5, connect=5, read=5, backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


@dataclass
class Body:
    source_id: str
    name_local: str = ""
    name_english: str = ""
    acronym: str = ""
    detail_url: str = ""
    source_list_url: str = ""
    directory_scheme_flags: str = ""
    phone: str = ""
    fax: str = ""
    website: str = ""
    head_office: str = ""
    general_information: str = ""
    detail_text: str = ""
    scraped_at: str = ""


@dataclass
class Accreditation:
    source_id: str
    body_name: str
    scheme_name: str = ""
    accreditation_number: str = ""
    accreditation_date: str = ""
    scheme_category: str = ""
    accredited_scope: str = ""
    status: str = ""
    source_detail_url: str = ""
    source_text: str = ""


@dataclass
class Document:
    source_id: str
    body_name: str
    document_type: str
    title: str
    source_url: str
    local_path: str = ""
    mime_type: str = ""
    file_size: int = 0
    sha256: str = ""
    downloaded_at: str = ""
    source_detail_url: str = ""
    download_status: str = "pending"
    error: str = ""


class KabScraper:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session = make_session()
        self.bodies: list[dict[str, Any]] = []
        self.accreditations: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.seen_doc_urls: set[str] = set()
        self.browser = None
        self.playwright = None
        for folder in ("raw/list", "raw/details", "documents", "parsed"):
            (OUT / folder).mkdir(parents=True, exist_ok=True)

    def request_html(self, url: str) -> tuple[str, str]:
        r = self.session.get(url, timeout=45)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        return r.text, r.url

    def browser_html(self, url: str) -> tuple[str, str]:
        if self.browser is None:
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
            self.page = self.browser.new_page(locale="ko-KR")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(1200)
        # Let common asynchronous table requests finish.
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        return self.page.content(), self.page.url

    def get_html(self, url: str) -> tuple[str, str]:
        if self.args.browser:
            return self.browser_html(url)
        html, final_url = self.request_html(url)
        # The static HTML path is preferred; browser mode is explicitly available
        # for deployments where the directory is rendered client-side.
        return html, final_url

    def save_raw(self, folder: str, key: str, html: str) -> str:
        p = OUT / "raw" / folder / f"{safe_name(key)}.html"
        p.write_text(html, encoding="utf-8")
        return str(p)

    @staticmethod
    def detail_id(href: str) -> str | None:
        q = parse_qs(urlparse(href).query)
        vals = q.get("orgIdx") or q.get("orgidx") or []
        return vals[0] if vals else None

    def build_detail_url(self, org_id: str) -> str:
        return DETAIL_URL + "?" + urlencode({"menuNo": "500044", "orgIdx": org_id})

    def extract_body_rows(self, html: str, page_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        found: dict[str, dict[str, Any]] = {}
        # Every profile link contains orgIdx. Use its closest row to retain
        # the scheme matrix from the directory.
        for a in soup.select('a[href*="view.do"][href*="orgIdx"], a[href*="orgIdx"]'):
            href = urljoin(page_url, a.get("href", ""))
            org_id = self.detail_id(href)
            if not org_id:
                continue
            tr = a.find_parent("tr")
            row_text = clean(tr.get_text(" ", strip=True)) if tr else clean(a.parent.get_text(" ", strip=True))
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])] if tr else []
            name_local = ""
            name_english = ""
            acronym = ""
            if len(cells) > 1:
                name_cell = cells[1]
                # Directory cell typically contains Korean/local name and English
                # name/acronym on separate lines.
                bits = [clean(x) for x in (tr.find_all(["th", "td"])[1].stripped_strings)]
                if bits:
                    name_local = bits[0]
                if len(bits) > 1:
                    name_english = " ".join(bits[1:])
                m = re.search(r"\[([A-Za-z0-9&._-]+)\]\s*$", name_cell)
                if m:
                    acronym = m.group(1)
            if not name_local:
                name_local = clean(a.get_text(" ", strip=True)) or row_text
            flags = []
            for code in SCHEME_CODES:
                # Preserve visible scheme flags; blank means no flag was shown.
                if code.lower() in row_text.lower():
                    flags.append(code)
            found[org_id] = {
                "source_id": org_id, "name_local": name_local,
                "name_english": name_english, "acronym": acronym,
                "detail_url": self.build_detail_url(org_id),
                "source_list_url": page_url,
                "directory_scheme_flags": ";".join(flags),
                "directory_row_text": row_text,
            }
        return list(found.values())

    def discover_directory(self) -> list[dict[str, Any]]:
        # KAB list.do is the official Management System (MS) CAB register.
        # Search-engine-indexed pages indicate server-rendered results; also
        # discover any pagination URLs exposed in the live HTML.
        queue = [LIST_URL]
        visited: set[str] = set()
        bodies: dict[str, dict[str, Any]] = {}
        page_count = 0
        while queue and page_count < self.args.max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            page_count += 1
            try:
                html, final_url = self.get_html(url)
                self.save_raw("list", f"page_{page_count}", html)
                rows = self.extract_body_rows(html, final_url)
                for row in rows:
                    bodies[row["source_id"]] = row
                LOG.info("Directory page %s: %s profiles (unique total %s)",
                         page_count, len(rows), len(bodies))
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.select('a[href*="list.do"]'):
                    nxt = urljoin(final_url, a.get("href", ""))
                    if "menuNo=400010" in nxt and nxt not in visited and nxt not in queue:
                        queue.append(nxt)
                # Egov pagination commonly uses javascript:fn_egov_link_page(n).
                for a in soup.select("a[onclick], a[href]"):
                    js = a.get("onclick", "") + " " + a.get("href", "")
                    m = re.search(r"fn_egov_link_page\s*\(\s*['\"]?(\d+)", js)
                    if m:
                        q = parse_qs(urlparse(LIST_URL).query)
                        q["pageIndex"] = [m.group(1)]
                        next_url = LIST_URL.split("?")[0] + "?" + urlencode({k: v[0] for k, v in q.items()})
                        if next_url not in visited and next_url not in queue:
                            queue.append(next_url)
            except Exception as e:
                self.failures.append({"stage": "directory", "url": url, "error": repr(e), "at": now_iso()})
                LOG.exception("Directory page failed: %s", url)
            time.sleep(self.args.delay)

        # Some KAB releases use a different pagination parameter. If the
        # rendered page reports more than one page, probe pageIndex sequentially.
        if not bodies and not self.args.browser:
            LOG.warning("No profile links found in static HTML. Retry with --browser.")
        return list(bodies.values())

    def parse_detail(self, body: dict[str, Any], html: str, final_url: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        soup = BeautifulSoup(html, "html.parser")
        text = "\n".join(clean(x) for x in soup.stripped_strings if clean(x))
        body_obj = Body(**{k: body.get(k, "") for k in Body.__dataclass_fields__ if k in body})
        body_obj.detail_url = final_url
        body_obj.detail_text = text
        body_obj.scraped_at = now_iso()

        # General-information fields are label/value pairs in the profile.
        labels = {
            "phone": [r"Phone", r"전화"],
            "fax": [r"Fax", r"팩스"],
            "website": [r"Web", r"홈페이지"],
            "head_office": [r"Head Office", r"본사"],
        }
        for field, pats in labels.items():
            for pat in pats:
                m = re.search(rf"(?:{pat})\s*[:：]?\s*(.+?)(?=\n(?:Phone|Fax|Web|Head Office|Critical Locations|Go to Promotional Material|Certification Scheme|전화|팩스|홈페이지|본사)\b|$)", text, re.I | re.S)
                if m:
                    setattr(body_obj, field, clean(m.group(1)))
                    break

        accs: list[dict[str, Any]] = []
        # Profile structure repeats a scheme title, accreditation number/date,
        # category and accredited scope. Segment by ISO/scheme heading.
        headings = []
        for node in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
            t = clean(node.get_text(" ", strip=True))
            if re.search(r"(ISO\s*\d|FSSC|TL\s*9000|KS\s*Q)", t, re.I):
                headings.append(node)
        seen_acc = set()
        for node in headings:
            container = node.find_parent(["li", "tr", "div", "section", "article"]) or node.parent
            block = clean(container.get_text(" ", strip=True))
            if len(block) < 20:
                block = clean(node.parent.get_text(" ", strip=True))
            num_match = re.search(r"(KAB-[A-Z0-9-]+)\s*\((\d{4}-\d{2}-\d{2})\)", block)
            if not num_match:
                num_match = re.search(r"(KAB-[A-Z0-9-]+)", block)
            if not num_match:
                continue
            number = num_match.group(1)
            if (number, block) in seen_acc:
                continue
            seen_acc.add((number, block))
            date = num_match.group(2) if num_match.lastindex and num_match.lastindex >= 2 else ""
            scope = ""
            sm = re.search(r"(?:인정된 인증수행범위|Accredited Certification Scope|Accredited Scope)\s*[:：]?\s*(.*?)(?=Promotional Material|Go to Promotional|$)", block, re.I)
            if sm:
                scope = clean(sm.group(1))
            scheme = clean(node.get_text(" ", strip=True))
            accs.append(asdict(Accreditation(
                source_id=body["source_id"], body_name=body.get("name_english") or body.get("name_local", ""),
                scheme_name=scheme, accreditation_number=number,
                accreditation_date=date, accredited_scope=scope,
                status="listed_on_current_profile", source_detail_url=final_url,
                source_text=block,
            )))

        docs: list[dict[str, Any]] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(final_url, a["href"])
            title = clean(a.get_text(" ", strip=True)) or clean(a.get("title", ""))
            img = a.find("img")
            if img:
                title = title or clean(img.get("alt", "")) or "linked image/document"
            parsed = urlparse(href)
            low = (href + " " + title).lower()
            is_file = (
                parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".hwp", ".zip", ".png", ".jpg", ".jpeg"))
                or any(x in low for x in ("filedown", "download", "attach", "atchfile", "certificate", "인정서", "첨부"))
            )
            if not is_file or href in self.seen_doc_urls:
                continue
            self.seen_doc_urls.add(href)
            dtype = "accreditation_certificate_or_schedule"
            if any(x in low for x in ("promotional", "홍보")):
                dtype = "promotional_material"
            elif any(x in low for x in ("annex", "schedule", "scope", "부속", "범위")):
                dtype = "scope_schedule_or_annex"
            docs.append(asdict(Document(
                source_id=body["source_id"], body_name=body.get("name_english") or body.get("name_local", ""),
                document_type=dtype, title=title or Path(parsed.path).name or "linked_document",
                source_url=href, source_detail_url=final_url,
            )))

        # Image-based certificate thumbnails can be meaningful evidence. Record
        # them separately; don't mistake decorative site images for documents.
        for img in soup.find_all("img", src=True):
            alt = clean(img.get("alt", ""))
            src = urljoin(final_url, img["src"])
            if re.search(r"(ISO|인증서|certificate|accreditation)", alt, re.I) and src not in self.seen_doc_urls:
                self.seen_doc_urls.add(src)
                docs.append(asdict(Document(
                    source_id=body["source_id"], body_name=body.get("name_english") or body.get("name_local", ""),
                    document_type="certificate_image", title=alt or "certificate_image",
                    source_url=src, source_detail_url=final_url,
                )))
        return asdict(body_obj), accs, docs

    def download_document(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self.session.get(doc["source_url"], timeout=60, stream=True)
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip()
            chunks = []
            total = 0
            tmp_dir = OUT / "documents" / safe_name(doc["source_id"])
            tmp_dir.mkdir(parents=True, exist_ok=True)
            url_name = Path(urlparse(r.url).path).name
            ext = Path(url_name).suffix
            if not ext:
                ext = mimetypes.guess_extension(content_type) or ".bin"
            filename = safe_name(Path(doc["title"]).stem, "document") + ext
            path = tmp_dir / filename
            # Avoid overwriting same-named files from different links.
            if path.exists():
                filename = f"{safe_name(Path(filename).stem)}_{hashlib.md5(doc['source_url'].encode()).hexdigest()[:8]}{ext}"
                path = tmp_dir / filename
            with path.open("wb") as f:
                for chunk in r.iter_content(1024 * 128):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            if total == 0:
                raise ValueError("Downloaded response was empty")
            # Reject obvious HTML login/error pages saved under .pdf.
            with path.open("rb") as f:
                head = f.read(512).lstrip()
            if b"<html" in head.lower() or b"<!doctype html" in head.lower():
                path.unlink(missing_ok=True)
                raise ValueError("Server returned HTML instead of a document")
            doc.update({
                "local_path": str(path), "mime_type": content_type,
                "file_size": total, "sha256": sha256_file(path),
                "downloaded_at": now_iso(), "download_status": "downloaded",
            })
        except Exception as e:
            doc.update({"download_status": "failed", "error": repr(e), "downloaded_at": now_iso()})
            self.failures.append({"stage": "document_download", "url": doc["source_url"], "source_id": doc["source_id"], "error": repr(e), "at": now_iso()})
            LOG.warning("Document failed: %s (%s)", doc["source_url"], e)
        return doc

    def run(self):
        LOG.info("Starting KAB management-system CAB scrape")
        discovered = self.discover_directory()
        if self.args.limit:
            discovered = discovered[:self.args.limit]
        LOG.info("Discovered %d unique CAB profiles", len(discovered))

        for i, body in enumerate(discovered, 1):
            try:
                html, final_url = self.get_html(body["detail_url"])
                self.save_raw("details", body["source_id"], html)
                body_rec, accs, docs = self.parse_detail(body, html, final_url)
                self.bodies.append(body_rec)
                self.accreditations.extend(accs)
                LOG.info("[%d/%d] %s — %d accreditation records, %d linked files",
                         i, len(discovered), body_rec.get("name_english") or body_rec.get("name_local"),
                         len(accs), len(docs))
                for doc in docs:
                    self.documents.append(self.download_document(doc))
            except Exception as e:
                self.failures.append({"stage": "detail", "url": body["detail_url"], "source_id": body["source_id"], "error": repr(e), "at": now_iso()})
                LOG.exception("Profile failed: %s", body["detail_url"])
            time.sleep(self.args.delay)

        self.write_outputs(discovered)
        if self.browser:
            self.browser.close()
            self.playwright.stop()

    @staticmethod
    def write_json(path: Path, rows: list[dict[str, Any]]):
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def write_csv(path: Path, rows: list[dict[str, Any]]):
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        keys = list(dict.fromkeys(k for row in rows for k in row.keys()))
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    def write_outputs(self, discovered: list[dict[str, Any]]):
        outputs = {
            "bodies": self.bodies,
            "accreditations": self.accreditations,
            "documents": self.documents,
            "failures": self.failures,
        }
        for name, rows in outputs.items():
            self.write_json(OUT / f"{name}.json", rows)
            self.write_csv(OUT / f"{name}.csv", rows)
        manifest = {
            "authority": "Korea Accreditation Board (KAB)",
            "register": LIST_URL,
            "scope": "Management System (MS) Certification Bodies",
            "scraped_at": now_iso(),
            "directory_profiles_discovered": len(discovered),
            "profiles_scraped": len(self.bodies),
            "accreditation_records": len(self.accreditations),
            "documents_attempted": len(self.documents),
            "documents_downloaded": sum(d["download_status"] == "downloaded" for d in self.documents),
            "documents_failed": sum(d["download_status"] == "failed" for d in self.documents),
            "failures": len(self.failures),
            "important_note": (
                "KAB accreditation certificates/schedules are not the same as "
                "client management-system certificates issued by the CABs. "
                "This register scraper collects public documents linked by KAB; "
                "it does not claim to enumerate all client certificates."
            ),
        }
        (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        LOG.info("Finished. Bodies=%d accreditations=%d documents=%d failures=%d",
                 len(self.bodies), len(self.accreditations), len(self.documents), len(self.failures))


def main():
    p = argparse.ArgumentParser(description="Scrape KAB Management System Certification Bodies")
    p.add_argument("--browser", action="store_true", help="Use Playwright Chromium for JS-rendered pages")
    p.add_argument("--limit", type=int, default=0, help="Test only the first N bodies (0 = all)")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (default: 1)")
    p.add_argument("--max-pages", type=int, default=100, help="Maximum directory pages to inspect")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        KabScraper(args).run()
    except KeyboardInterrupt:
        LOG.warning("Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
