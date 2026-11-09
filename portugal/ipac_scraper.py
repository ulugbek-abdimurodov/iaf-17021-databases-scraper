#!/usr/bin/env python3
"""Download IPAC's (Portugal) accredited-body register, with each body's scope.

Default scope: management system certification bodies (ISO/IEC 17021-1).
Needs Python 3.8+ and nothing else.

    python ipac_scraper.py                      # management system bodies
    python ipac_scraper.py --scheme 17065       # any scheme, matched on its name
    python ipac_scraper.py --scheme all         # all ~870 bodies, every scheme
    python ipac_scraper.py --no-profiles        # register list only, no profile pages
    python ipac_scraper.py --offline            # re-parse the pages saved by a previous run

Output (in ./ipac_data by default):
    bodies.csv / bodies.json   one row per body
    sites.csv                  one row per accredited site (address, phone, e-mail)
    scope.csv                  one row per accredited scope line (IAF sector, extent...)
    notes.csv                  accreditation notes per site
    pages.csv                  one row per profile page, with status and SHA-256
    raw/ScopeIPAC2.xml         the site's unmodified register
    raw/profiles/<id>.html     the site's unmodified profile pages

Where the data comes from:
    The register is the XML behind https://www.ipac.pt/pesquisa/acredita.asp grid
    (scheme, accreditation no, acronym, e-mail, scope summary). Each body's profile
    page (ficha_*.asp) holds the current scope, dates, sites and notes.

    The current technical annexes are PDFs that IPAC only releases with a per-body
    access code (https://www.ipac.pt/docsig), so they are not downloaded. The
    public docs/anexos/<id>A.pdf files exist for a few bodies only and date from
    2005-2006; the profile page is the up-to-date version of the same scope.

The profile pages are tuned for management system bodies (ficha_ocf.asp). Other
schemes use other page layouts: their general data, sites and notes are parsed the
same way, and their scope rows are kept as raw cells.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

REGISTER_URL = "https://www.ipac.pt/docs/2partyEA/ScopeIPAC2.xml"
USER_AGENT = "Mozilla/5.0 (compatible; ipac-register-scraper/1.0)"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RETRY_STATUS = {429, 500, 502, 503, 504}
HEADING_BG = "#D8D7BE"  # background of the section titles on the profile pages

GENERAL_FIELDS = {
    "acreditação": "accreditation_no_page",
    "referencial": "standard",
    "entidade": "legal_name",
    "sigla": "acronym",
    "data de concessão": "granted",
    "certificado em vigor": "certificate_date",
    "certificado válido até": "certificate_valid_until",
    "anexo técnico em vigor": "annex_date",
    "contacto": "contact",
}
SITE_FIELDS = {
    "endereço": "address",
    "distrito": "district",
    "telefone": "phone",
    "fax": "fax",
    "e-mail": "email",
}


def one_line(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def clean_cell(text):
    """Collapse whitespace but keep the <br> line breaks as newlines."""
    lines = (one_line(line) for line in (text or "").split("\n"))
    return "\n".join(line for line in lines if line)


def slug(text, max_len=50):
    """Make a name that is safe on Windows, macOS and Linux."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")
    return cleaned[:max_len].rstrip("_") or "organismo"


