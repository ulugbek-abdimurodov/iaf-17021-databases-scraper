#!/usr/bin/env python3
"""
IPAC Management Systems (ISO/IEC 17021-1) Scraper & Scope/Annex Extractor.

Scrapes all Management System Certification Bodies from IPAC's EA portal
(https://www.ipac.pt/docs/2partyEA/IPAC_ScopesFor_EA.htm -> ScopeIPAC2.xml),
fetches their live official accreditation certificate/technical annex fichas
(https://www.ipac.pt/pesquisa/ficha_ocf.asp?ID=...), downloads available
official PDF annexes (https://www.ipac.pt/docs/anexos/{ID}A.pdf) and the
IPAC Master Directory PDF (DirectorioIPAC.pdf), and exports structured JSON
and CSV datasets covering bodies, locations, certificates, technical annexes,
EA/IAF sectors, and scope notes.
"""

import csv
import json
import logging
import re
import subprocess
import time
import unicodedata
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EA_PAGE_URL = "https://www.ipac.pt/docs/2partyEA/IPAC_ScopesFor_EA.htm"
XML_URL = "https://www.ipac.pt/docs/2partyEA/ScopeIPAC2.xml"
FICHA_URL_TMPL = "https://www.ipac.pt/pesquisa/ficha_ocf.asp?ID={body_id}"
ANNEX_URL_TMPL = "https://www.ipac.pt/docs/anexos/{body_id}A.pdf"
DIRECTORIO_PDF_URL = "https://www.ipac.pt/docs/publicdocs/outros/DirectorioIPAC.pdf"

OUTPUT_DIR = Path("ipac_qms_data")
LEGACY_DIR = Path("ipac_management_systems")

