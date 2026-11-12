# EMA (Mexico)

Source: EMA register of accredited certification bodies, https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion ("Mostrar todos", 670 rows), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/mexico/scrape_mx_ema.py`, converted with `database/mexico/prepare_certifind.py`; every skipped scheme is listed in `database/mexico/ema_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` and `proof_url` are the register page (EMA publishes no scope PDFs in this register).

Extraction rules:
- One EMA accreditation number (e.g. `182/21`, `SGSI-182/26`) is one accreditation; whitespace and trailing dots are stripped. `issue_date` is `fechaInicio`, `expiry_date` is the client record's `fechaFinal` (only where the detail dialog was captured).
- Scheme codes: SGC→ISO 9001, SGA→ISO 14001, SASST/SGSST→ISO 45001, SGSI→ISO/IEC 27001, SGTI→ISO/IEC 20000-1, SGCN→ISO 22301, SGIA→ISO 22000, SGDM→ISO 13485, SGE→ISO 50001.
- Country is Mexico unless the address or the body name shows otherwise (US, Bolivia, Dominican Republic).
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- No EA codes are published; `ea_codes` is empty.
- Not imported: ISO 37001 (SGAS), ISO 37301 (SGCM), ISO 21001 (SGOE), ISO 28000 (SGS), ISO 18788 (SGSP) and other codes (SGSV, SGPG, SGOS, MSAI, SGES, SGPI, SGCD, SGAC, SGBG, SGRH, SMSC); 17065 product, 17024 persons and 17029 validation/verification programmes.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_mx_ema.py | 670 register rows, 476 under ISO/IEC 17021-1, 48 detail records |
| 2026-11-10 | prepare_certifind.py | 101 bodies, 282 accreditations, 347 scope rows |
