# KENAS review (2026-11-09)

Register: https://kenas.go.ke/status — 18 certification bodies listed; 7 are "Management System" (ISO/IEC 17021-1) and imported.

Skipped (out of scope):
- 8 product certification bodies (ISO/IEC 17065), e.g. KENAS/CB/20 Bureau Veritas Product Certification.
- 3 personnel certification bodies (ISO/IEC 17024), e.g. KENAS/CB/016 KEBS Persons Certification Body.

Open issues:
- Schedule PDFs (kenas.s3.amazonaws.com, media.kenas.go.ke) were not retrievable (sandbox egress blocked, S3 CORS blocks in-browser fetch). Every body got one placeholder ISO 9001 scope with empty `ea_codes`. Re-run `scrape_ke_kenas.py` with these hosts allowed; `prepare_certifind.py` then parses schemes, IAF/NACE codes and food categories from the PDFs.
- Register schedule hrefs are malformed (several URLs concatenated); the scraper keeps the first `.pdf` URL.
- Websites not in register; to fill from schedule PDFs.
