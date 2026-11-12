# SANAS (South Africa)

Source: SANAS register of accredited CABs, https://www.sanas.co.za/Pages/index.aspx (Accredited Organisations → Certification Bodies), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/south-africa/scrape_za_sanas.py` (browser-side SharePoint REST + pdf.js, as the site is not reachable from the build host), converted with `database/south-africa/prepare_certifind.py`; every skipped scheme is listed in `database/south-africa/sanas_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF that was read.

Extraction rules:
- One SANAS facility number (C01a, C59e, …) is one accreditation for one scheme. `issue_date` is the initial accreditation date, `expiry_date` the register expiry date.
- Address, phone and e-mail from the "Legal Entity (Published)" list; country from the province field (South Africa unless a foreign country is given). `registration_no` is the lowest base facility number of the body. Websites are not published.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Scope schedules list IAF codes (used as EA codes), ISO 22003-1 categories (mapped to EA) or IAF MD 8 technical areas (mapped to EA); ISO 3834, ISO/IEC 27001 and ISO 50001 schedules have no sector breakdown.
- Not imported: HACCP, SANS 1395-1 RTMS, RBI/RIMAP, ISO 55001, ISO/IEC 17065, 17024, 14065 accreditations and withdrawn facilities.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_za_sanas.py | 150 registrations, 110 scope PDFs |
| 2026-11-10 | prepare_certifind.py | 32 bodies, 97 accreditations, 97 scope rows |
