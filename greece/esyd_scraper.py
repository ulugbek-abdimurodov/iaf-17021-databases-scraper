#!/usr/bin/env python3
"""Download every ISO/IEC 17021-1 accredited body from the Greek ESYD register.

How it works
------------
1. Walk the full bodies catalogue (showCatalogue.jsp) to collect every body id.
2. Open each body's detail page (showOrgInfo.jsp) and keep the body only if its
   accreditation table has a row under the 17021 standard. ESYD labels the
   standard "ELOT EN ISO/IEC 17021"; that label is the site's 17021-1 scheme.
3. Rows with a blank English field name are filled in from the Greek page.
4. Cross-check against the site's own search for the 17021 standard and report
   any disagreement. The detail page decides what is included.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE_URL = "http://www.esydops.gr/portal/p/esyd/"
USER_AGENT = "esyd-17021-scraper/1.0 (accredited body register export)"
MAX_CATALOGUE_PAGES = 200

# Matches 17021 and 17021-1, but not the separate 17021-2, 17021-3, ... parts.
STANDARD_RE = re.compile(r"17021(?!\d)(?!\s*-\s*[2-9])")
HEADER_MARKERS = ("Certificate Number", "Αριθμός Πιστοποιητικού")
SCOPE_ID_RE = re.compile(r"/eped/(?P<id>[^/]+?)_(?P<lang>el|en)\.\w+$", re.I)
ORG_ID_RE = re.compile(r"showOrgInfo\.jsp\?id=(\d+)")
MISSING_TR_RE = re.compile(r"</tr>\s*<td", re.I)

log = logging.getLogger("esyd")


class ParseError(Exception):
    """A page did not have the expected structure (site layout may have changed)."""


@dataclass
class Accreditation:
    standard: str
    field: str
    field_language: str
    certificate_number: str
    valid_since: str
    scope_doc_en: str = ""
    scope_doc_el: str = ""


@dataclass
class Body:
    body_id: str
    name: str = ""
    address: str = ""
    city: str = ""
    region: str = ""
    telephone: str = ""
    fax: str = ""
    email: str = ""
    website: str = ""
    detail_url: str = ""
    accreditations: list[Accreditation] = field(default_factory=list)


# --------------------------------------------------------------------- parsing
def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def soupify(html: str) -> BeautifulSoup:
    # Detail pages omit the opening <tr> on most rows ("</tr> <td>..."). Browsers
    # repair this, but parsers differ, so restore the tag before parsing.
    return BeautifulSoup(MISSING_TR_RE.sub("</tr><tr><td", html), "lxml")


def leaf_tables(soup: BeautifulSoup):
    return [t for t in soup.find_all("table") if not t.find("table")]


def parse_catalogue_ids(html: str) -> list[str]:
    soup = soupify(html)
    ids = []
    for a in soup.find_all("a", href=True):
        match = ORG_ID_RE.search(a["href"])
        if match:
            ids.append(match.group(1))
    return ids


def parse_contact(soup: BeautifulSoup) -> dict[str, str]:
    for table in leaf_tables(soup):
        text = table.get_text(" ")
        if "Address" in text and "Telephone" in text:
            rows = table.find_all("tr")
            info = {"name": clean(rows[0].get_text(" "))}
            for row in rows[1:]:
                cells = row.find_all("td", recursive=False)
                if len(cells) >= 2:
                    info[clean(cells[0].get_text(" ")).lower()] = clean(cells[1].get_text(" "))
            return info
    raise ParseError("contact table not found")


def parse_accreditation_rows(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Every accreditation row on a detail page, whichever its standard."""
    table = None
    for candidate in leaf_tables(soup):
        first = candidate.find("tr")
        if first and any(m in first.get_text(" ") for m in HEADER_MARKERS):
            table = candidate
            break
    if table is None:
        raise ParseError("accreditation table not found")

    rows, standard = [], ""
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td", recursive=False)
        if len(cells) == 5:  # first row of a group carries the rowspan standard cell
            standard = clean(cells[0].get_text(" "))
            cells = cells[1:]
        elif len(cells) != 4:
            continue
        docs = {"en": "", "el": "", "id": ""}
        for a in tr.find_all("a", href=True):
            match = SCOPE_ID_RE.search(a["href"])
            if match:
                docs[match.group("lang").lower()] = urljoin(base_url, a["href"])
                docs["id"] = match.group("id")
        rows.append({
            "standard": standard,
            "field": clean(cells[0].get_text(" ")),
            "certificate_number": clean(cells[1].get_text(" ")),
            "valid_since": clean(cells[2].get_text(" ")),
            "docs": docs,
        })
    return rows


