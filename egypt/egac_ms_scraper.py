#!/usr/bin/env python3
"""
Scraper for EGAC-accredited Management System Certification Bodies.
Source: https://egac.gov.eg/en/accredited-cabs/

Collects, for every body and every status (Accredited, Suspended, Withdrawn, Expired):
  - register data: name, reference no., country, dates, logo
  - contacts: address, phone, fax, email, website, PO box, contact persons
  - accredited scopes, as a hierarchy
  - scope/annex PDFs and certificate PDFs

Setup:   pip install requests beautifulsoup4
Run:     python egac_ms_scraper.py
Options: python egac_ms_scraper.py --help

Re-running resumes: PDFs already on disk are skipped.

Output (default folder: egac_ms_bodies/):
  cabs.json       everything, nested
  cabs.csv        one row per body
  contacts.csv    one row per contact person
  panels.csv      one row per accreditation block on a body's page
  scopes.csv      one row per scope line
  files.csv       one row per PDF, with its local path and download result
  logos/          logos
  files/<ref - name>/<status>/<accreditation>/{scopes,certificates}/*.pdf
"""
import argparse
import csv
import json
import math
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SITE = "https://egac.gov.eg"
LIST_PAGE = "/en/accredited-cabs/"
AJAX = "/wp-admin/admin-ajax.php"
DOWNLOAD_API = "https://systemapi.egac.gov.eg/api/download_attachments"

MS_ROOT_LABEL = "Management System Certification Bodies"
STATUSES = {1: "Accredited", 2: "Suspended", 3: "Withdrawn", 4: "Expired"}
FILE_TYPES = {"1": "scopes", "2": "certificates"}
PAGE_SIZE = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en",
}


def text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def safe_name(value, limit=90):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "").strip(" .")
    return value[:limit].rstrip(" .") or "unnamed"


class Client:
    def __init__(self, delay, timeout=180, retries=4):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay, self.timeout, self.retries = delay, timeout, retries

    def request(self, method, url, **kwargs):
        last = None
        for attempt in range(self.retries):
            try:
                time.sleep(self.delay)
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last = exc
                time.sleep(2 ** attempt * 2)
        raise last


def ms_scope_ids(client, root_label):
    """The listing filter needs every scope id under the discipline, not just its root."""
    soup = BeautifulSoup(client.request("GET", SITE + LIST_PAGE).text, "html.parser")
    for label in soup.select("label.custom-control-label"):
        if text(label) == root_label:
            box = soup.find("input", id=label.get("for"))
            container = box.find_parent(class_="parent-container")
            ids = [i["value"] for i in container.select("input.scopes")]
            if ids:
                return ids
    raise RuntimeError(f"Scope '{root_label}' not found on the listing page; the site may have changed.")


def parse_listing(html):
    soup = BeautifulSoup(html, "html.parser")
    counter = soup.select_one(".main_counter")
    total = int(counter["value"]) if counter and str(counter.get("value", "")).isdigit() else 0
    rows = []
    for tr in soup.select("tbody tr"):
        link = tr.select_one("a.cabs-name")
        if not link:
            continue
        cells = [text(c) for c in tr.select(".date-td")]
        logo = link.find("img")
        rows.append({
            "name": text(tr.select_one(".title-td")),
            "reference_no": cells[0] if len(cells) > 0 else "",
            "country": cells[1] if len(cells) > 1 else "",
            # Accredited rows have two dates. Other statuses have one, e.g. "Withdrawn date".
            "accreditation_date": cells[2] if len(cells) > 3 else "",
            "expiry_date": cells[3] if len(cells) > 3 else "",
            "status_date": cells[2] if len(cells) == 3 else "",
            "detail_url": urljoin(SITE, link["href"]),
            "logo_url": urljoin(SITE, logo["src"]) if logo and logo.get("src") else "",
        })
    return total, rows


def fetch_listing(client, status, scope_ids):
    rows, page, pages = [], 1, 1
    while page <= pages:
        data = [("action", "certifications_action"), ("page_no", page), ("status", status),
                ("country_id", ""), ("search_word", ""), ("from_date", ""), ("to_date", "")]
        data += [("scopes[]", s) for s in scope_ids]
        total, found = parse_listing(client.request("POST", SITE + AJAX, data=data).text)
        rows += found
        pages = math.ceil(total / PAGE_SIZE)
        print(f"  {STATUSES[status]}: page {page}/{max(pages, 1)} ({total} bodies)")
        if not found:
            break
        page += 1
    return rows


