# OUA (Uruguay)

Source: OUA register of accredited management system certification bodies (ISO/IEC 17021-1), https://www.organismouruguayodeacreditacion.org/organismos-de-certificacion-de-sistemas-de-gestion-ocs/. Scraped with `database/uruguay/scrape_uy_oua.py`, converted with `database/uruguay/prepare_certifind.py`; skipped bodies/schemes in `database/uruguay/oua_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF (OUAIMP034) that was read.

Extraction rules:
- OUA issues one registration per scheme (OCSC = quality, OCSGA = environment, OCSST = OHS, OCSGIA = food safety); each is one accreditation. `registration_no` in bodies.csv is the OCSC number. `issue_date`/`expiry_date` are the current accreditation cycle ("Ciclo de acreditación vigente").
- EA codes come from the IAF code table in each scope PDF; "X" marks mapped to the standard column by position. ISO 22000 categories converted to EA via ISO 22003-1 mapping (noted in scope_note).
- Accreditation standard per scheme as in the other datasets: ISO 22000 → ISO 22003-1 (certificate suffix " (22000)").
- All bodies are in Montevideo, Uruguay; phone numbers normalised to +598.
