# SAE (Ecuador)

Source: SAE (Servicio de Acreditación Ecuatoriano) public register of accredited conformity assessment bodies, https://sistema.acreditacion.gob.ec/accreditations/scopes-public, area CERTIFICACIÓN, management system activities (ISO/IEC 17021-1). Data read from the register's JSON endpoints (`/accreditations/get-oec/<activity>` and `/qualityMng/updateInformations/scopes_active`). Scraped with `database/ecuador/scrape_ec_sae.py`, converted with `database/ecuador/prepare_certifind.py`; every skipped scheme is listed in `database/ecuador/sae_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the latest signed accreditation resolution PDF (register page when none is published).

Extraction rules:
- One SAE accreditation number (SAE CSC 09-002, SAE CSA 18-001, SAE CSIA 10-003, SAE CSDM 23-001, SAE CSST 26-001) is one accreditation. `issue_date` is the initial accreditation date (`acc_init_date`, else last resolution date); SAE publishes no expiry date, so `expiry_date` is empty.
- Body contact data (phone, email, web, address, city, country) from the organization record; country translated to English. Bodies are not limited to Ecuador (Colombia, Mexico, India, Peru also present).
- EA codes: QMS/EMS/OH&S scopes list IAF sectors directly. ISO 22000 / FSSC 22000 food chain categories mapped via ISO 22003-1 → EA; ISO 13485 technical areas (IAF MD 8) mapped via the common MD8 table.
- Accreditation standard per scheme as in the other datasets: ISO 22000 / FSSC 22000 → ISO 22003-1 (certificate suffix " (22000)"), others → ISO/IEC 17021-1.
- Not included: ISO 37001 anti-bribery, HACCP (Codex), persons (ISO/IEC 17024) and product (ISO/IEC 17065) certification. No body holds ISO 50001 accreditation.
