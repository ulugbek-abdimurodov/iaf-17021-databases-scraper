# IARM (North Macedonia)

Source: register of the Institute for Accreditation of the Republic of North Macedonia
(Институт за акредитација на Република Северна Македонија), category "Certification bodies
for management systems" on https://iarm.gov.mk (WordPress category `cb_management`; each
body's page is its `source_url`), and the annex to
each body's accreditation certificate (form OB 05-23), in Macedonian and English. Generated
with `database/macedonia/iarm_scraper.py` and `database/macedonia/prepare_certifind.py`.
Not yet verified by a person, so `verified_at` is empty.

Extraction rules:

- One register entry is one IARM certificate (CB-NNN, Macedonian СТ-NNN), accredited to
  ISO/IEC 17021-1. Each section of the annex's detailed scope is one certification standard
  (ISO 9001, ISO 14001, ISO 45001).
- The annex the register page links as current is read. Its sector tables give IAF codes as
  per IAF ID 1:2023, which are the EA codes. When a row's NACE list is narrower than the
  IAF ID 1 sector, the scope note says "Limited scope" and lists the annex's NACE codes
  (same comparison as the BAS dataset).
- The PDF text does not keep the table layout, so the tables are transcribed in
  `prepare_certifind.py` and checked against the annex text on every run.
- Intercert (CB-009): the current annex (dated 05.08.2026) is published stamped "ПРЕДЛОГ"
  (draft) with an unsigned signature block. Its scope is used; the codes it adds over the
  last signed annex (26.11.2025) are named in the scope note. It also narrows EA 17 for
  ISO 14001 / 45001 to NACE 25 except 25.4, 33.11 (the signed annex included NACE 24).
- Names: Latin name from the register (Cyrillic look-alike letters fixed), Macedonian legal
  name in brackets. Address from the current annex header. For Intercert the register page
  still shows the street as Jordan Mijalkov 44/2-10; the annexes since 26.11.2025 say
  Železnička 44/2-10.
- `issue_date` is the first accreditation date, `expiry_date` the certificate's valid-until.
  The register gives no phone or e-mail.
- Not imported: annexes the scraper could not assign to a current body
  (`documents/_unassigned`, including the withdrawn AKRA accreditation of 27.09.2023).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | iarm_scraper.py | 3 active bodies: MQS (CB-005), MKD Sertifikat (CB-006), Intercert (CB-009) |