class RowParser(HTMLParser):
    """Flatten a profile page into its innermost table rows.

    The pages are 1990s-style nested tables with unclosed tags, so each table
    tracks its own open row, and a row that contains a table is only a wrapper:
    its inner rows are kept instead.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)  # also decodes the &#73;&#65;&#70; obfuscation
        self.rows = []
        self.tables = []

    def _new_row(self):
        return {"cells": [], "text": None, "nested": False, "bg": ""}

    @staticmethod
    def _close_cell(row):
        if row["text"] is not None:
            row["cells"].append(clean_cell("".join(row["text"])))
            row["text"] = None

    def _close_row(self, table):
        row = table["row"]
        if row is None:
            return
        self._close_cell(row)
        if not row["nested"] and any(row["cells"]):
            self.rows.append({"cells": row["cells"], "bg": row["bg"]})
        table["row"] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.tables and self.tables[-1]["row"]:
                self.tables[-1]["row"]["nested"] = True
            self.tables.append({"row": None})
        elif not self.tables:
            return
        elif tag == "tr":
            self._close_row(self.tables[-1])
            self.tables[-1]["row"] = self._new_row()
        elif tag in ("td", "th"):
            table = self.tables[-1]
            if table["row"] is None:
                table["row"] = self._new_row()
            row = table["row"]
            self._close_cell(row)
            row["text"] = []
            if not row["cells"]:
                row["bg"] = (dict(attrs).get("bgcolor") or "").upper()
        elif tag == "br":
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if not self.tables:
            return
        if tag == "table":
            self._close_row(self.tables.pop())
        elif tag == "tr":
            self._close_row(self.tables[-1])
        elif tag in ("td", "th") and self.tables[-1]["row"]:
            self._close_cell(self.tables[-1]["row"])

    def handle_data(self, data):
        if self.tables and self.tables[-1]["row"] and self.tables[-1]["row"]["text"] is not None:
            self.tables[-1]["row"]["text"].append(data)


def parse_scope_line(cells):
    """Split 'IAF 28 - Construção' | '(completo)' into code, sector and extent."""
    first = one_line(cells[0])
    match = re.match(r"^(IAF\s*\d{1,2}|[A-Z]{1,2}\d{0,2}|\d{1,2})\s*-\s*(.+)$", first)
    code, description = (one_line(match.group(1)), match.group(2)) if match else ("", first)
    iaf = re.match(r"IAF\s*(\d+)", code)
    extent = " | ".join(one_line(c) for c in cells[1:] if one_line(c))
    return {
        "code": code,
        "iaf_code": int(iaf.group(1)) if iaf else "",
        "description": description,
        "extent": extent.strip("()") if re.fullmatch(r"\([^()]*\)", extent) else extent,
    }


def standard_from_group(group):
    """'Sistemas de Gestão Ambiental ISO 14001' -> 'ISO 14001'."""
    found = re.findall(r"\b((?:ISO/IEC|ISO|NP EN|NP|EN)\s*\d+(?:-\d+)?)", group)
    return found[-1] if found else ""


def parse_profile(page):
    """Return (general info, sites, scope lines, notes) from a profile page."""
    parser = RowParser()
    parser.feed(page)
    parser.close()

    info, other, sites, scope, notes = {}, {}, [], [], []
    section, site_label, group = "", "", ""
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) == 1 and row["bg"] == HEADING_BG:
            heading = one_line(cells[0])
            low = heading.lower()
            group = ""
            if low.startswith("informação geral"):
                section = "general"
            elif low.startswith("locais"):
                section = "sites"
            elif low.startswith("notas"):
                section = "notes"
            elif low.startswith(("âmbito", "extensão do âmbito")):
                section = "scope"
                match = re.search(r"Local:\s*(.*?)(?:\s+Anexo técnico em vigor:|\s+Tipo de|$)", heading)
                site_label = match.group(1).strip() if match else ""
                annex = re.search(r"Anexo técnico em vigor:\s*([\d-]+)", heading)
                if annex and site_label:
                    for site in sites:
                        if site_label in site.get("address", ""):
                            site["annex_date"] = annex.group(1)
            else:
                section = heading
            continue

        if section == "scope":
            text = one_line(cells[0])
            if len(cells) == 1 and text.startswith("[") and text.endswith("]"):
                group = text[1:-1].strip()
            elif len(cells) == 1 and text.startswith("(") and text.endswith(")"):
                continue  # "(descrição de acordo com o DRC006)": wording note, not a scope line
            else:
                scope.append({"site": site_label, "group": group,
                              "standard": standard_from_group(group),
                              **parse_scope_line(cells), "cells": cells})
        elif section == "notes" and len(cells) >= 2:
            if [one_line(c).lower() for c in cells[:2]] == ["local", "notas"]:
                continue
            for text in re.split(r"\n(?=\d+\.\s)", cells[1]):
                if one_line(text):
                    notes.append({"site": one_line(cells[0]), "text": one_line(text)})
        elif len(cells) == 2:
            key, value = one_line(cells[0]), cells[1]
            low = key.lower()
            if section == "sites" and low in SITE_FIELDS:
                if low == "endereço" or not sites:
                    sites.append({})
                value = ", ".join(value.split("\n")) if low == "endereço" else one_line(value)
                sites[-1][SITE_FIELDS[low]] = value
            elif low in GENERAL_FIELDS:
                info[GENERAL_FIELDS[low]] = one_line(value)
            elif key:
                other[key] = one_line(value)
    if other:
        info["other"] = other
    return info, sites, scope, notes


def parse_register(raw):
    """Read the grid XML: scheme, accreditation no + profile link, acronym, mail, summary."""
    root = ET.fromstring(raw)
    bodies = []
    for row in root.iter("row"):
        cells = [(c.text or "").strip() for c in row.findall("cell")]
        cells += [""] * (5 - len(cells))
        number, _, rest = cells[1].partition("^")
        url = rest.split("^")[0].replace("http://", "https://")
        mail = EMAIL_RE.search(cells[3])
        bodies.append({
            "accreditation_no": number.strip(),
            "acronym": cells[2],
            "scheme": one_line(cells[0]),
            "email": mail.group(0) if mail else "",
            "scope_summary": [s.strip() for s in cells[4].split(";") if s.strip()],
            "profile_url": url,
        })
    return bodies


def make_context(insecure):
    context = ssl.create_default_context()
    # www.ipac.pt only offers old SHA-1 CBC cipher suites, which OpenSSL 3 refuses
    # at its default security level 2 (the server then resets the connection).
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def fetch(url, context, timeout=90, retries=3, delay=2.0):
    """Return the response body, retrying temporary failures."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code not in RETRY_STATUS or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries:
                raise
        time.sleep(delay * attempt)
    raise RuntimeError("unreachable")


