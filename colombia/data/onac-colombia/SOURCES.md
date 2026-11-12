# ONAC (Colombia)

Source: ONAC Directorio Oficial de Acreditados (DOA), https://onac.org.co/directorio-de-acreditados/, scheme "Certificación de Sistemas de Gestión (CSG)" (ISO/IEC 17021-1). Scraped with `database/colombia/scrape_co_onac.py` (browser session; snapshot in `onac_raw.tsv`), converted with `database/colombia/prepare_certifind.py`; every skipped scheme is listed in `database/colombia/onac_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope certificate PDF that was read.

Extraction rules:
- One ONAC registration (e.g. 09-CSG-001, 18-CSG-003) is one accreditation under ISO/IEC 17021-1. `issue_date` is "Fecha de publicación del otorgamiento", `expiry_date` is "Fecha de vencimiento de la acreditación".
- Address, phone, first e-mail and website come from the DOA detail page; country from the address (Colombia, plus bodies in India and Venezuela).
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1 (categories mapped to EA). Schemes ONAC lists as "No aplica" for IAF sectors have empty `ea_codes`.
- Not added: NTC 5555, NTC 6001, ISO 18788, ISO 28000/28001, ISO 37001, ISO 39001, ISO 55001.