def is_target_standard(standard: str) -> bool:
    return bool(STANDARD_RE.search(standard))


# ---------------------------------------------------------------------- scraper
class Scraper:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, delay: float = 0.3, timeout: float = 30):
        self.base = base_url.rstrip("/") + "/"
        self.en = self.base + "en/"
        self.el = self.base + "el/"
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=None)
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        time.sleep(self.delay)
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def _html(self, method: str, url: str, **kwargs) -> str:
        response = self._request(method, url, **kwargs)
        # The site serves UTF-8 Greek; never let requests guess ISO-8859-1.
        match = re.search(r"charset=([\w-]+)", response.headers.get("content-type", ""), re.I)
        response.encoding = match.group(1) if match else "utf-8"
        return response.text

    def catalogue_ids(self) -> list[str]:
        ids: list[str] = []
        for page in range(1, MAX_CATALOGUE_PAGES + 1):
            html = self._html("GET", f"{self.en}showCatalogue.jsp",
                              params={"type": "Body", "letter": "all", "page": page})
            page_ids = parse_catalogue_ids(html)
            new = [i for i in page_ids if i not in ids]
            if not new:
                break
            ids.extend(new)
            log.info("catalogue page %d: %d bodies (total %d)", page, len(new), len(ids))
        if not ids:
            raise ParseError("catalogue returned no bodies")
        return ids

    def search_ids(self) -> list[str]:
        """Ids the site's own search returns for the 17021 standard."""
        ids: list[str] = []
        for page in range(1, MAX_CATALOGUE_PAGES + 1):
            html = self._html("POST", f"{self.en}showResults.jsp", data={
                "nomos": "", "protypoDiap": "accStd:17021", "protypoPist": "", "antikeimeno": "",
                "ea": "", "nace": "", "type": "Body", "page": str(page),
            })
            new = [i for i in parse_catalogue_ids(html) if i not in ids]
            if not new:
                break
            ids.extend(new)
        return ids

    def fetch_body(self, body_id: str) -> Body | None:
        """The body with its 17021 rows, or None if it has no 17021 accreditation."""
        url = f"{self.en}showOrgInfo.jsp?id={body_id}"
        soup = soupify(self._html("GET", url))
        rows = [r for r in parse_accreditation_rows(soup, self.base)
                if is_target_standard(r["standard"])]
        if not rows:
            return None

        contact = parse_contact(soup)
        greek = self._greek_fields(body_id) if any(not r["field"] for r in rows) else {}

        body = Body(
            body_id=body_id, name=contact.get("name", ""), address=contact.get("address", ""),
            city=contact.get("city", ""), region=contact.get("region", ""),
            telephone=contact.get("telephone", ""), fax=contact.get("fax", ""),
            email=contact.get("email", ""), website=contact.get("website", ""), detail_url=url,
        )
        for row in rows:
            name, language = row["field"], "en"
            if not name:
                name, language = greek.get(row["docs"]["id"], ""), "el"
                if not name:
                    language = ""
                    log.warning("body %s: no field name in either language (scope %s)",
                                body_id, row["docs"]["id"])
            body.accreditations.append(Accreditation(
                standard=row["standard"], field=name, field_language=language,
                certificate_number=row["certificate_number"], valid_since=row["valid_since"],
                scope_doc_en=row["docs"]["en"], scope_doc_el=row["docs"]["el"],
            ))
        return body

    def _greek_fields(self, body_id: str) -> dict[str, str]:
        soup = soupify(self._html("GET", f"{self.el}showOrgInfo.jsp?id={body_id}"))
        return {r["docs"]["id"]: r["field"] for r in parse_accreditation_rows(soup, self.base)
                if r["docs"]["id"]}

    def download_docs(self, bodies: list[Body], out_dir: Path, languages: list[str]) -> list[dict]:
        failures = []
        for body in bodies:
            folder = out_dir / f"{body.body_id}_{safe_name(body.name)}"
            folder.mkdir(parents=True, exist_ok=True)
            for acc in body.accreditations:
                for language in languages:
                    url = acc.scope_doc_en if language == "en" else acc.scope_doc_el
                    if not url:
                        continue
                    target = folder / url.rsplit("/", 1)[-1]
                    if target.exists() and target.stat().st_size:
                        continue  # lets an interrupted run resume
                    try:
                        data = self._request("GET", url).content
                    except requests.RequestException as exc:
                        log.error("download failed %s: %s", url, exc)
                        failures.append({"url": url, "error": str(exc)})
                        continue
                    target.write_bytes(data)
            log.info("scope documents done: %s", body.name)
        return failures