def save(path, data):
    """Write through a .part file so an interrupted run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def load_profiles(bodies, out, context, delay, offline):
    """Fetch (or re-read) every profile page and parse it into the body record."""
    rows = []
    for n, body in enumerate(bodies, 1):
        number = body["accreditation_no"]
        target = out / "raw" / "profiles" / f"{number}.html"
        row = {"accreditation_no": number, "acronym": body["acronym"], "url": body["profile_url"],
               "local_path": target.relative_to(out).as_posix(),
               "size_bytes": "", "sha256": "", "status": "", "note": ""}
        rows.append(row)
        try:
            if offline:
                if not target.exists():
                    raise FileNotFoundError("no saved page, run once without --offline")
                data, row["status"] = target.read_bytes(), "saved copy"
            else:
                data = fetch(body["profile_url"], context)
                save(target, data)
                row["status"] = "downloaded"
                time.sleep(delay)
        except (urllib.error.URLError, OSError) as err:
            row["status"] = f"FAILED: {err}"
            print(f"[{n}/{len(bodies)}] {number}  FAILED: {err}", file=sys.stderr)
            continue

        row["size_bytes"] = len(data)
        row["sha256"] = hashlib.sha256(data).hexdigest()
        info, sites, scope, notes = parse_profile(data.decode("cp1252", errors="replace"))
        if info.get("accreditation_no_page", number) != number:
            row["note"] = f"page shows {info['accreditation_no_page']}"
        elif not info:
            row["note"] = "no data found on the page"
        body.update(info)
        body.update(sites=sites, scope=scope, notes=notes)
        print(f"[{n}/{len(bodies)}] {number:<7}{body['acronym'][:30]:<32}"
              f"{len(sites)} site(s), {len(scope)} scope lines  {row['note']}")
    return rows


def write_csv(path, rows, fields):
    # utf-8-sig lets Excel display accented characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Scrape IPAC's register of accredited bodies.")
    parser.add_argument("--scheme", default="17021",
                        help="part of the scheme name: 17021 (default, management systems), 17065, "
                             "17024, 15189, EMAS, 17029, Sectorial, Testing, Calibration, Vehicles, "
                             "or 'all'")
    parser.add_argument("--out", default="ipac_data", help="output folder")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between page downloads")
    parser.add_argument("--no-profiles", action="store_true", help="register list only")
    parser.add_argument("--offline", action="store_true",
                        help="parse the files saved in <out>/raw instead of downloading")
    parser.add_argument("--register-url", default=REGISTER_URL, help=argparse.SUPPRESS)
    parser.add_argument("--insecure", action="store_true",
                        help="skip TLS certificate checks, only if Python rejects the site's certificate")
    args = parser.parse_args()

    context = make_context(args.insecure)
    out = Path(args.out)
    register_path = out / "raw" / "ScopeIPAC2.xml"

    if args.offline:
        if not register_path.exists():
            sys.exit(f"{register_path} not found; run once without --offline.")
        raw = register_path.read_bytes()
    else:
        try:
            raw = fetch(args.register_url, context)
        except (urllib.error.URLError, OSError) as err:
            sys.exit(f"Could not reach the IPAC register: {err}")
        save(register_path, raw)

    records = parse_register(raw)
    bodies = records
    if args.scheme.lower() != "all":
        bodies = [b for b in records if args.scheme.lower() in b["scheme"].lower()]
    if not bodies:
        schemes = sorted({b["scheme"] for b in records})
        sys.exit(f"No bodies found for scheme '{args.scheme}'. Schemes:\n  " + "\n  ".join(schemes))
    print(f"{len(bodies)} bodies out of {len(records)} in the register\n")

    pages = [] if args.no_profiles else load_profiles(bodies, out, context, args.delay, args.offline)

    with open(out / "bodies.json", "w", encoding="utf-8") as handle:
        json.dump(bodies, handle, ensure_ascii=False, indent=2)

    def first_site(body, key):
        return body.get("sites", [{}])[0].get(key, "") if body.get("sites") else ""

    fields = ["accreditation_no", "acronym", "legal_name", "scheme", "standard", "granted",
              "certificate_date", "certificate_valid_until", "annex_date", "contact", "email",
              "phone", "address", "district", "sites_count", "scope_lines", "scope_summary",
              "profile_url"]
    write_csv(out / "bodies.csv",
              [{**b,
                "email": first_site(b, "email") or b["email"],
                "phone": first_site(b, "phone"),
                "address": first_site(b, "address"),
                "district": first_site(b, "district"),
                "sites_count": len(b.get("sites", [])),
                "scope_lines": len(b.get("scope", [])),
                "scope_summary": " | ".join(b["scope_summary"])} for b in bodies],
              fields)

    if args.no_profiles:
        print(f"Register saved in {out.resolve()} (profile pages skipped)")
        return 0

    write_csv(out / "sites.csv",
              [{"accreditation_no": b["accreditation_no"], "acronym": b["acronym"], **s}
               for b in bodies for s in b.get("sites", [])],
              ["accreditation_no", "acronym", "address", "district", "phone", "fax", "email",
               "annex_date"])
    write_csv(out / "scope.csv",
              [{"accreditation_no": b["accreditation_no"], "acronym": b["acronym"], **s,
                "cells": " | ".join(one_line(c) for c in s["cells"])}
               for b in bodies for s in b.get("scope", [])],
              ["accreditation_no", "acronym", "site", "standard", "group", "code", "iaf_code",
               "description", "extent", "cells"])
    write_csv(out / "notes.csv",
              [{"accreditation_no": b["accreditation_no"], "acronym": b["acronym"], **note}
               for b in bodies for note in b.get("notes", [])],
              ["accreditation_no", "acronym", "site", "text"])
    write_csv(out / "pages.csv", pages,
              ["accreditation_no", "acronym", "url", "local_path", "size_bytes", "sha256",
               "status", "note"])

    failed = [p for p in pages if p["status"].startswith("FAILED")]
    flagged = [p for p in pages if p["note"]]
    print(f"\n{len(pages) - len(failed)}/{len(pages)} profile pages OK, "
          f"{sum(len(b.get('scope', [])) for b in bodies)} scope lines, saved in {out.resolve()}")
    for page in flagged:
        print(f"Check: {page['accreditation_no']} {page['acronym']}: {page['note']}")
    if failed:
        print(f"{len(failed)} failed; run the script again to retry them.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

