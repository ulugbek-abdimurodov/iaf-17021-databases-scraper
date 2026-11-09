# PCA (Poland)

Source: PCA (Polskie Centrum Akredytacji, Polish Centre for Accreditation) register of
management-system certification bodies,
https://www.pca.gov.pl/en/accredited-organizations/accredited-organizations/management-systems-certification-bodies,
each body's page (contacts, validity, listed schemes) and its current "Zakres akredytacji"
(scope-of-accreditation annex, PDF). Scraped with `database/poland/pca_scraper.py`, converted
with `database/poland/prepare_certifind.py`; every skipped scheme, merge and limited scope is
listed in `database/poland/pca_review.md`. Not yet verified by a person, so `verified_at` is
empty. `source_url` / `proof_url` are the PCA register pages.

Extraction rules:

- PCA gives each body one accreditation number (AC xxx) with one validity, covering all its
  schemes. CertiFind keeps one accreditation per body and accreditation standard, so the AC
  number is split per accreditation standard: ISO 9001 / 14001 / 45001 / 13485 / 3834 /
  15378 under ISO/IEC 17021-1 (plain number); ISO 22000 and FSSC 22000 → ISO 22003-1,
  ISO 50001 → ISO 50003, ISO/IEC 27001 → ISO/IEC 27006, ISO 22301 → ISO/IEC 17021-6,
  ISO 37001 → ISO/IEC 17021-9. Those rows carry a suffix (`AC 014 (22000)`). Every row has
  the AC number's dates.
- `issue_date` is the date of the current accreditation certificate named in the annex
  ("Certyfikatu Akredytacji Nr … z dnia"); `expiry_date` is the register's validity date,
  which matches the end of the annex's accreditation cycle for every body.
- Sectors come from each annex's IAF code column (ISO 9001 / 14001 / 45001). PCA prints a
  standard NACE column per IAF code, in two editions (the newer moves NACE 74.2 from EA 35
  to EA 34); a row whose NACE column matches neither is a limited scope and its NACE codes
  are given in the scope note (10 rows: AC 058, 072, 092, 111, 116, 146, 155, 183, 187).
- ISO 22003-1 food chain categories (ISO 22000, FSSC 22000), ISO 50003 technical areas and
  IAF MD 8 main technical areas (ISO 13485) are classified to EA with the ESYD tables.
- ISO/IEC 27001, 22301, 37001, ISO 3834 and ISO 15378 have no sector list in the annex and
  are recorded for all EA sectors.
- Partial suspension: AC 014 (Polski Rejestr Statków) FSSC 22000 category B (BIII) is
  suspended at the body's request from 2026-08-18 to 2027-02-17. PCA marks it only in bold
  italic, so it was read from the PDF by hand (`SUSPENDED_PARTS`); category B is left out
  of that row. AC 215's partial suspension ended 2026-06-16 and its scope is imported in full.
- Not imported: PEFC PL 1003 forest management (AC 078, 081, 162; SGS Polska AC 162 holds
  only PEFC, so it is not in the dataset), EU directive / regulation notified-body
  activities (2014/68/EU pressure equipment, 2014/33/EU lifts, 2006/42/EC machinery,
  (EU) 2019/945 unmanned aircraft; Instytut Lotnictwa AC 237 and INTERCERT Global AC 258
  hold only these, so they are not in the dataset) and GB/T 19001 (AC 215).
- All bodies listed are currently valid; none is withdrawn, suspended or expired.
- Names: the register's name of the accredited organization (the legal entity), not of its
  certification unit (e.g. Polski Rejestr Statków S.A., not its "Biuro Certyfikacji Systemów
  Zarządzania"). All bodies are in Poland.
- Contacts: the register's phone (else mobile) with +48, email, website with https:// when
  no scheme is given; address of the certification unit.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | pca_scraper.py | 41 bodies, 41 annexes |
| 2026-11-04 | prepare_certifind.py + prune_inactive.py | 38 bodies, 72 accreditations, 121 scope rows (2,425 EA scopes) |
