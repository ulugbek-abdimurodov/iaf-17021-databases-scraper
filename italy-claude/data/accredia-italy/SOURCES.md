# ACCREDIA (Italy)

Source: ACCREDIA register of accredited bodies, https://services.accredia.it/ppsearch/accredia_orgmask.jsp (filter: ISO/IEC 17021-1:2015), management system certification bodies. Scraped with `database/italy/scrape_it_accredia.py` (run in-browser; raw snapshot `database/italy/accredia_raw.json`), converted with `database/italy/prepare_certifind.py`; every skipped scheme and body is listed in `database/italy/accredia_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register search; `proof_url` is the body's register detail page that was read.

Extraction rules:
- One ACCREDIA registration (e.g. 00407, 01879) is one accreditation under ISO/IEC 17021-1. `issue_date` is the register "Date", `expiry_date` is the annex "Expiredate".
- Country is taken from the end of the register address (bodies outside Italy: Bosnia and Herzegovina, India, Israel, Kosovo, Liechtenstein, Switzerland); first email only.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Scope text is on the register page: "(IAF Sectors: …)" used directly as EA; ISO 22000 "Categories" via ISO 22003-1; ISO 50001 numeric technical areas (ISO 50003:2021) mapped to the letter areas; ISO 13485 via IAF MD 8 main areas; NACE via division mapping.
- Not imported: ISO 37001, 39001, 21001, 20121, 28000, 55001, 37301, 19443, 42001, 29001, EN 9100/9110/9120, 7101, 56001, 21401, UNI/PdR and national schemes; 20 bodies holding only such schemes.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_it_accredia.py | 122 registrations, 122 register detail pages |
| 2026-11-10 | prepare_certifind.py | 102 bodies, 200 accreditations, 332 scope rows |
