# ANAB (United States)

Source: ANAB directory of accredited management systems certification bodies, https://anabdirectory.remoteauditor.com/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/usa/scrape_us_anab.py`, converted with `database/usa/prepare_certifind.py`; every skipped scheme is listed in `database/usa/anab_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the directory; `proof_url` is the ANAB scope-of-accreditation PDF (anab.jadian.com) that was read.

Extraction rules:
- One ANAB accreditation ID (MS-4126, MS-7266, …) is one accreditation under ISO/IEC 17021-1. `issue_date` is "Accredited since", `expiry_date` is "Accreditation expires" from the scope PDF.
- Country is the directory "Country" field; phone, email and website from the directory; address from the scope PDF header (company name and country stripped).
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- ISO 9001/14001/45001 EA codes come straight from the ANAB Rule 20/21/30 sector lists (sub-codes such as 07a/17b collapsed to the parent). ISO 13485 main technical areas (Rule 35) and ISO 22003-1 food chain categories (Rules 22/23) are converted to EA via the shared mapping tables.
- Not imported: AS91xx, AS6081, TL 9000, RC14001, ISO 15378, ISO 55001, ISO 37001, ISO 37301, ISO 28000, ISO/IEC 42001, SFI, ATFS, R2, RIOS, BA 9000, SN 9001, FAMI-QS, Leading Harvest; 8 bodies holding only these.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_us_anab.py | 113 registrations, 113 scope PDFs |
| 2026-11-10 | prepare_certifind.py | 105 bodies, 174 accreditations, 298 scope rows |
