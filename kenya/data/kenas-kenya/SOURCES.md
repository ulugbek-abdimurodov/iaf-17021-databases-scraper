# KENAS (Kenya)

Source: KENAS register of accredited CABs, https://kenas.go.ke/status, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/kenya/scrape_ke_kenas.py`, converted with `database/kenya/prepare_certifind.py`; every skipped scheme is listed in `database/kenya/kenas_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the schedule PDF link.

Extraction rules:
- One KENAS registration (KENAS/CB/001, KENAS/Ms.CB/021) is one accreditation under ISO/IEC 17021-1. `issue_date` is not published (empty), `expiry_date` is the card's "Expiry Date/Status".
- Country is Kenya for all bodies; address, phone and email from the register card.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Schedules could not be read in this run; scopes are placeholders (ISO 9001, no EA codes) pending PDF access.
- Not imported: product (ISO/IEC 17065) and personnel (ISO/IEC 17024) certification bodies.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_ke_kenas.py | 7 registrations, 0 scope PDFs |
| 2026-11-09 | prepare_certifind.py | 7 bodies, 7 accreditations, 7 scope rows |
