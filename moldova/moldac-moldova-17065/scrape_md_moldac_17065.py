"""Download the ISO/IEC 17065 product certification bodies from the MOLDAC register (Moldova).

Source: https://acreditare.md/en/register_category/organisme-de-certificare-a-produselor/
The register is a single static page ("detail__row" divs, Romanian text) with one row per body:
name + head, contact block, accreditation certificate (OCpr-NNN, PDF), annex PDFs, status, remark.
There is no management-system scraper for Moldova to derive from, so this one is standalone.

Outputs (default folder moldac_17065/):
  bodies.csv              one row per body, all register fields
  moldac_17065_raw.json   one record per accreditation (CertiFind input)
  scope_lines.csv         registration_no,source,row_index,product_text_raw
  documents/<OCpr>/       certificate + annex PDFs (skipped with --no-files; resumes)
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
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://acreditare.md/en/register_category/organisme-de-certificare-a-produselor/"
USER_AGENT = "Mozilla/5.0 (moldac-17065-scraper/1.0; accredited body register export)"
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

log = logging.getLogger("moldac17065")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def col_lines(col) -> list[str]:
    """Text of a column split on its <br> blocks (the site wraps each line in <br>..</br>)."""
    for br in col.find_all("br"):
        br.insert_before("\n")
        br.insert_after("\n")
    return [clean(t) for t in col.get_text("").split("\n") if clean(t)]


def parse_contact(lines: list[str]) -> dict:
    info = {"address": "", "phone": "", "fax": "", "email": "", "website": ""}
    rest = []
    for line in lines:
        key, _, value = line.partition(":")
        k = key.lower()
        if "adres" in k:
            info["address"] = "; ".join(p for p in (info["address"], value.strip()) if p)
        elif k.startswith("tel"):
            info["phone"] = value.strip()
            if "fax" in k and not info["fax"]:
                info["fax"] = value.strip()
        elif k.startswith("fax"):
            info["fax"] = value.strip()
        elif "mail" in k:
            info["email"] = ", ".join(EMAIL_RE.findall(value)) or value.strip()
        elif "web" in k or "site" in k:
            info["website"] = line.split(":", 1)[1].strip() if ":" in line else line
        else:
            rest.append(line)
    if not info["email"]:
        info["email"] = ", ".join(e for l in rest for e in EMAIL_RE.findall(l))
    info["contact_other"] = "; ".join(rest)
    return info


def file_date(url: str) -> str:
    """Date in a document's file name (e.g. CMAC-10.09.2026.signed.pdf), ISO formatted."""
    m = DATE_RE.search(unquote(url.rsplit("/", 1)[-1]))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def parse_register(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = [r for r in soup.select("div.detail__row") if "head" not in r.get("class", [])]
    if not rows:
        raise RuntimeError("no register rows found: page layout may have changed")
    bodies = []
    for row in rows:
        cols = row.find_all("div", class_="detail__col", recursive=False)
        if len(cols) < 6:
            log.warning("skipping row with %d columns", len(cols))
            continue
        name_lines = col_lines(cols[1])
        cert_links = [(clean(a.get_text()), urljoin(URL, a["href"]))
                      for a in cols[3].find_all("a", href=True)]
        annexes = [{"title": clean(a.get_text()), "url": urljoin(URL, a["href"])}
                   for a in cols[4].find_all("a", href=True)]
        cert_text = clean(cols[3].get_text(" "))
        reg = cert_links[0][0] if cert_links else cert_text
        bodies.append({
            "row_no": clean(cols[0].get_text()),
            "registration_no": re.sub(r"\s*-\s*", "-", reg),
            "name": name_lines[0] if name_lines else "",
            "head": "; ".join(name_lines[1:]),
            **parse_contact(col_lines(cols[2])),
            "certificate_url": cert_links[0][1] if cert_links else "",
            "certificate_file_date": file_date(cert_links[0][1]) if cert_links else "",
            "annexes": annexes,
            "status": clean(cols[5].get_text(" ")),
            "remark": clean(cols[6].get_text(" ")) if len(cols) > 6 else "",
        })
    return bodies


class Client:
    def __init__(self, delay: float = 0.5, timeout: float = 60):
        self.delay, self.timeout = delay, timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def get(self, url: str) -> requests.Response:
        time.sleep(self.delay)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response

    def download(self, url: str, target: Path) -> bool:
        """True if the file is on disk afterwards (already there or downloaded)."""
        if target.exists() and target.stat().st_size:
            return True
        try:
            data = self.get(url).content
        except requests.RequestException as exc:
            log.error("download failed %s: %s", url, exc)
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True


def pdf_lines(path: Path) -> list[str] | None:
    """Text lines of a PDF, [] if it has no text layer, None if pypdf is unavailable."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception as exc:  # noqa: BLE001 - a broken PDF is reported, not fatal
        log.warning("cannot read %s: %s", path.name, exc)
        return []
    return [clean(t) for t in text.splitlines() if clean(t)]


def safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_.") or "x"


def run(args: argparse.Namespace) -> int:
    client = Client(args.delay)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    bodies = parse_register(client.get(URL).text)
    log.info("register lists %d product certification bodies", len(bodies))
    if args.limit:
        bodies = bodies[: args.limit]

    stats = {"downloaded": 0, "failed": [], "pdf_with_text": 0, "pdf_scanned": [], "no_pypdf": False}
    lines: list[list] = []
    raw = []
    for body in bodies:
        reg = body["registration_no"]
        for i, annex in enumerate(body["annexes"]):
            lines.append([reg, "register", i, annex["title"]])
        if not args.no_files:
            folder = out / "documents" / safe(reg)
            docs = ([("certificate", body["certificate_url"])] if body["certificate_url"] else []) + \
                   [("annex", a["url"]) for a in body["annexes"]]
            for kind, url in docs:
                target = folder / safe(unquote(url.rsplit("/", 1)[-1]))
                if not client.download(url, target):
                    stats["failed"].append(url)
                    continue
                stats["downloaded"] += 1
                if kind != "annex":
                    continue
                text = pdf_lines(target)
                if text is None:
                    stats["no_pypdf"] = True
                elif text:
                    stats["pdf_with_text"] += 1
                    lines += [[reg, f"annex:{target.name}", j, t] for j, t in enumerate(text)]
                else:
                    stats["pdf_scanned"].append(target.name)
        raw.append({
            "registration_no": reg, "id": body["row_no"], "name": body["name"],
            "address": body["address"], "phone": body["phone"], "email": body["email"],
            "website": body["website"], "issued": "", "expiry": "",
            "certificate_file_date": body["certificate_file_date"], "status": body["status"],
            "remark": body["remark"], "certificate_url": body["certificate_url"],
            "annex_urls": [a["url"] for a in body["annexes"]],
            "annex_titles": [a["title"] for a in body["annexes"]],
        })
        log.info("%s %s (%s, %d annexes)", reg, body["name"], body["status"], len(body["annexes"]))

    (out / "moldac_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    columns = ["row_no", "registration_no", "name", "head", "address", "phone", "fax", "email",
               "website", "contact_other", "status", "remark", "certificate_url",
               "certificate_file_date", "annex_count"]
    with open(out / "bodies.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, columns, extrasaction="ignore")
        writer.writeheader()
        for body in bodies:
            writer.writerow({**body, "annex_count": len(body["annexes"])})
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        writer.writerows(lines)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": URL, "bodies": len(bodies),
              "statuses": {s: sum(b["status"] == s for b in bodies) for s in {b["status"] for b in bodies}},
              "annexes": sum(len(b["annexes"]) for b in bodies), "scope_lines": len(lines), **stats}
    (out / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"bodies: {len(bodies)}  annexes: {report['annexes']}  scope lines: {len(lines)}  "
          f"PDFs downloaded: {stats['downloaded']} failed: {len(stats['failed'])}  "
          f"annexes with text: {stats['pdf_with_text']} scanned: {len(stats['pdf_scanned'])}"
          + ("  (pypdf missing: annex text not extracted)" if stats["no_pypdf"] else ""))
    return 1 if stats["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default=str(Path(__file__).parent / "moldac_17065"))
    parser.add_argument("--no-files", action="store_true", help="skip PDF downloads")
    parser.add_argument("--limit", type=int, default=0, help="only the first N bodies")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
