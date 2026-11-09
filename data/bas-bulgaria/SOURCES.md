# BAS (Bulgaria)

Source: register of the Executive Agency Bulgarian Accreditation Service (ИА БСА / NAB),
field "Certification Bodies - Management Systems",
https://www.nab-bas.bg/en/registers, and the full-scope annex (the accreditation order)
attached to each entry, in Bulgarian and English. Generated with
`database/bulgaria/nab_scraper.py` and `database/bulgaria/prepare_certifind.py`; every
mapping, merge, fallback and cleaned value is listed in
`database/bulgaria/nab_management_system_bodies/REVIEW.md`. Not yet verified by a person,
so `verified_at` is empty.

Extraction rules:

- One register entry is one BAS certificate ("N ОСС"); each numbered section of its annex is
  one certification standard. The accreditation standard is chosen per scheme as in the
  other datasets (27006, 50003, 22003-1, 17021-7 for ISO 39001, 17021-9 for ISO 37001).
- The newest annex is read: of the Bulgarian and English files, the one with the latest
  order date, the Bulgarian one on a tie. The English annexes are often an older order or an
  OCR'd scan. An annex without an order date in its header is taken as issued with the
  current certificate.
- ISO 9001 / 14001 / 45001 tables give IAF codes, which are the EA codes. When a row's NACE
  list is narrower than the IAF ID 1:2023 sector, the scope note says "Limited scope" and
  lists the NACE codes of the annex.
- ISO 50001 tables give the IAF code of each ISO 50003 technical area, used as the EA code.
  ISO 22000 categories (ISO 22003-1 A-K) are classified to EA by sector, as in the RENAR,
  DPA, TÜRKAK and ESYD datasets.
- ISO/IEC 27001, ISO 37001 (granted for the territory of Bulgaria) and ISO 39001 (Annex A 4.1
  activity groups) have no sector list and are recorded as `ALL`.
- Codes BAS marks as critical ("*", granted on condition of a witnessed audit) are kept, with
  a scope note.
- Not imported: PEFC forest management (MG Global) and PAS 24000 / FSSC 24000 social
  management (TÜV NORD), which are not international management-system standards.
- Status from the register: "Отнета акредитация" (revoked) is `WITHDRAWN` and removed (see the last rule);
  (Axerta International).
- Names: the register only has the Cyrillic legal name and a machine translation, and the
  certificates are scans, so the Latin name is curated (English annex, e-mail domain) and the
  Cyrillic legal name follows in brackets.
- `issue_date` is the initial accreditation date, `expiry_date` the certificate's valid-to.
- Contacts: the register office's first phone number and one e-mail (the generic one when
  several are listed); the address from the annex header (office address when given),
  otherwise the office city.
- Only bodies that currently hold a valid accreditation are kept: withdrawn, expired (including an active-listed row whose valid-to date has passed) and suspended bodies and rows are removed by `database/prune_inactive.py`, which the prepare script runs after writing the CSVs.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-03 | nab_scraper.py | 20 register entries; 19 bodies after merging the two 17 ОСС (Q-Aid Europe) entries |
| 2026-11-04 | prune_inactive.py | removed 1 withdrawn body (Axerta International); 18 bodies kept |
