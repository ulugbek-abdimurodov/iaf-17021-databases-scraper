# SAAC (Saudi Arabia)

Source: SAAC register of accredited CABs, https://saac.gov.sa/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Management+Systems+Certificates, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/saudi-arabia/scrape_sa_saac.py`, converted with `database/saudi-arabia/prepare_certifind.py`; review notes in `database/saudi-arabia/saac_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the SAAC body detail page (no scope PDFs are published).

Extraction rules:
- One SAAC registration (N-QMS-00001, N-FSMS-00035, ...) is one accreditation; SAAC numbers are per scheme. `issue_date` is Start date, `expiry_date` is End date.
- Detail page gives email, phone, city (address = city only) and website. All bodies are in Saudi Arabia.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Scope tables: QMS/EMS/OHS "IAF Code" column used directly as EA codes; ISO 22000 food categories mapped via ISO 22003-1; ISO 13485 "Main Technical Areas" mapped via IAF MD 8. ISO 50001/27001/22301 publish no areas.
- Not imported: nothing (only MS schemes listed under this service type).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_sa_saac.py | 124 registrations, 0 scope PDFs (HTML scope tables) |
| 2026-11-09 | prepare_certifind.py | 35 bodies, 124 accreditations, 124 scope rows |
