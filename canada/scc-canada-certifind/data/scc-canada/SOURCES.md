# SCC (Canada)

Source: SCC register of accredited organizations, https://scc-ccn.ca/search/accredited-organizations?f[0]=program:496, Management Systems program (ISO/IEC 17021-1). Scraped with `database/canada/scrape_ca_scc.py`, converted with `database/canada/prepare_certifind.py`; every skipped scheme is listed in `database/canada/scc_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register profile; `proof_url` is the Scope of Accreditation PDF.

Extraction rules:
- One SCC file number (8002–8091) is one accreditation under ISO/IEC 17021-1. `issue_date` is "Initial Accreditation Date", `expiry_date` is "Expires on".
- Country, address, website, phone and email from the profile "Contact Data" (email decoded from Cloudflare obfuscation). Bodies in all countries are included.
- Schemes from "MS Program Specialty Areas": QMS→ISO 9001, EMS→ISO 14001, OH&SMS→ISO 45001, MDMS→ISO 13485, ISMS→ISO/IEC 27001, PIMS→ISO/IEC 27701, EnMS→ISO 50001, BCMS→ISO 22301, ITSMS→ISO/IEC 20000-1. Accreditation standard per scheme as in the other datasets (27001/27701 → ISO/IEC 27006, 50001 → ISO 50003, 22301 → ISO/IEC 17021-6, 20000-1 → ISO/IEC 20000-6).
- Deliberately not added: CyberSecure Canada, ISO/IEC 42001 (AIMS), AS9100 (AQMS), ISO 37001 (ABMS), Sustainable Forestry.
- `ea_codes` empty: scope PDFs were not parsed in this run.
