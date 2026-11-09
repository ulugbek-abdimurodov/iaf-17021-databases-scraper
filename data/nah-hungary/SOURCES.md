# NAH (Hungary)

Source: NAH (Nemzeti Akkreditáló Hatóság, National Accreditation Authority) register of
management-system certification bodies, https://nah.gov.hu/hu/kategoriak, each body's page
(contacts, validity) and its current "Részletező Okirat" (scope-of-accreditation annex, PDF).
Scraped with `database/hungary/nah_scraper.py`, converted with
`database/hungary/prepare_certifind.py`; every merge, skipped scheme and fallback is listed
in `database/hungary/nah_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` / `proof_url` are the NAH register pages.

Extraction rules:

- One NAH registration number (NAH-4-xxxx/yyyy) is one accredited status with its own
  validity; a body often holds several. CertiFind keeps one accreditation per body and
  accreditation standard, so a body's statuses are merged per accreditation standard, as in
  the NABCB dataset: the row takes the number of the status carrying ISO 9001 (else 14001,
  else 45001), the earliest start and the latest expiry date; scopes from another status
  name it and its validity in the scope note.
- Accreditation standard per scheme: ISO 9001 / 14001 / 45001 / 13485 / 3834 / 19443 /
  56001 under ISO/IEC 17021-1; ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003,
  ISO 22000 → ISO 22003-1, ISO 37001 → ISO/IEC 17021-9, ISO 22301 → ISO/IEC 17021-6,
  ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO/IEC 42001 → ISO/IEC 42006. Those rows carry a
  suffix (`NAH-4-0047/2023 (50003)`). A body with only such schemes still gets the
  ISO/IEC 17021-1 row search requires, without scopes (VantaSec).
- Sectors come from each annex's IAF code column (ISO 9001 / 14001 / 45001). Annexes with
  no section heading (NAH-4-0073/2022, 0107/2024, 0120/2022) are read as the standard their
  ISO/IEC 17021-2 / -3 part names. The NACE column is not compared with IAF ID 1.
  OMNIA CERTAB's EA 7 is "limited to pulp and paper manufacturing" (scope note).
- ISO 22003-1 food chain categories, ISO 50003 technical areas and IAF MD 8 main technical
  areas (ISO 13485, sections 1.1–1.7) are classified to EA with the ESYD tables.
- ISO/IEC 27001, 37001, 22301, 20000-1, 42001, 19443, 56001 and ISO 3834 have no sector list
  in the annex and are recorded for all EA sectors.
- Not imported: MEES (Hungarian health-care standards; SGS NAH-4-0049/2024 and part of MSZT
  NAH-4-0044/2023), MER forest certification (Control Union NAH-4-0168/2026, so Control
  Union is not in the dataset), ISO/TS 22163 railway (MSZT NAH-4-0148/2025, TAM CERT
  NAH-4-0150/2026), the 2014/68/EU module H activity of Bureau Veritas, and ISO 9001 for
  NEOEMKI NAH-4-0009/2026 (named in the register, but its annex has only the ISO 13485 tables).
- Only bodies that currently hold a valid accreditation are kept. Withdrawn (CERTOP
  NAH-4-0151/2021, MSZT NAH-4-0149/2021, QUALI-CERT NAH-4-0038/2022, SGS NAH-4-0031/2023)
  and suspended (EasyCert NAH-4-0158/2024, so EasyCert is not in the dataset) statuses are
  left out, and so is INTERNATIONAL CERT Hungary's NAH-4-0059/2021 (ISO 9001), listed active
  but expired 2026-10-14.
- Names: the register's name of the legal entity; branch offices are merged into it
  (Bureau Veritas "PED Iroda", DEKRA "Irányítási Rendszer Tanúsító Iroda", TAM CERT
  "Rendszertanúsító hely" / "Kiberbiztonsági Tanúsító hely"). e.com-CERT Rendszertanúsító
  Kft. and e.com-CERT International Certification Bureau Rendszertanúsító Kft. share an
  address but are listed as two bodies, as NAH lists them. Turkmenstandardlary is in
  Turkmenistan; all other bodies in Hungary.
- Contacts: the register's phone (international form), first valid email, website with
  https:// when no scheme is given.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | nah_scraper.py | 65 register entries (60 active) under 38 body names, 145 annexes |
| 2026-11-04 | prepare_certifind.py + prune_inactive.py | 36 bodies, 70 accreditations, 112 scope rows (2,842 EA scopes) |
