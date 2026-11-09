# BELAC (Belgium)

Source: BELAC public list of accredited management system certification bodies (QMS),
https://weblist.economie.fgov.be/en/belac/list/qms: each body's record (contacts, validity,
structured scope) and its annex PDF. Scraped with `database/belgium/belac_qms_scraper.py`,
converted with `database/belgium/prepare_certifind.py`; every skipped scheme is listed in
`database/belgium/belac_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` is the body's register page; `proof_url` is the certificate + annex PDF.

Extraction rules:

- One certification number (e.g. 019-QMS) is one accreditation under EN ISO/IEC 17021-1:2015.
  `issue_date` / `expiry_date` are the validity period of the current annex version.
- Sectors come from the register's structured scope (field × keyword): IAF codes for ISO 9001
  and ISO 45001; ISO 50003 technical areas for ISO 50001; ISO 22003-1 categories for ISO 22000
  and FSSC 22000; IAF MD 8 main technical areas for ISO 13485 — the last three classified to EA
  with the ESYD tables. ISO/IEC 27001 has no sector list and is recorded for all EA sectors.
  Restrictions written in the annex (e.g. IAF 7 "limited to paper products") are not kept.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 → ISO/IEC 27006,
  ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1 (suffixed rows such as
  `019-QMS (27006)`).
- BELAC's QMS list has no ISO 14001 accreditations.
- Not imported: national schemes (VCA, VCU, CO2 prestatieladder, Food Autocontrol System, Feed
  Chain Alliance, SHE asbestos / soil remediation) and EU directive activities. Four bodies hold
  only such schemes (COPRO, HaCeCo, Normec BTV Audit, APAVE Belgium) and are left out.
- Contacts: the register's first phone number (put in international form) and first email.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | belac_qms_scraper.py | 17 bodies, 381 scope rows |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 13 bodies, 24 accreditations, 28 scope rows |
