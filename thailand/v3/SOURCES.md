# TISI (Thailand)

Source: TISI register of accredited certification bodies, https://center.tisi.go.th/report/certificate?sort=CB, management system certification bodies (ISO/IEC 17021-1 / TIS 17021-1-2559). Scraped with `database/thailand/scrape_th_tisi.py`, converted with `database/thailand/prepare_certifind.py`; every skipped scheme is listed in `database/thailand/tisi_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` and `proof_url` are the register page.

Extraction rules:
- One TISI accreditation number (QMS 002, EMS 005, EnMS 004…) is one accreditation. `issue_date` / `expiry_date` are the scope validity "from"/"to" dates on the English detail page; Buddhist-era years converted.
- Address, phone, e-mail from the English detail page; body names translated to English legal names. All bodies are in Thailand.
- Accreditation standard per scheme: ISO 50001 → ISO 50003; QMS/EMS/OHS → ISO/IEC 17021-1.
- Scope annexes are scanned PDFs; no EA codes extracted (ea_codes empty).
- Not imported: SFMS, GHG, TLS, product, personnel, tourist schemes; superseded TUV NORD registrations.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_th_tisi.py | 23 MS registrations, 0 scope PDFs parsed |
| 2026-11-09 | prepare_certifind.py | 8 bodies, 20 accreditations, 20 scope rows |
