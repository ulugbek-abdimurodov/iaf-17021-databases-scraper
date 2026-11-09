# OLAS (Luxembourg)

Source: OLAS register on portail-qualite.public.lu (organismes accrédités, ISO/IEC 17021-1):
each body's page, accreditation certificate and technical annex. Scraped with
`database/luxembourg/olas_17021_scraper.py`, converted with
`database/luxembourg/prepare_certifind.py`; notes in `database/luxembourg/olas_review.md`.
Not yet verified by a person, so `verified_at` is empty.

Extraction rules:

- The certificate number is read from the annex and matches the certificate PDF
  (Certi-Trust Europe 4/005, ESCEM 6/001). The register's listing gives different numbers
  (6/005, 4/007, taken from the page URLs) and is not used for them.
- `issue_date` is the register's accreditation date, `expiry_date` the annex's "Valide jusqu'au".
  ESCEM's certificate says 27 January 2029, its annex and register page 22 January 2029; the
  annex date is used.
- Sectors: the IAF codes listed under each "Domaine général" (ISO 9001 / 14001 / 45001).
  ISO/IEC 27001 has no sector list and is recorded for all EA sectors (accreditation row
  ISO/IEC 27006, `4/005 (27006)`).
- Not imported: the Luxembourg PSDC scheme (ILNAS 106, digitisation / archiving) and ESCEM's
  EU 2018/858 automotive type-approval audits.
- Contacts: the contact person's phone and email in the annex; no website is published.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | olas_17021_scraper.py | 2 bodies |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 2 bodies, 3 accreditations, 4 scope rows |