def parse_scopes(panel):
    """Flatten the scope tree, keeping each line's level and its path of parents."""
    scopes = []
    header = panel.select_one(".treeHeader")
    path = {}
    if header:
        name = text(header.select_one(".name"))
        path[1] = name
        scopes.append({"level": 1, "label": text(header.select_one(".label")), "name": name, "path": name})
    for li in panel.select(".treeList li"):
        box = li.select_one(":scope > .li-parent > .li-container")
        if not box:
            continue
        level_text = text(box.select_one(".li-box"))
        level = int(level_text) if level_text.isdigit() else 0
        name = text(box.select_one(".li-content .text")) or text(box.select_one(".li-content"))
        path = {k: v for k, v in path.items() if k < level}
        path[level] = name
        scopes.append({"level": level, "label": "", "name": name,
                       "path": " > ".join(path[k] for k in sorted(path))})
    return scopes


def parse_contact_boxes(pane):
    """Return [(label, value, icon_name)] from a contact tab."""
    items = []
    for box in pane.select(".box") if pane else []:
        icon = box.select_one("img.icon")
        items.append((text(box.select_one(".box-label")), text(box.select_one(".box-data")),
                      Path(icon.get("src", "")).stem if icon else ""))
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    result = {"name_on_page": text(soup.select_one(".description-title")),
              "date_label": text(soup.select_one(".description-label")),
              "date_on_page": text(soup.select_one(".description-date")),
              "contacts": {label: value for label, value, _ in parse_contact_boxes(soup.select_one("#CAB-Contacts"))},
              "contact_persons": [], "accreditations": []}

    person = None
    for label, value, icon in parse_contact_boxes(soup.select_one("#Contact-Person")):
        if icon == "user":  # a user icon opens each person: value is the name, label the job title
            person = {"Name": value, "Title": label}
            result["contact_persons"].append(person)
        elif person is not None:
            person[label] = value

    for status in STATUSES.values():
        pane = soup.find(id=status)
        if not pane:
            continue
        for panel in pane.select(".panel"):
            files = []
            for box in panel.select(".Scope-container .box"):
                box_label = text(box.select_one(".label"))
                for a in box.select("a[onclick*=DownloadFile]"):
                    files.append({"section": box_label, "type": a.get("data-type", ""),
                                  "file_id": a.get("data-file", ""), "file_name": a.get("data-name", "")})
            result["accreditations"].append({
                "status": status,
                "title": text(panel.select_one(".header-text")),
                "scopes": parse_scopes(panel),
                "files": files,
            })
    return result


def fetch_detail(client, url, attempts=3, wait=20):
    """The site sometimes answers HTTP 200 with the contacts or accreditation blocks empty,
    and the same page is complete on a later try. Retry until both are present."""
    detail = None
    for attempt in range(attempts):
        detail = parse_detail(client.request("GET", url).text)
        if detail["name_on_page"] and detail["accreditations"]:
            detail["incomplete"] = ""
            return detail
        if attempt < attempts - 1:
            print(f"  page came back incomplete, retrying in {wait}s ({attempt + 1}/{attempts})")
            time.sleep(wait)
    detail["incomplete"] = "yes"
    return detail


def save_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)


def download_pdf(client, item, target):
    if target.exists() and target.stat().st_size > 0:
        return "already on disk"
    # The site's field names really are crossed: "file" holds the name, "file_name" the stored id.
    response = client.request("POST", DOWNLOAD_API, data={
        "file": item["file_name"], "file_name": item["file_id"], "type": item["type"]})
    if not response.content.startswith(b"%PDF"):
        return f"not a PDF ({response.headers.get('content-type')}, {len(response.content)} bytes)"
    save_atomic(target, response.content)
    return "downloaded"


def unique_path(folder, name, used):
    path = folder / name
    stem, suffix, n = path.stem, path.suffix, 2
    while str(path) in used:
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    used.add(str(path))
    return path


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(out, cabs):
    (out / "cabs.json").write_text(json.dumps(cabs, ensure_ascii=False, indent=2), encoding="utf-8")

    contact_keys = sorted({k for c in cabs for k in c.get("contacts", {})})
    person_keys = sorted({k for c in cabs for p in c.get("contact_persons", []) for k in p})
    base = ["reference_no", "name", "listed_status", "country", "accreditation_date",
            "expiry_date", "status_date", "date_label", "date_on_page", "detail_url", "logo_file",
            "incomplete", "error"]
    write_csv(out / "cabs.csv", [{**c, **c.get("contacts", {})} for c in cabs], base + contact_keys)

    people, panels, scopes, files = [], [], [], []
    for c in cabs:
        who = {"reference_no": c["reference_no"], "cab_name": c["name"]}
        people += [{**who, **p} for p in c.get("contact_persons", [])]
        for acc in c.get("accreditations", []):
            ctx = {**who, "status": acc["status"], "accreditation": acc["title"]}
            panels.append({**ctx, "scope_lines": len(acc["scopes"]), "files": len(acc["files"])})
            scopes += [{**ctx, **s} for s in acc["scopes"]]
            files += [{**ctx, **f} for f in acc["files"]]

    write_csv(out / "contacts.csv", people, ["reference_no", "cab_name"] + person_keys)
    ctx = ["reference_no", "cab_name", "status", "accreditation"]
    write_csv(out / "panels.csv", panels, ctx + ["scope_lines", "files"])
    write_csv(out / "scopes.csv", scopes, ctx + ["level", "label", "name", "path"])
    write_csv(out / "files.csv", files, ctx + ["section", "type", "file_name", "file_id", "local_path", "result"])
    return len(files), sum(1 for f in files if f.get("result") in ("downloaded", "already on disk"))


