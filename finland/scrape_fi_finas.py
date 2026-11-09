#!/usr/bin/env python3
"""Scrape FINAS (Finland) management system certification bodies.

Source: https://www.finas.fi/sites/en/operators/Pages/default.aspx
FINAS publishes no record API. The page runs a SharePoint search over
https://www.finas.fi/Scopes through client.svc/ProcessQuery (a read-only query
that needs only the anonymous form digest from the page) and each record is one
scope PDF. The accreditation standard is read from that PDF, and only records
whose PDF names ISO/IEC 17021 are kept.

    pip install requests pypdf
    python scrape_fi_finas.py --out fi_ms_output --delay 0.5
"""
import argparse
import csv
import datetime
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

import requests
from pypdf import PdfReader

BASE = "https://www.finas.fi"
PAGE = BASE + "/sites/en/operators/Pages/default.aspx"
ENDPOINT = BASE + "/sites/en/operators/_vti_bin/client.svc/ProcessQuery"
SOURCE_ID = "{8413cd39-2156-4e00-b54d-11efd9abdb89}"
REFINEMENT = 'RefinableString02:"ǂǂ536572746966696f696e7469656c696d6574"'  # Sertifiointielimet
QUERY_TEMPLATE = '{SearchBoxQuery} path:"https://www.finas.fi/Scopes" '
PAGE_SIZE = 15  # the site caps results per request at 15, whatever RowLimit asks for
UA = "Mozilla/5.0 (compatible; finas-registry-scraper/1.0)"

ACCRED_STD = re.compile(r"(?<!\d)(17021|17065|17024|17029)(?!\d)")
STD_LINE = re.compile(r"\(ISO|\bISO/?(IEC|TS)?\s?\d{4,5}|järjestelmät\s*[/(]|management systems?\s*\(", re.I)
MS_STD = re.compile(r"ISO(?:/IEC|/TS)?\s?\d{4,5}|EN\s\d{4,5}|IATF\s?\d{4,5}|FSSC\s?\d+")
HEADINGS = re.compile(r"^(Akkreditoitu pätevyysalue|Järjestelmäsertifiointi|Certification of management systems)$", re.I)
NOISE = re.compile(
    r"^(\d+/\d+)?\s*FINAS (kuuluu|is a signatory)|^for accreditation\.?$|^www\.finas\.fi|"
    r"Päätöksen (päiväys|viimeinen)|^Date of |^Vaatimus\s*/|^\S+/[AM]\d+/\d{4}Liite|^S\s?\d{3}\s?/\s?[AM]|"
    r"^Liite 1|^Päätöksen numero|^Akkreditoinnin vaatimus|^Akkreditointialue|^Päätöspvm|"
    r"^\d{1,2}\.\d{1,2}\.\s?\d{4}|^S\d{3},|^AKKREDITOITU|^ACCREDITED CERT|^Toimipisteet$|^Toimiala \(IAF|"
    r"^Tunnus$|^Code$|^Sertifiointielin$|^Certification body$|^Osoite$|^Address$|^www$|^Sivu/Page|^Page \d|"
    r"\d{5}[A-ZÄÖÅ].*Suomi|^Toimipisteen nimi|^Katuosoite|^Postinumero|^Postitoimipaikka|^Maa$|^Toimipisteen lyhenne",
    re.I,
)

BODY_COLS = ["ident", "url", "company", "accreditation_name", "state", "standard", "cvr", "address",
             "contact_name", "phone", "email", "website", "started", "renewed", "expires", "scope_entries",
             "decision_no", "ms_standards", "pages"]
SCOPE_COLS = ["ident", "company", "scheme_title", "scheme_url", "published", "row_type",
              "column1", "column2", "comment"]


