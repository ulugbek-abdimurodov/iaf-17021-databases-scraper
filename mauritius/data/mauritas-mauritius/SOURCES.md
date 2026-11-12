# MAURITAS (Mauritius)

Source: MAURITAS register of accredited entities, https://www.mauritas.org/entities.php, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/mauritius/scrape_mu_mauritas.py`, converted with `database/mauritius/prepare_certifind.py`; every skipped scheme is listed in `database/mauritius/mauritas_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF that was read.

Extraction rules:
- One MAURITAS registration (CB001) is one accreditation under ISO/IEC 17021-1. `issue_date` is the certificate Issue Date, `expiry_date` is the schedule Expiry Date.
- Address, phone and e-mail from the schedule header; website from the register row.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- QMS schedule lists IAF ID1 sectors with "Except NACE code" remarks (kept in scope_note); FSMS lists ISO 22003-1 category C subcategories; ISMS has no sector table, so ISO/IEC 27001 is recorded for all EA sectors 1-39.
- Not imported: HACCP scheme; laboratory and calibration accreditations.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_mu_mauritas.py | 1 registration, 1 scope PDF |
| 2026-11-10 | prepare_certifind.py | 1 bodies, 3 accreditations, 3 scope rows |