# Matches "EA 03", "IAF 28", "Sector EA 14", "IAF 20 - Construção", etc.
EA_IAF_PATTERN = re.compile(
    r"(?:EA|IAF|Sector\s+EA|Sector\s+IAF)\s*[:ºn°\s]*([0-3]?\d)\b(?:\s*[-–:]\s*([^\n\r;]+))?",
    re.I,
)
# Matches numbered EA sector lines inside PDF annexes like "1 - Agricultura..." or "28 – Construção..."
PDF_SECTOR_LINE_PATTERN = re.compile(
    r"^\s*([1-3]?\d)\s*[-–]\s*([A-ZÀ-Ú][^\n\r]+)$"
)
SUSPENSION_PATTERN = re.compile(
    r"(Suspens[ãa]o\s+(?:parcial\s+)?desde\s+\d{4}-\d{2}-\d{2}|\bSuspens[ãa]o\b[^\n\r]*)",
    re.I,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ipac")


def run_curl(url: str, output_path: Path = None) -> bytes:
    """Fetch URL using Windows curl.exe (uses Schannel to avoid OpenSSL/IIS TLS resets)."""
    cmd = [
        "curl.exe",
        "-k",
        "-s",
        "-L",
        "--tlsv1.2",
        "--retry",
        "2",
        "-A",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        url,
    ]
    if output_path:
        cmd += ["-o", str(output_path)]
        subprocess.run(cmd, check=True)
        return b""
    res = subprocess.run(cmd, capture_output=True, check=True)
    return res.stdout


def slug(text: str, limit: int = 50) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")[:limit].rstrip("-") or "unnamed"


def clean_ws(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def extract_standard_code(standard_name: str) -> str:
    """Extract normalized standard identifier (e.g. 'ISO 9001', 'ISO/IEC 27001', 'NP 4552', 'PEFC')."""
    m = re.search(
        r"(ISO(?:/IEC)?\s*\d+(?:-\d+)?|FSSC\s*22000|NP\s*\d+|PEFC)",
        standard_name or "",
        re.I,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).upper()
    if "regulamentar" in (standard_name or "").lower() or "regulatory" in (standard_name or "").lower():
        return "Regulatory Scope"
    return clean_ws(standard_name)


def parse_ficha_html(html_text: str, body_id: str) -> dict:
    """
    Parse IPAC live accreditation record (`ficha_ocf.asp?ID=A00xx`), which holds:
    - General certificate & technical annex information (entity, acronym, dates, contact person)
    - Accredited locations (`Locais abrangidos`)
    - Detailed live technical annex scope (`Âmbito de acreditação` per location & standard)
    - Accreditation notes (`Notas` per location)
    """
    soup = BeautifulSoup(html_text, "html.parser")
    general_info = {}
    locations = []
    current_loc = None
    scopes = []
    notes = []

    section = ""
    scope_location = ""
    current_standard_full = ""
    current_standard_code = ""
    in_notes_table = False

    for tr in soup.find_all("tr"):
        # Skip inner rows of nested width="100%" scope tables (handled via their parent cell)
        parent_tbl = tr.find_parent("table")
        if parent_tbl and parent_tbl.get("width") == "100%":
            continue

        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue

        first_text = clean_ws(tds[0].get_text(" ", strip=True))

        # Single-column banner / section / standard / scope item row
        if len(tds) == 1:
            if "Informação geral" in first_text:
                section = "general"
                continue
            if "Locais abrangidos" in first_text:
                section = "locations"
                continue
            if "Âmbito de acreditação" in first_text:
                section = "scope"
                if "Local:" in first_text:
                    scope_location = clean_ws(first_text.split("Local:", 1)[1])
                else:
                    scope_location = ""
                continue
            if first_text == "Notas":
                section = "notes"
                in_notes_table = True
                continue

            if section == "scope":
                if first_text.startswith("[") and first_text.endswith("]"):
                    current_standard_full = clean_ws(first_text.strip("[]"))
                    current_standard_code = extract_standard_code(current_standard_full)
                    continue

                inner_tbl = tds[0].find("table")
                if inner_tbl:
                    inner_tds = [clean_ws(c.get_text(" ", strip=True)) for c in inner_tbl.find_all("td")]
                    if len(inner_tds) >= 2:
                        left_col, right_col = inner_tds[0], inner_tds[1]
                        if left_col.startswith("(descrição de acordo"):
                            continue

                        status = "Active"
                        suspension_note = ""
                        susp_m = SUSPENSION_PATTERN.search(left_col) or SUSPENSION_PATTERN.search(right_col)
                        if susp_m:
                            status = "Suspended"
                            suspension_note = clean_ws(susp_m.group(0))
                            left_col = clean_ws(SUSPENSION_PATTERN.sub("", left_col))

                        ea_code = ""
                        iaf_code = ""
                        sector_code = ""
                        sector_desc = left_col

                        iaf_m = re.match(r"^(?:IAF|EA)\s*(\d+)\s*[-–:]\s*(.+)$", left_col, re.I)
                        if iaf_m:
                            num = int(iaf_m.group(1))
                            ea_code = f"EA {num:02d}"
                            iaf_code = f"IAF {num:02d}"
                            sector_code = iaf_code
                            sector_desc = clean_ws(iaf_m.group(2))
                        else:
                            cat_m = re.match(r"^([A-Z]{1,5}|\d+)\s*[-–]\s*(.+)$", left_col)
                            if cat_m:
                                sector_code = cat_m.group(1).strip()
                                sector_desc = clean_ws(cat_m.group(2))

                        scopes.append({
                            "certificationNumber": body_id,
                            "location": scope_location,
                            "standard_full": current_standard_full,
                            "standard": current_standard_code,
                            "sector_code": sector_code,
                            "ea_code": ea_code,
                            "iaf_code": iaf_code,
                            "sector_description": sector_desc,
                            "extent": right_col,
                            "status": status,
                            "suspension_info": suspension_note,
                            "source": "live_ficha",
                        })

        # Two-column key-value row
        elif len(tds) >= 2:
            key = clean_ws(tds[0].get_text(" ", strip=True))
            val = clean_ws(tds[1].get_text(" ", strip=True))

            if section == "general":
                key_low = key.lower()
                if "acreditação" in key_low:
                    general_info["accreditation_id"] = val
                elif "referencial" in key_low:
                    general_info["accreditation_standard"] = val
                elif "entidade" in key_low:
                    general_info["full_entity_name"] = val
                elif "sigla" in key_low:
                    general_info["acronym"] = val
                elif "concessão" in key_low:
                    general_info["concession_date"] = val
                elif "certificado em vigor" in key_low:
                    general_info["certificate_in_force_date"] = val
                elif "anexo técnico em vigor" in key_low:
                    general_info["technical_annex_in_force_date"] = val
                elif "contacto" in key_low:
                    general_info["contact_person"] = val

            elif section == "locations":
                key_low = key.lower()
                if "endereço" in key_low or "morada" in key_low:
                    if current_loc:
                        locations.append(current_loc)
                    # Extract postal code / city line if separated by <br>
                    raw_lines = [clean_ws(x) for x in tds[1].get_text("\n", strip=True).splitlines() if clean_ws(x)]
                    postal_locality = raw_lines[-1] if len(raw_lines) > 1 else ""
                    current_loc = {
                        "certificationNumber": body_id,
                        "address": val,
                        "postal_locality": postal_locality,
                        "district": "",
                        "telephone": "",
                        "fax": "",
                        "email": "",
                    }
                elif current_loc is not None:
                    if "distrito" in key_low:
                        current_loc["district"] = val
                    elif "telefone" in key_low:
                        current_loc["telephone"] = val
                    elif "fax" in key_low:
                        current_loc["fax"] = val
                    elif "e-mail" in key_low or "email" in key_low:
                        current_loc["email"] = val

            elif section == "notes" and in_notes_table:
                if key.lower() == "local" and val.lower() == "notas":
                    continue
                note_lines = [clean_ws(x) for x in tds[1].get_text("\n", strip=True).splitlines() if clean_ws(x)]
                if note_lines:
                    for nl in note_lines:
                        notes.append({
                            "certificationNumber": body_id,
                            "location": key,
                            "note": nl,
                        })

    if current_loc:
        locations.append(current_loc)

    return {
        "general_info": general_info,
        "locations": locations,
        "scopes": scopes,
        "notes": notes,
    }


def download_and_validate_pdf(url: str, dest_path: Path, force: bool = False) -> bool:
    if dest_path.exists() and not force and dest_path.stat().st_size > 2000:
        with open(dest_path, "rb") as f:
            if f.read(4).startswith(b"%PDF"):
                return True

    log.info("  --> Probing PDF: %s", url)
    try:
        run_curl(url, dest_path)
    except Exception as exc:
        log.warning("  [!] curl failed for %s: %s", url, exc)
        return False

    is_valid = False
    if dest_path.exists() and dest_path.stat().st_size > 2500:
        with open(dest_path, "rb") as f:
            if f.read(10).startswith(b"%PDF"):
                is_valid = True

    if not is_valid and dest_path.exists():
        try:
            dest_path.unlink()
        except Exception:
            pass
        return False

    return is_valid


def parse_annex_pdf(pdf_path: Path, folder: Path, body_id: str):
    """Extract raw tables, text, and EA/IAF sector mappings from historical/published PDF annexes."""
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber required: pip install pdfplumber")
        return {}, [], []

    info = {"page_count": 0}
    raw_tables = []
    ea_records = []
    full_text = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            info["page_count"] = len(pdf.pages)
            current_standard = "ISO 9001"

            for page_no, page in enumerate(pdf.pages, 1):
                p_text = page.extract_text() or ""
                full_text.append(f"--- Page {page_no} ---\n{p_text}")

                # Detect edition date if present
                ed_match = re.search(r"Edi[çc][ãa]o\s*n\.?[º°]?\s*(\d+)\s*\((\d{4}-\d{2}-\d{2})\)", p_text, re.I)
                if ed_match and "edition" not in info:
                    info["edition"] = ed_match.group(1)
                    info["edition_date"] = ed_match.group(2)

                # Detect active standard
                std_match = re.search(r"(ISO\s*(?:9001|14001|45001|22000|50001|27001)|NP\s*4552|NP\s*4406|PEFC)", p_text, re.I)
                if std_match:
                    current_standard = re.sub(r"\s+", " ", std_match.group(1)).upper()

                # Strategy A: Scan tables
                tables = page.extract_tables()
                for table_idx, table in enumerate(tables, 1):
                    for row_idx, cells in enumerate(table, 1):
                        cleaned = [clean_ws(c) for c in cells]
                        if not any(cleaned):
                            continue

                        raw_tables.append({
                            "certificationNumber": body_id,
                            "page": page_no,
                            "table": table_idx,
                            "row": row_idx,
                            "cells": cleaned,
                        })

                        # Check first cell for "1 - Agricultura..." or "EA 01"
                        first_cell = cleaned[0] if cleaned else ""
                        num_m = PDF_SECTOR_LINE_PATTERN.match(first_cell)
                        if num_m:
                            code_num = int(num_m.group(1))
                            if 1 <= code_num <= 39:
                                desc = clean_ws(num_m.group(2))
                                extent = " ; ".join(c for c in cleaned[1:] if c)
                                ea_records.append({
                                    "certificationNumber": body_id,
                                    "ea_code": f"EA {code_num:02d}",
                                    "iaf_code": f"IAF {code_num:02d}",
                                    "standard": current_standard,
                                    "sector_description": desc,
                                    "extent": extent or "(completo)",
                                    "page": page_no,
                                    "source": "pdf_annex",
                                })

                # Strategy B: Scan text lines for numbered EA sectors or explicit EA/IAF mentions
                for line in p_text.splitlines():
                    line_clean = clean_ws(line)
                    num_m = PDF_SECTOR_LINE_PATTERN.match(line_clean)
                    if num_m:
                        code_num = int(num_m.group(1))
                        if 1 <= code_num <= 39:
                            desc = clean_ws(num_m.group(2))
                            ea_records.append({
                                "certificationNumber": body_id,
                                "ea_code": f"EA {code_num:02d}",
                                "iaf_code": f"IAF {code_num:02d}",
                                "standard": current_standard,
                                "sector_description": desc,
                                "extent": "(Sector EA completo)",
                                "page": page_no,
                                "source": "pdf_annex",
                            })
                            continue

                    for match in EA_IAF_PATTERN.finditer(line_clean):
                        code_num = int(match.group(1))
                        if 1 <= code_num <= 39:
                            desc = clean_ws(match.group(2) or line_clean.split(match.group(0))[-1])
                            if desc.lower().startswith("completo") or len(desc) < 3:
                                continue
                            ea_records.append({
                                "certificationNumber": body_id,
                                "ea_code": f"EA {code_num:02d}",
                                "iaf_code": f"IAF {code_num:02d}",
                                "standard": current_standard,
                                "sector_description": desc.strip(" -–|:;\t"),
                                "extent": "(Sector EA completo)",
                                "page": page_no,
                                "source": "pdf_annex",
                            })

            (folder / "annex.txt").write_text("\n\n".join(full_text), encoding="utf-8")

        # Deduplicate PDF EA records
        seen_keys = set()
        deduped = []
        for r in ea_records:
            k = (r["certificationNumber"], r["ea_code"], r["standard"])
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(r)
        ea_records = deduped

        if raw_tables:
            max_w = max(len(r["cells"]) for r in raw_tables)
            cols = [f"col{i + 1}" for i in range(max_w)]
            flat = [
                {
                    "certificationNumber": r["certificationNumber"],
                    "page": r["page"],
                    "table": r["table"],
                    "row": r["row"],
                    **dict(zip(cols, r["cells"])),
                }
                for r in raw_tables
            ]
            write_csv(folder / "annex_tables.csv", flat, ["certificationNumber", "page", "table", "row", *cols])

        return info, raw_tables, ea_records

    except Exception as exc:
        log.warning("%s: Failed to parse %s: %s", body_id, pdf_path.name, exc)
        return info, [], []


def get_ipac_bodies():
    """Download IPAC_ScopesFor_EA.htm and ScopeIPAC2.xml and extract all ISO/IEC 17021-1 bodies."""
    log.info("Downloading EA scope portal page: %s", EA_PAGE_URL)
    try:
        ea_html = run_curl(EA_PAGE_URL)
        Path("scopes.html").write_bytes(ea_html)
    except Exception as exc:
        log.warning("Could not refresh scopes.html: %s", exc)

    log.info("Downloading grid XML via curl: %s", XML_URL)
    raw_bytes = run_curl(XML_URL)
    Path("ScopeIPAC2.xml").write_bytes(raw_bytes)
    raw_xml = raw_bytes.decode("latin-1", errors="replace")
    soup = BeautifulSoup(raw_xml, "html.parser")

    bodies = []
    seen = set()

    for row in soup.find_all("row"):
        cells = [c.get_text(strip=True) for c in row.find_all("cell")]
        if not cells:
            continue

        scheme = clean_ws(cells[0])
        # Capture Management Systems Certification (ISO/IEC 17021-1)
        if "17021" not in scheme and "Management Systems" not in scheme:
            continue

        body_id = None
        detail_url = ""
        body_name = ""
        email = ""
        standards = ""

        if len(cells) >= 2:
            parts = cells[1].split("^")
            m = re.search(r"\b(A\d{4,5})\b", parts[0])
            if m:
                body_id = m.group(1)
                if len(parts) > 1:
                    detail_url = parts[1].replace("http://www.ipac.pt", "https://www.ipac.pt")

        if not body_id or body_id in seen:
            continue

        if len(cells) >= 3:
            body_name = clean_ws(cells[2])

        if len(cells) >= 4 and "mailto:" in cells[3]:
            m_mail = re.search(r"mailto:([^\";\s]+)", cells[3])
            if m_mail:
                email = m_mail.group(1)

        if len(cells) >= 5:
            standards = clean_ws(cells[4])

        seen.add(body_id)
        bodies.append({
            "certificationNumber": body_id,
            "name": body_name or body_id,
            "scheme": scheme,
            "standard": "ISO/IEC 17021-1",
            "email": email,
            "detail_page": detail_url or FICHA_URL_TMPL.format(body_id=body_id),
            "standards_summary": standards,
        })

    return sorted(bodies, key=lambda x: x["certificationNumber"])


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)

    # Download IPAC Master Directory PDF (DirectorioIPAC.pdf)
    directorio_path = OUTPUT_DIR / "DirectorioIPAC.pdf"
    download_and_validate_pdf(DIRECTORIO_PDF_URL, directorio_path)

    bodies = get_ipac_bodies()
    log.info("Found %d Management System Certification Bodies.", len(bodies))

    records = []
    all_locations = []
    all_scopes = []
    all_ea_sectors = []
    all_notes = []
    all_raw_tables = []

    for idx, body in enumerate(bodies, 1):
        num = body["certificationNumber"]
        folder_name = f"{num}_{slug(body['name'])}"
        folder = OUTPUT_DIR / "bodies" / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        log.info("[%d/%d] Processing %s (%s)", idx, len(bodies), num, body["name"])

        # 1. Fetch live HTML ficha (Certificate & Technical Annex in force)
        ficha_data = {"general_info": {}, "locations": [], "scopes": [], "notes": []}
        ficha_html_path = folder / f"{num}_ficha.html"
        try:
            raw_ficha = run_curl(body["detail_page"])
            ficha_html_path.write_bytes(raw_ficha)
            profile_html = raw_ficha.decode("latin-1", errors="replace")
            ficha_data = parse_ficha_html(profile_html, num)
            log.info(
                "  --> Parsed live ficha: %d locations, %d scope items, %d notes (Annex in force: %s)",
                len(ficha_data["locations"]),
                len(ficha_data["scopes"]),
                len(ficha_data["notes"]),
                ficha_data["general_info"].get("technical_annex_in_force_date", "N/A"),
            )
        except Exception as exc:
            log.warning("  Could not fetch/parse profile HTML for %s: %s", num, exc)

        # 2. Download and validate static PDF Annex (if hosted on IPAC server)
        annex_url = ANNEX_URL_TMPL.format(body_id=num)
        target_pdf = folder / f"{num}.pdf"
        is_pdf_valid = download_and_validate_pdf(annex_url, target_pdf)

        # 3. Parse PDF Annex if available
        pdf_meta, raw_tbls, pdf_ea_recs = {}, [], []
        if is_pdf_valid:
            pdf_meta, raw_tbls, pdf_ea_recs = parse_annex_pdf(target_pdf, folder, num)
            log.info(
                "  --> Parsed PDF annex (%d pages, %d EA records)",
                pdf_meta.get("page_count", 0),
                len(pdf_ea_recs),
            )

        # 4. Build unified EA/IAF sector records (preferring live ficha, falling back/supplementing with PDF)
        body_ea_sectors = [
            {
                "certificationNumber": s["certificationNumber"],
                "location": s["location"],
                "ea_code": s["ea_code"],
                "iaf_code": s["iaf_code"],
                "standard": s["standard"],
                "standard_full": s["standard_full"],
                "sector_description": s["sector_description"],
                "extent": s["extent"],
                "status": s["status"],
                "suspension_info": s["suspension_info"],
                "source": s["source"],
            }
            for s in ficha_data["scopes"]
            if s["ea_code"] or s["iaf_code"]
        ]

        # Save per-body CSVs
        if ficha_data["locations"]:
            write_csv(
                folder / "locations.csv",
                ficha_data["locations"],
                ["certificationNumber", "address", "postal_locality", "district", "telephone", "fax", "email"],
            )
        if ficha_data["scopes"]:
            write_csv(
                folder / "scopes.csv",
                ficha_data["scopes"],
                [
                    "certificationNumber",
                    "location",
                    "standard",
                    "standard_full",
                    "sector_code",
                    "ea_code",
                    "iaf_code",
                    "sector_description",
                    "extent",
                    "status",
                    "suspension_info",
                    "source",
                ],
            )
        if body_ea_sectors:
            write_csv(
                folder / "ea_sectors.csv",
                body_ea_sectors,
                [
                    "certificationNumber",
                    "location",
                    "ea_code",
                    "iaf_code",
                    "standard",
                    "standard_full",
                    "sector_description",
                    "extent",
                    "status",
                    "suspension_info",
                    "source",
                ],
            )
        if ficha_data["notes"]:
            write_csv(folder / "notes.csv", ficha_data["notes"], ["certificationNumber", "location", "note"])

        all_locations.extend(ficha_data["locations"])
        all_scopes.extend(ficha_data["scopes"])
        all_ea_sectors.extend(body_ea_sectors)
        all_notes.extend(ficha_data["notes"])
        all_raw_tables.extend(raw_tbls)

        # Primary contact details
        primary_loc = ficha_data["locations"][0] if ficha_data["locations"] else {}
        gen = ficha_data["general_info"]

        contact_details = {
            "contact_person": gen.get("contact_person", ""),
            "email": body["email"] or primary_loc.get("email", ""),
            "telephone": primary_loc.get("telephone", ""),
            "fax": primary_loc.get("fax", ""),
            "address": primary_loc.get("address", ""),
            "postal_locality": primary_loc.get("postal_locality", ""),
            "district": primary_loc.get("district", ""),
        }

        standards_list = [s.strip() for s in body["standards_summary"].split(";") if s.strip()]
        active_scopes_count = sum(1 for s in ficha_data["scopes"] if s["status"] == "Active")
        suspended_scopes_count = sum(1 for s in ficha_data["scopes"] if s["status"] == "Suspended")

        record = {
            **body,
            "full_entity_name": gen.get("full_entity_name", body["name"]),
            "acronym": gen.get("acronym", body["name"]),
            "accreditation_standard": gen.get("accreditation_standard", "ISO/IEC 17021-1:2015"),
            "concession_date": gen.get("concession_date", ""),
            "certificate_in_force_date": gen.get("certificate_in_force_date", ""),
            "technical_annex_in_force_date": gen.get("technical_annex_in_force_date", ""),
            "contact_details": contact_details,
            "locations": ficha_data["locations"],
            "standards_list": standards_list,
            "scope_counts": {
                "total_scope_items": len(ficha_data["scopes"]),
                "active_scope_items": active_scopes_count,
                "suspended_scope_items": suspended_scopes_count,
                "ea_iaf_sector_items": len(body_ea_sectors),
            },
            "notes": ficha_data["notes"],
            "ficha_html_file": str(ficha_html_path.relative_to(OUTPUT_DIR)),
            "annex_pdf_url": annex_url if is_pdf_valid else "",
            "pdf_available": is_pdf_valid,
            "pdf_details": pdf_meta,
        }
        records.append(record)
        write_json(folder / "info.json", record)
        time.sleep(0.2)

    # Export Master JSON and CSV files
    write_json(OUTPUT_DIR / "bodies.json", records)

    summary_rows = [
        {
            "certificationNumber": r["certificationNumber"],
            "name": r["name"],
            "full_entity_name": r["full_entity_name"],
            "acronym": r["acronym"],
            "accreditation_standard": r["accreditation_standard"],
            "concession_date": r["concession_date"],
            "certificate_in_force_date": r["certificate_in_force_date"],
            "technical_annex_in_force_date": r["technical_annex_in_force_date"],
            "contact_person": r["contact_details"].get("contact_person", ""),
            "email": r["contact_details"].get("email", ""),
            "telephone": r["contact_details"].get("telephone", ""),
            "fax": r["contact_details"].get("fax", ""),
            "address": r["contact_details"].get("address", ""),
            "postal_locality": r["contact_details"].get("postal_locality", ""),
            "district": r["contact_details"].get("district", ""),
            "locations_count": len(r["locations"]),
            "total_scope_items": r["scope_counts"]["total_scope_items"],
            "active_scope_items": r["scope_counts"]["active_scope_items"],
            "suspended_scope_items": r["scope_counts"]["suspended_scope_items"],
            "detail_page": r["detail_page"],
            "standards_summary": r["standards_summary"],
            "pdf_available": r["pdf_available"],
            "pdf_page_count": r["pdf_details"].get("page_count", 0),
            "annex_pdf_url": r["annex_pdf_url"],
        }
        for r in records
    ]
    bodies_fieldnames = [
        "certificationNumber",
        "name",
        "full_entity_name",
        "acronym",
        "accreditation_standard",
        "concession_date",
        "certificate_in_force_date",
        "technical_annex_in_force_date",
        "contact_person",
        "email",
        "telephone",
        "fax",
        "address",
        "postal_locality",
        "district",
        "locations_count",
        "total_scope_items",
        "active_scope_items",
        "suspended_scope_items",
        "detail_page",
        "standards_summary",
        "pdf_available",
        "pdf_page_count",
        "annex_pdf_url",
    ]
    write_csv(OUTPUT_DIR / "bodies.csv", summary_rows, bodies_fieldnames)
    write_csv(LEGACY_DIR / "certification_bodies.csv", summary_rows, bodies_fieldnames)

    write_csv(
        OUTPUT_DIR / "locations.csv",
        all_locations,
        ["certificationNumber", "address", "postal_locality", "district", "telephone", "fax", "email"],
    )

    scope_summary_rows = [
        {
            "certificationNumber": r["certificationNumber"],
            "name": r["name"],
            "full_entity_name": r["full_entity_name"],
            "standard": extract_standard_code(sc),
            "standard_description": sc,
        }
        for r in records
        for sc in r["standards_list"]
    ]
    write_csv(
        OUTPUT_DIR / "scope.csv",
        scope_summary_rows,
        ["certificationNumber", "name", "full_entity_name", "standard", "standard_description"],
    )

    if all_scopes:
        write_csv(
            OUTPUT_DIR / "detailed_scopes.csv",
            all_scopes,
            [
                "certificationNumber",
                "location",
                "standard",
                "standard_full",
                "sector_code",
                "ea_code",
                "iaf_code",
                "sector_description",
                "extent",
                "status",
                "suspension_info",
                "source",
            ],
        )

    if all_ea_sectors:
        write_csv(
            OUTPUT_DIR / "ea_sectors.csv",
            all_ea_sectors,
            [
                "certificationNumber",
                "location",
                "ea_code",
                "iaf_code",
                "standard",
                "standard_full",
                "sector_description",
                "extent",
                "status",
                "suspension_info",
                "source",
            ],
        )

    if all_notes:
        write_csv(OUTPUT_DIR / "notes.csv", all_notes, ["certificationNumber", "location", "note"])

    if all_raw_tables:
        max_w = max(len(r["cells"]) for r in all_raw_tables)
        cols = [f"col{i + 1}" for i in range(max_w)]
        flat_all = [
            {
                "certificationNumber": r["certificationNumber"],
                "page": r["page"],
                "table": r["table"],
                "row": r["row"],
                **dict(zip(cols, r["cells"])),
            }
            for r in all_raw_tables
        ]
        write_csv(
            OUTPUT_DIR / "annex_tables.csv",
            flat_all,
            ["certificationNumber", "page", "table", "row", *cols],
        )

    log.info(
        "[✓] Completed. Saved %d bodies, %d locations, %d detailed scope items (%d EA/IAF sector records), and %d notes in '%s'.",
        len(records),
        len(all_locations),
        len(all_scopes),
        len(all_ea_sectors),
        len(all_notes),
        OUTPUT_DIR.resolve(),
    )


if __name__ == "__main__":
    main()