def build_request(start):
    """The search request sent by the page, reduced to the fields this site needs."""
    def prop(i, name, kind, value):
        return (f'<SetProperty Id="{i}" ObjectPathId="1" Name="{name}">'
                f'<Parameter Type="{kind}">{escape(str(value))}</Parameter></SetProperty>')

    def add(i, path_id, value):
        return (f'<Method Name="Add" Id="{i}" ObjectPathId="{path_id}"><Parameters>'
                f'<Parameter Type="String">{escape(value)}</Parameter></Parameters></Method>')

    selected = ["Path", "OtsikkoengOWSTEXT", "RefinableString07", "FileExtension", "SecondaryFileExtension"]
    actions = [
        '<ObjectPath Id="10" ObjectPathId="1" />',
        prop(11, "QueryTemplate", "String", QUERY_TEMPLATE),
        prop(12, "QueryText", "String", ""),
        prop(13, "StartRow", "Number", start),
        prop(14, "RowLimit", "Number", PAGE_SIZE),
        prop(15, "RowsPerPage", "Number", PAGE_SIZE),
        prop(16, "TotalRowsExactMinimum", "Number", 100000),
        prop(17, "TrimDuplicates", "Boolean", "false"),
        prop(18, "SourceId", "Guid", SOURCE_ID),
        prop(19, "Culture", "Number", 1033),
        prop(20, "SafeQueryPropertiesTemplateUrl", "String",
             "querygroup://webroot/Pages/default.aspx?groupname=Default"),
        prop(24, "IgnoreSafeQueryPropertiesTemplateUrl", "Boolean", "false"),
        '<ObjectPath Id="21" ObjectPathId="3" />',
        add(22, 3, REFINEMENT),
        '<ObjectPath Id="23" ObjectPathId="4" />',
        *[add(30 + n, 4, name) for n, name in enumerate(selected)],
        '<ObjectPath Id="40" ObjectPathId="5" />',
        '<Method Name="Add" Id="41" ObjectPathId="5"><Parameters>'
        '<Parameter Type="String">Title</Parameter><Parameter Type="Number">0</Parameter>'
        '</Parameters></Method>',
        '<ObjectPath Id="50" ObjectPathId="6" />',
        '<Method Name="ExecuteQueries" Id="51" ObjectPathId="6"><Parameters>'
        '<Parameter Type="Array"><Object Type="String">Default</Object></Parameter>'
        '<Parameter Type="Array"><Object ObjectPathId="1" /></Parameter>'
        '<Parameter Type="Boolean">true</Parameter></Parameters></Method>',
    ]
    paths = (
        '<Constructor Id="1" TypeId="{80173281-fffd-47b6-9a49-312e06ff8428}" />'
        '<Property Id="3" ParentId="1" Name="RefinementFilters" />'
        '<Property Id="4" ParentId="1" Name="SelectProperties" />'
        '<Property Id="5" ParentId="1" Name="SortList" />'
        '<Constructor Id="6" TypeId="{8d2ac302-db2f-46fe-9015-872b35f15098}" />'
    )
    return ('<Request xmlns="http://schemas.microsoft.com/sharepoint/clientquery/2009" SchemaVersion="15.0.0.0" '
            'LibraryVersion="16.0.0.0" ApplicationName="Javascript Library">'
            f'<Actions>{"".join(actions)}</Actions><ObjectPaths>{paths}</ObjectPaths></Request>')


def find_results(node):
    if isinstance(node, dict):
        if "ResultTables" in node:
            return node
        node = list(node.values())
    if isinstance(node, list):
        for item in node:
            found = find_results(item)
            if found:
                return found
    return None