def safe_name(name: str, limit: int = 60) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_.")
    return cleaned[:limit].rstrip("_.") or "body"


# ----------------------------------------------------------------------- output
BODY_COLUMNS = ["body_id", "name", "address", "city", "region", "telephone", "fax", "email",
                "website", "certificate_numbers", "scope_count", "detail_url"]
ACCREDITATION_COLUMNS = ["body_id", "body_name", "standard", "field", "field_language",
                         "certificate_number", "valid_since", "scope_doc_en", "scope_doc_el"]


def write_outputs(bodies: list[Body], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel displays the Greek text correctly.
    with open(out_dir / "bodies.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, BODY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for body in bodies:
            certificates = dict.fromkeys(a.certificate_number for a in body.accreditations
                                         if a.certificate_number)
            writer.writerow({**asdict(body), "certificate_numbers": "; ".join(certificates),
                             "scope_count": len(body.accreditations)})
    with open(out_dir / "accreditations.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, ACCREDITATION_COLUMNS)
        writer.writeheader()
        for body in bodies:
            for acc in body.accreditations:
                writer.writerow({"body_id": body.body_id, "body_name": body.name, **asdict(acc)})
    with open(out_dir / "bodies.json", "w", encoding="utf-8") as handle:
        json.dump([asdict(b) for b in bodies], handle, ensure_ascii=False, indent=2)


# -------------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> int:
    scraper = Scraper(args.base_url, args.delay)
    out_dir = Path(args.output)

    ids = scraper.catalogue_ids()
    log.info("catalogue lists %d bodies; checking each for 17021", len(ids))
    if args.limit:
        ids = ids[: args.limit]

    bodies: list[Body] = []
    errors: list[dict] = []
    checked: set[str] = set()
    for index, body_id in enumerate(ids, 1):
        try:
            body = scraper.fetch_body(body_id)
            checked.add(body_id)
        except (requests.RequestException, ParseError) as exc:
            log.error("body %s failed: %s", body_id, exc)
            errors.append({"body_id": body_id, "error": str(exc)})
            continue
        if body:
            bodies.append(body)
            log.info("[%d/%d] 17021: %s (%d scopes)", index, len(ids), body.name,
                     len(body.accreditations))

    write_outputs(bodies, out_dir)

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": scraper.en,
        "catalogue_bodies_checked": len(checked),
        "bodies_17021": len(bodies),
        "accreditation_rows": sum(len(b.accreditations) for b in bodies),
        "rows_without_field_name": sum(1 for b in bodies for a in b.accreditations if not a.field),
        "errors": errors,
    }

    found = {b.body_id for b in bodies}
    if not args.limit:
        try:
            search = set(scraper.search_ids())
            report["search_cross_check"] = {
                "search_results": len(search),
                # Search hit, but the detail page has no 17021 row: excluded from the output.
                "in_search_but_no_17021_on_detail_page": sorted(search & checked - found),
                "in_search_but_not_in_catalogue": sorted(search - set(ids)),
                "has_17021_but_not_in_search": sorted(found - search),
            }
        except (requests.RequestException, ParseError) as exc:
            log.warning("search cross-check failed: %s", exc)
            report["search_cross_check"] = {"error": str(exc)}

    if args.download_docs != "none":
        languages = ["en", "el"] if args.download_docs == "both" else [args.download_docs]
        report["download_failures"] = scraper.download_docs(bodies, out_dir / "scope_documents",
                                                            languages)

    (out_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    log.info("done: %d bodies, %d rows, written to %s", report["bodies_17021"],
             report["accreditation_rows"], out_dir)
    if errors or report.get("download_failures"):
        log.error("run incomplete: see run_report.json")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default="output", help="output folder (default: output)")
    parser.add_argument("--download-docs", choices=("none", "en", "el", "both"), default="none",
                        help="also download the scope-of-accreditation .doc files")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    parser.add_argument("--limit", type=int, default=0,
                        help="check only the first N catalogue bodies (for a quick trial)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        return run(args)
    except (requests.RequestException, ParseError) as exc:
        log.error("aborted: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