def main():
    parser = argparse.ArgumentParser(description="Download EGAC Management System Certification Body data and PDFs.")
    parser.add_argument("--out", default="egac_ms_bodies", help="output folder")
    parser.add_argument("--status", nargs="+", default=list(STATUSES.values()), choices=list(STATUSES.values()),
                        help="which register statuses to include (default: all)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds to wait before each request")
    parser.add_argument("--no-files", action="store_true", help="collect data only, skip PDFs and logos")
    parser.add_argument("--limit", type=int, help="only the first N bodies (for a trial run)")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.delay)

    print("Reading scope filter...")
    scope_ids = ms_scope_ids(client, MS_ROOT_LABEL)
    print(f"  {len(scope_ids)} scope ids under '{MS_ROOT_LABEL}'")

    cabs, seen = [], {}
    for code, label in STATUSES.items():
        if label not in args.status:
            continue
        for row in fetch_listing(client, code, scope_ids):
            if row["detail_url"] in seen:  # a body can appear under more than one status
                if label not in seen[row["detail_url"]]["listed_status"]:
                    seen[row["detail_url"]]["listed_status"] += f"; {label}"
            else:
                seen[row["detail_url"]] = {**row, "listed_status": label}
                cabs.append(seen[row["detail_url"]])
    if args.limit:
        cabs = cabs[:args.limit]
    print(f"{len(cabs)} bodies to process")

    used_paths = set()
    for index, cab in enumerate(cabs, 1):
        print(f"[{index}/{len(cabs)}] {cab['reference_no']} {cab['name']}")
        try:
            cab.update(fetch_detail(client, cab["detail_url"]))
        except Exception as exc:
            cab["error"] = f"detail page: {exc}"
            print(f"  ERROR {cab['error']}", file=sys.stderr)
            continue

        folder_name = safe_name(f"{cab['reference_no']} - {cab['name']}")
        if not args.no_files and cab.get("logo_url"):
            suffix = Path(cab["logo_url"].split("?")[0]).suffix or ".img"
            logo = out / "logos" / f"{folder_name}{suffix}"
            try:
                if not logo.exists():
                    save_atomic(logo, client.request("GET", cab["logo_url"]).content)
                cab["logo_file"] = str(logo.relative_to(out))
            except Exception as exc:
                print(f"  logo failed: {exc}", file=sys.stderr)

        for acc in cab.get("accreditations", []):
            for item in acc["files"]:
                kind = FILE_TYPES.get(item["type"], f"type_{item['type']}")
                folder = out / "files" / folder_name / acc["status"] / safe_name(acc["title"]) / kind
                target = unique_path(folder, safe_name(item["file_name"], 120), used_paths)
                item["local_path"] = str(target.relative_to(out))
                if args.no_files:
                    item["result"] = "skipped"
                    continue
                try:
                    item["result"] = download_pdf(client, item, target)
                except Exception as exc:
                    item["result"] = f"error: {exc}"
                print(f"  {item['file_name']}: {item['result']}")
        write_outputs(out, cabs)  # saved after each body, so an interrupted run keeps its data

    total, ok = write_outputs(out, cabs)
    errors = [c for c in cabs if c.get("error")]
    incomplete = [c["reference_no"] for c in cabs if c.get("incomplete")]
    print(f"\nDone: {len(cabs)} bodies ({len(errors)} with errors), {ok}/{total} PDFs on disk. Output: {out.resolve()}")
    if incomplete:
        print(f"{len(incomplete)} pages still incomplete after retries (see 'incomplete' in cabs.csv); "
              f"run again to retry: {', '.join(incomplete)}")
    if not args.no_files and ok < total:
        print("Some PDFs failed: see the 'result' column in files.csv, then run again to retry them.")


if __name__ == "__main__":
    main()