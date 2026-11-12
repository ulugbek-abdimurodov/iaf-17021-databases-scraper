# SADCAS (SADC — multi-economy)

Source: SADCAS register of accredited management system certification bodies, https://www.sadcas.org/accredited-organisations/management-bodies (ISO/IEC 17021-1). Scraped with `database/sadc/scrape_sadc_sadcas.py`, converted with `database/sadc/prepare_certifind.py`; every skipped scheme is listed in `database/sadc/sadcas_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the Cert & SoA PDF that was read.

Extraction rules:
- One SADCAS accreditation number (QMS-CERT 001, EMS-CERT 002, …) is one accreditation; the prefix gives the scheme (QMS→ISO 9001, EMS→ISO 14001, OHS→ISO 45001, FSMS→ISO 22000, ISMS→ISO/IEC 27001). `issue_date` is the register "Approved Date", `expiry_date` the "Expiration Date".
- Country, address, phone and e-mail from "Permanent Address of Facility" / contact block on page 1 of the schedule; `registration_no` is the body's first listed accreditation number.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Annexure A lists IAF/EA codes directly ("IAF CODE DESCRIPTION"); FSMS schedules list ISO 22003-1 categories, mapped to EA.
- Not imported: HACCP certification (2 accreditations).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_sadc_sadcas.py | 18 registrations, 18 scope PDFs |
| 2026-11-09 | prepare_certifind.py | 7 bodies, 16 accreditations, 16 scope rows |