class Client:
    def __init__(self, delay):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def call(self, method, url, **kw):
        for attempt in range(5):
            try:
                resp = self.session.request(method, url, timeout=60, **kw)
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    time.sleep(self.delay)
                    return resp
                error = f"HTTP {resp.status_code}"
            except requests.RequestException as exc:
                error = str(exc)
            time.sleep(self.delay + 2 ** attempt)
        raise RuntimeError(f"{method} {url} failed after 5 attempts: {error}")

    def digest(self):
        html = self.call("GET", PAGE).text
        found = re.search(r'id="__REQUESTDIGEST"[^>]*value="([^"]+)"', html)
        if not found:  # anonymous pages currently carry the literal value "noDigest"
            sys.exit("Could not find the search digest on the FINAS page; the site may have changed.")
        return found.group(1)

    def listing(self):
        token = self.digest()
        rows, total, start = [], None, 0
        while True:
            resp = self.call("POST", ENDPOINT, data=build_request(start).encode("utf-8"), headers={
                "Content-Type": "text/xml", "X-RequestDigest": token, "X-Requested-With": "XMLHttpRequest"})
            payload = resp.json()
            error = payload[0].get("ErrorInfo") if payload else None
            if error:
                sys.exit(f"Search failed: {error.get('ErrorMessage')}")
            table = find_results(payload)["ResultTables"][0]
            total = table["TotalRows"]
            batch = table["ResultRows"]
            if not batch:
                break
            rows.extend(batch)
            start += len(batch)
            if start >= total:
                break
        unique = {row["Path"]: row for row in rows}
        if total is None or len(unique) != total:
            sys.exit(f"Listing incomplete: site reports {total}, received {len(unique)} unique rows.")
        return list(unique.values())


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def pdf_pages(path):
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


def spaceless(text):
    return re.sub(r"[^a-z0-9äöå]", "", text.lower())


def parse_address(text, company):
    found = re.search(r"(\d{5})\s*([A-ZÄÖÅ][A-Za-zÄÖÅäöå-]+)", text)
    if not found:
        return ""
    city = re.sub(r"(Suomi|Https?|Www).*$", "", found.group(2), flags=re.I).strip()
    lines = [clean(l) for l in text[:found.start()].split("\n") if clean(l)]
    line = re.sub(r"FI-$", "", lines.pop() if lines else "").strip()
    if not line and lines:
        line = lines.pop()
    line = re.sub(r"^S\d{3}\s*", "", line)
    glued = re.match(r"^.*?\b(?:Oy|Ltd)\s*(?=[A-ZÄÖÅ0-9])(.*)$", line)
    if glued and len(spaceless(line[:len(line) - len(glued.group(1))])) > 2:
        line = glued.group(1)
    line = re.sub(r"^(Oy|Ltd)\s+", "", line)
    return f"{clean(line)}, {found.group(1)} {city}".strip(", ")


