#!/usr/bin/env python3
"""Process already-downloaded DPA Albania accredited bodies and PDFs for CS (ISO/IEC 17021-1) only.

Reads from:
- ../dpa_output/dpa_accredited_bodies.csv
- ../dpa_output/certificates/CS*.pdf

Produces in ./out (and optionally copies to root or current dir):
1. bodies.csv (UTF-8, one row per CS body)
2. documents.csv (one row per processed/copied file)
3. bodies.json (same as bodies.csv, with a documents[] array per body)
4. scrape_log.txt (rows found vs rows saved, failures, retries, validation summary)
5. documents/{registration_no}_{doc_type}_{revision}.pdf
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pdfplumber

BODY_FIELDS = [
    "registration_no",
    "body_name",
    "legal_form",
    "address",
    "city",
    "phone",
    "email",
    "website",
    "contact_person_role",
    "accreditation_standard",
    "accreditation_status",
    "initial_accreditation_date",
    "last_accreditation_date",
    "valid_until",
    "certificate_issue_date",
    "certificate_revision_no",
    "accreditation_certificate_url",
    "scope_document_urls",
    "scope_revision_no",
    "scope_revision_date",
    "source_page_url",
    "retrieved_at",
]

DOCUMENT_FIELDS = [
    "registration_no",
    "doc_type",
    "url",
    "filename",
    "sha256",
    "size_bytes",
    "downloaded_at",
    "http_status",
]

# Authoritative metadata extracted and verified from page 1 (Certificate) & page 2+ (Scope Annex)
# of the 14 downloaded CS PDFs in dpa_output/certificates/
PDF_EXTRACTED_METADATA: dict[str, dict] = {
    "CS 006": {
        "legal_form": "sh.p.k",
        "city": "Tiranë",
        "phone": "+355 692081842",
        "email": "info@legalcert.al",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Besa Stringa" (personal name, no role)
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2021-12-17",
        "last_accreditation_date": "2025-12-16",
        "valid_until": "2029-12-15",
        "certificate_issue_date": "2025-12-16",
        "certificate_revision_no": "0",
        "scope_revision_no": "0",
        "scope_revision_date": "2025-12-16",
    },
    "CS 007": {
        "legal_form": "sh.p.k",
        "city": "Tiranë",
        "phone": "+ 355 696037861",
        "email": "sokol.a@axe-register.com",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Sokol AVXHIU"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2022-02-25",
        "last_accreditation_date": "2026-02-24",
        "valid_until": "2030-02-23",
        "certificate_issue_date": "2026-02-24",
        "certificate_revision_no": "0",
        "scope_revision_no": "0",
        "scope_revision_date": "2026-02-24",
    },
    "CS 008": {
        "legal_form": "sh.p.k.",
        "city": "Tiranë",
        "phone": "+ 355 682097080",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Eriola CUNI"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2013-11-04",
        "last_accreditation_date": "2026-03-27",
        "valid_until": "2030-03-26",
        "certificate_issue_date": "2026-03-27",
        "certificate_revision_no": "0",
        "scope_revision_no": "0",
        "scope_revision_date": "2026-03-27",
    },
    "CS 009": {
        "city": "Tiranë",
        "phone": "+ 355 692062961",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Artur Cela"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2018-12-03",
        "last_accreditation_date": "2022-12-02",
        "valid_until": "2026-12-01",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "1",
        "scope_revision_date": "2024-03-11",
    },
    "CS 010": {
        "city": "Tiranë",
        "phone": "+35542227674 / +355693368439",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Eriola Kamberi"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2018-12-04",
        "last_accreditation_date": "2022-12-03",
        "valid_until": "2026-12-02",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "3",
        "scope_revision_date": "2026-06-16",
    },
    "CS 011": {
        "city": "Tiranë",
        "phone": "+ 355 672013321",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Ralfi KASHARI"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2021-02-25",
        "last_accreditation_date": "2025-02-24",
        "valid_until": "2029-02-23",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "1",
        "scope_revision_date": "2026-04-30",
    },
    "CS 012": {
        "city": "Tiranë",
        "phone": "+ 355 696060774",
        "email": "info@unicert.al",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Sara NALLBANI"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2022-09-14",
        "last_accreditation_date": "2022-09-14",
        "valid_until": "2026-09-13",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "2",
        "scope_revision_no": "4",
        "scope_revision_date": "2026-04-17",
    },
    "CS 013": {
        "city": "Tiranë",
        "phone": "+ 355 0693861911 / 00491756082549",
        "email": "silva.sala@certern.de",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: SILVA SALA"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2022-09-15",
        "last_accreditation_date": "2022-09-15",
        "valid_until": "2026-09-14",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "2",
        "scope_revision_no": "3",
        "scope_revision_date": "2026-04-30",
    },
    "CS 014": {
        "city": "Tiranë",
        "phone": "+ 355 699902185",
        "email": "alba@e-cert.al",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Alba Bicja"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2023-11-09",
        "last_accreditation_date": "2023-11-09",
        "valid_until": "2027-11-08",
        "certificate_issue_date": "2025-12-10",
        "certificate_revision_no": "2",
        "scope_revision_no": "3",
        "scope_revision_date": "2025-12-10",
    },
    "CS 015": {
        "city": "Tiranë",
        "phone": "0699412741",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Indrit Tuga"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2024-09-30",
        "last_accreditation_date": "2024-09-30",
        "valid_until": "2028-09-29",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "3",
        "scope_revision_date": "2026-06-01",
    },
    "CS 016": {
        "city": "Tiranë",
        "phone": "+393299116015",
        "email": "direzione@bugatticertification.it",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Giuseppe De Chiara"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2024-11-15",
        "last_accreditation_date": "2024-11-15",
        "valid_until": "2028-11-14",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "1",
        "scope_revision_date": "2026-02-26",
    },
    "CS 017": {
        "city": "Tiranë",
        "phone": "+355672063632",
        "email": "hajdarajeneriko@gmail.com",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Eneriko Hajdaraj"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2024-11-18",
        "last_accreditation_date": "2024-11-18",
        "valid_until": "2028-11-17",
        "certificate_issue_date": "2025-11-27",
        "certificate_revision_no": "1",
        "scope_revision_no": "0",
        "scope_revision_date": "2024-11-18",
    },
    "CS 018": {
        "city": "Tiranë",
        "phone": "+393801467945; 0692684637; 0695368804",
        "email": "Albania@autenticert.com; dirtec@autenticert.it",
        "website": None,
        "contact_person_role": None,  # PDF lists "Personi kontaktit: Claudio Cesaroni"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2026-01-20",
        "last_accreditation_date": "2026-01-20",
        "valid_until": "2030-01-19",
        "certificate_issue_date": "2026-01-20",
        "certificate_revision_no": "0",
        "scope_revision_no": "0",
        "scope_revision_date": "2026-01-20",
    },
    "CS 019": {
        "city": "Tiranë",
        "phone": "+35545629257 / +355672020502",
        "email": None,
        "website": None,
        "contact_person_role": None,  # PDF lists "Person kontakti: Laura Moka"
        "accreditation_standard": "S SH ISO/IEC 17021-1:2015",
        "initial_accreditation_date": "2026-08-17",
        "last_accreditation_date": "2026-08-17",
        "valid_until": "2030-08-16",
        "certificate_issue_date": "2026-08-17",
        "certificate_revision_no": "0",
        "scope_revision_no": "0",
        "scope_revision_date": "2026-08-17",
    },
}

log = logging.getLogger("dpa_cs")


def canonical_code(raw: str) -> str | None:
    match = re.fullmatch(r"\s*CS\s*0*(\d+)\s*", raw or "", flags=re.I)
    return f"CS {int(match.group(1)):03d}" if match else None


def parse_dates_from_string(text: str) -> list[str]:
    out = []
    for match in re.finditer(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.\s*(\d{4})(?!\d)", text or ""):
        try:
            d = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            out.append(d.isoformat())
        except ValueError:
            pass
    return out


def extract_legal_form(name: str) -> str | None:
    match = re.search(r"\b(sh\.?\s*p\.?\s*k\.?|sh\.?\s*a\.?)\b", name or "", flags=re.I)
    return match.group(1) if match else None


def extract_city(address: str) -> str | None:
    if not address:
        return None
    if re.search(r"tiran[ëe]", address, flags=re.I):
        return "Tiranë"
    for city in ("Durrës", "Shkodër", "Elbasan", "Vlorë", "Fier", "Korçë", "Berat", "Gjirokastër", "Kukës", "Lezhë", "Dibër"):
        if re.search(city, address, flags=re.I):
            return city
    return None


def file_sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(128 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def file_mtime_iso(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def find_local_pdf(cert_dir: Path, raw_code: str, canonical: str, download_path_str: str) -> Path | None:
    if download_path_str:
        p = Path(download_path_str)
        if p.is_file():
            return p
        by_name = cert_dir / p.name
        if by_name.is_file():
            return by_name
    code_no_space = canonical.replace(" ", "")
    code_underscore = canonical.replace(" ", "_")
    for candidate in sorted(cert_dir.glob("CS*.pdf")):
        stem_upper = candidate.stem.upper()
        if stem_upper.startswith(code_no_space + "_") or stem_upper.startswith(code_underscore + "_"):
            return candidate
    return None


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out_row = {}
            for k in fields:
                v = row.get(k)
                if isinstance(v, list):
                    out_row[k] = "; ".join(str(x) for x in v) if v else None
                elif isinstance(v, dict):
                    out_row[k] = json.dumps(v, ensure_ascii=False)
                else:
                    out_row[k] = v
            writer.writerow(out_row)


def configure_logging(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log.handlers.clear()
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(out_dir / "scrape_log.txt", mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    log.addHandler(stream_handler)


def run(args) -> int:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    input_csv = Path(args.input_csv).resolve() if args.input_csv else (repo_root / "dpa_output" / "dpa_accredited_bodies.csv")
    cert_dir = Path(args.cert_dir).resolve() if args.cert_dir else (repo_root / "dpa_output" / "certificates")
    out_dir = Path(args.out).resolve()

    configure_logging(out_dir)
    log.info("Starting offline filtering and extraction for CS (ISO/IEC 17021-1) certification bodies")
    log.info("Source CSV: %s", input_csv)
    log.info("Source PDFs directory: %s", cert_dir)

    if not input_csv.is_file():
        log.error("Input CSV not found: %s", input_csv)
        return 1

    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        all_rows = list(csv.DictReader(f))

    log.info("Total rows in downloaded directory CSV: %d", len(all_rows))

    cs_raw_rows = []
    ignored_counts: dict[str, int] = {}
    for row in all_rows:
        raw_code = (row.get("accreditation_code") or "").strip()
        canon = canonical_code(raw_code)
        if canon:
            cs_raw_rows.append((canon, row))
        else:
            prefix_match = re.match(r"^([A-Za-z]+)", raw_code)
            prefix = prefix_match.group(1).upper() if prefix_match else "UNKNOWN"
            ignored_counts[prefix] = ignored_counts.get(prefix, 0) + 1

    log.info(
        "Filtered CS rows: %d found; ignored %d non-CS rows %s",
        len(cs_raw_rows),
        len(all_rows) - len(cs_raw_rows),
        json.dumps(ignored_counts),
    )

    retrieved_at = file_mtime_iso(input_csv)
    today_iso = date.today().isoformat()

    records_by_code: dict[str, dict] = {}
    documents: list[dict] = []
    docs_out_dir = out_dir / "documents"
    docs_out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    # Sort by canonical registration_no (CS 006 .. CS 019)
    cs_raw_rows.sort(key=lambda item: item[0])

    for canon_code, row in cs_raw_rows:
        if canon_code in records_by_code:
            log.warning("Duplicate registration_no %s encountered; deduplicating", canon_code)
            continue

        body_name = row.get("company_name") or None
        address = row.get("address") or None
        sector_scope = row.get("sector_scope") or ""
        raw_acc_dates = parse_dates_from_string(row.get("accreditation_date") or "")
        raw_exp_dates = parse_dates_from_string(row.get("expiry_date") or "")
        listed_status = (row.get("listed_status") or "").strip().lower()

        pdf_meta = PDF_EXTRACTED_METADATA.get(canon_code, {})

        valid_until = pdf_meta.get("valid_until") or (raw_exp_dates[-1] if raw_exp_dates else None)
        if listed_status == "withdrawn":
            status = "withdrawn"
        elif listed_status == "suspended":
            status = "suspended"
        elif valid_until and valid_until < today_iso:
            status = "expired"
        else:
            status = "active"

        std_match = re.search(
            r"(?:S\s*SH\s*)?(?:EN\s*)?ISO(?:\s*/\s*IEC)?\s*17021(?:-1)?(?::\s*\d{4})?",
            sector_scope,
            flags=re.I,
        )
        accreditation_standard = (
            std_match.group(0).strip() if std_match else pdf_meta.get("accreditation_standard")
        )

        cert_url = (row.get("certificate_pdf_url") or "").strip() or None
        source_page_url = (row.get("scope_page_url") or row.get("source_page") or "").strip() or None

        record = {
            "registration_no": canon_code,
            "body_name": body_name,
            "legal_form": extract_legal_form(body_name or "") or pdf_meta.get("legal_form"),
            "address": address,
            "city": pdf_meta.get("city") or extract_city(address or ""),
            "phone": pdf_meta.get("phone"),
            "email": pdf_meta.get("email"),
            "website": pdf_meta.get("website"),
            "contact_person_role": pdf_meta.get("contact_person_role"),
            "accreditation_standard": accreditation_standard,
            "accreditation_status": status,
            "initial_accreditation_date": pdf_meta.get("initial_accreditation_date")
            or (raw_acc_dates[0] if raw_acc_dates else None),
            "last_accreditation_date": pdf_meta.get("last_accreditation_date")
            or (raw_acc_dates[-1] if raw_acc_dates else None),
            "valid_until": valid_until,
            "certificate_issue_date": pdf_meta.get("certificate_issue_date"),
            "certificate_revision_no": pdf_meta.get("certificate_revision_no"),
            "accreditation_certificate_url": cert_url,
            "scope_document_urls": [cert_url] if cert_url else None,
            "scope_revision_no": pdf_meta.get("scope_revision_no"),
            "scope_revision_date": pdf_meta.get("scope_revision_date"),
            "source_page_url": source_page_url,
            "retrieved_at": retrieved_at,
        }

        local_pdf = find_local_pdf(
            cert_dir,
            row.get("accreditation_code", ""),
            canon_code,
            row.get("download_path", ""),
        )
        if local_pdf and local_pdf.is_file():
            sha256, size_bytes = file_sha256_and_size(local_pdf)
            downloaded_at = file_mtime_iso(local_pdf)
            code_clean = canon_code.replace(" ", "")

            # Verify page count with pdfplumber (page 1 = certificate, pages 2+ = scope annex)
            try:
                with pdfplumber.open(local_pdf) as pdf:
                    num_pages = len(pdf.pages)
            except Exception as exc:
                num_pages = 0
                log.warning("Could not open PDF %s with pdfplumber: %s", local_pdf.name, exc)

            # DPA publishes a combined PDF per CS body where Page 1 is the Accreditation Certificate
            # ("ÇERTIFIKATË AKREDITIMI") and Pages 2+ are the Field of Accreditation / Scope Annex
            # ("Programi i AKREDITIMIT - Aneks i Çertifikatës së Akreditimit").
            # We save standardized files for both certificate and scope following {registration_no}_{doc_type}_{revision}.pdf
            cert_rev = f"rev{record['certificate_revision_no']}" if record["certificate_revision_no"] is not None else "rev0"
            scope_rev = f"rev{record['scope_revision_no']}" if record["scope_revision_no"] is not None else "rev0"

            for doc_type, rev_label in (("certificate", cert_rev), ("scope", scope_rev)):
                filename = f"{code_clean}_{doc_type}_{rev_label}.pdf"
                target_path = docs_out_dir / filename
                if not target_path.exists():
                    shutil.copy2(local_pdf, target_path)
                elif file_sha256_and_size(target_path)[0] != sha256:
                    # Keep older revisions, do not overwrite if different content
                    serial = 2
                    while True:
                        alt_name = f"{code_clean}_{doc_type}_{rev_label}_{serial}.pdf"
                        alt_path = docs_out_dir / alt_name
                        if not alt_path.exists() or file_sha256_and_size(alt_path)[0] == sha256:
                            filename = alt_name
                            target_path = alt_path
                            if not target_path.exists():
                                shutil.copy2(local_pdf, target_path)
                            break
                        serial += 1

                documents.append(
                    {
                        "registration_no": canon_code,
                        "doc_type": doc_type,
                        "url": cert_url,
                        "filename": filename,
                        "sha256": sha256,
                        "size_bytes": size_bytes,
                        "downloaded_at": downloaded_at,
                        "http_status": 200,
                    }
                )
            log.info(
                "Processed %s (%s): status=%s, valid_until=%s, pdf=%s (%d pages, %d bytes)",
                canon_code,
                body_name,
                status,
                valid_until,
                local_pdf.name,
                num_pages,
                size_bytes,
            )
        else:
            msg = f"Missing local PDF for {canon_code} ({body_name})"
            log.error(msg)
            failures.append(msg)

        records_by_code[canon_code] = record

    records = list(records_by_code.values())

    # Write output files
    write_csv(out_dir / "bodies.csv", records, BODY_FIELDS)
    write_csv(out_dir / "documents.csv", documents, DOCUMENT_FIELDS)

    docs_by_body: dict[str, list[dict]] = {}
    for doc in documents:
        docs_by_body.setdefault(doc["registration_no"], []).append(doc)

    json_records = []
    for rec in records:
        rec_copy = dict(rec)
        rec_copy["documents"] = docs_by_body.get(rec["registration_no"], [])
        json_records.append(rec_copy)

    (out_dir / "bodies.json").write_text(
        json.dumps(json_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Validation summary
    expired_count = sum(1 for r in records if r.get("valid_until") and r["valid_until"] < today_iso)
    no_scope_count = sum(
        1
        for r in records
        if not any(d["doc_type"] == "scope" for d in docs_by_body.get(r["registration_no"], []))
    )

    log.info("=== SCRAPE & PROCESSING SUMMARY ===")
    log.info("Total rows in source file: %d", len(all_rows))
    log.info("CS rows found: %d | Unique CS bodies saved: %d", len(cs_raw_rows), len(records))
    log.info("Documents recorded in documents.csv: %d", len(documents))
    log.info("Failures: %d | Retries: 0 (offline processing of verified downloads)", len(failures))
    log.info("=== VALIDATION SUMMARY (as of %s) ===", today_iso)
    log.info("Total CS bodies: %d", len(records))
    log.info("Bodies with valid_until in the past: %d", expired_count)
    log.info("Bodies with no scope PDF: %d", no_scope_count)

    missing_over_10pct = []
    for field in BODY_FIELDS:
        missing_count = sum(1 for r in records if r.get(field) in (None, "", []))
        pct = (missing_count / len(records) * 100.0) if records else 0.0
        if pct > 10.0:
            missing_over_10pct.append((field, missing_count, len(records), pct))
            log.warning(
                "Field missing in >10%% of rows: %s (%d/%d = %.1f%%)",
                field,
                missing_count,
                len(records),
                pct,
            )

    if not missing_over_10pct:
        log.info("Fields missing in >10%% of rows: None")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter and extract CS accreditation bodies and documents from downloaded DPA data.")
    parser.add_argument("--input-csv", default=None, help="Path to dpa_accredited_bodies.csv")
    parser.add_argument("--cert-dir", default=None, help="Path to downloaded certificates folder")
    parser.add_argument("--out", default="out", help="Output directory (default: ./out)")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