def parse_record(ident, company, url, pages):
    text = "\n".join(pages)
    flat = clean(text)
    decision = re.search(r"S\d{3}\s*/\s*[AM]\s*\d+\s*/\s*\d{4}", flat)
    decision_no = re.sub(r"\s", "", decision.group(0)) if decision else ""
    if not decision_no:
        decision_no = re.sub(r"[ _]", "/", Path(unquote(urlsplit(url).path)).stem)
    standard = re.search(r"(?:vaatimusstandardi:|Requirement)\s*((?:SFS|ISO|EN|IEC)[^,]{0,25}?17\d{3}[-:\d]*)", flat, re.I)
    date = re.search(r"Päätöspvm:\s*(\d{1,2}\.\d{1,2}\.\d{4})", flat)
    expiry = re.search(r"voimassaolopvm:\s*(\d{1,2}\.\d{1,2}\.\d{4})", flat)
    date = date.group(1) if date else ""
    expiry = expiry.group(1) if expiry else ""
    for value, label in re.findall(r"(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})\s*Päätöksen (päiväys|viimeinen)", flat):
        value = re.sub(r"\s", "", value)
        if label == "päiväys" and not date:
            date = value
        if label == "viimeinen" and not expiry:
            expiry = value
    website = re.search(r"www\.(?!finas)[\w.-]+\.\w+", text, re.I)
    email = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    phone = re.search(r"\+358[\d\s-]{6,}", text)
    business_id = re.search(r"\b\d{7}-\d\b", text)
    scope, scheme = [], ""
    for number, page in enumerate(pages, 1):
        lines = [clean(l) for l in page.split("\n") if clean(l)]
        start = next((i for i, l in enumerate(lines) if HEADINGS.match(l)), 0)
        for line in lines[start:]:
            if NOISE.search(line) or re.match(r"^Akkreditoitu pätevyysalue$", line, re.I):
                continue
            if HEADINGS.match(line):
                scheme = line
                continue
            is_scheme = bool(STD_LINE.search(line)) and len(line) < 140
            if is_scheme:
                scheme = line
            scope.append({"ident": ident, "company": company, "scheme_title": scheme, "scheme_url": url,
                          "published": date, "row_type": "scheme" if is_scheme else "scope_line",
                          "column1": line, "column2": f"page {number}", "comment": ""})
    ms = sorted({re.sub(r"\s+", " ", m) for m in MS_STD.findall(flat)} - {""})
    ms = [m for m in ms if not re.search(r"17021|17065|17024|17011", m)]
    day, month, year = (expiry.split(".") + ["", "", ""])[:3] if expiry else ("", "", "")
    state = "Valid (listed)"
    if year and datetime.date(int(year), int(month), int(day)) < datetime.date.today():
        state = "Listed, expiry passed"
    return {"ident": ident, "url": url, "company": company,
            "accreditation_name": "Certification of management systems (Järjestelmäsertifiointi)",
            "state": state, "standard": clean(standard.group(1)) if standard else "",
            "cvr": business_id.group(0) if business_id else "", "decision_no": decision_no,
            "address": parse_address(text, company), "contact_name": "",
            "phone": phone.group(0).strip() if phone else "", "email": email.group(0) if email else "",
            "website": website.group(0) if website else "", "started": "", "renewed": date, "expires": expiry,
            "scope_entries": len(scope), "ms_standards": ms, "pages": len(pages), "scope": scope,
            "text_by_page": pages}


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: "; ".join(row[c]) if isinstance(row.get(c), list) else row.get(c, "") for c in cols})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="fi_ms_output")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()
    out = Path(args.out)
    (out / "cases").mkdir(parents=True, exist_ok=True)

    client = Client(max(args.delay, 0.5))
    rows = client.listing()
    print(f"{len(rows)} certification body records listed", flush=True)

    cases, excluded, unreadable, documents = [], [], [], []
    for row in sorted(rows, key=lambda r: r["RefinableString07"]):
        ident, url = row["RefinableString07"], row["Path"]
        company = clean(row.get("OtsikkoengOWSTEXT"))
        name = Path(unquote(urlsplit(url).path)).name
        pdf_dir = out / "documents" / ident
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / name
        safe = BASE + quote(urlsplit(url).path)
        data = client.call("GET", safe).content
        if not data.startswith(b"%PDF"):
            sys.exit(f"{ident}: response is not a PDF: {safe}")
        pdf_path.write_bytes(data)
        pages = pdf_pages(pdf_path)
        found = set(ACCRED_STD.findall(re.sub(r"\s", "", "\n".join(pages))))
        if "17021" not in found:
            if not found:
                unreadable.append(ident)
            excluded.append((ident, company, "/".join(sorted(found)) or "no text"))
            pdf_path.unlink()
            pdf_dir.rmdir()
            continue
        case = parse_record(ident, company, url, pages)
        cases.append(case)
        documents.append({"ident": ident, "source_url": url, "file_name": name, "size_bytes": len(data)})
        (out / "cases" / f"{ident}.json").write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")

    (out / "all_cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(out / "bodies.csv", BODY_COLS, cases)
    write_csv(out / "scopes.csv", SCOPE_COLS, [line for case in cases for line in case["scope"]])
    write_csv(out / "addresses.csv", ["ident", "company", "address"], cases)
    write_csv(out / "documents.csv", ["ident", "source_url", "file_name", "size_bytes"], documents)

    print(f"Kept {len(cases)} ISO/IEC 17021 accreditations, excluded {len(excluded)}.")
    for ident, company, standard in excluded:
        print(f"  excluded {ident} {company}: {standard}")
    if unreadable:
        print("Review by hand, no standard readable in PDF text: " + ", ".join(unreadable))


if __name__ == "__main__":
    main()
