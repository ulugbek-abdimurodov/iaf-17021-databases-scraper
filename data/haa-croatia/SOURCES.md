# HAA (Croatia)

Source: register of the Croatian Accreditation Agency (Hrvatska akreditacijska agencija),
https://akreditacija.gov.hr/frontend/registar-akreditacija, scheme "Certifikacijska tijela
za certifikaciju sustava upravljanja", and the accreditation certificate with its annex
(the register's text copy of each PDF). Generated with `database/croatia/haa_scraper.py`
and `database/croatia/prepare_certifind.py`. Not yet verified by a person, so `verified_at`
is empty. The register has no per-body link (its documents are fetched by POST), so
`source_url` and `proof_url` point at the register page; search it by certificate number.

Extraction rules:

- One register entry is one HAA certificate (the register's certificate number), accredited
  to ISO/IEC 17021-1. Each numbered annex section is one certification standard.
- ISO 9001 / 14001 / 45001 tables give the scope number "based upon IAF ID 1:2023", which
  is the EA code. When a row's NACE list is narrower than the IAF ID 1 sector, the scope
  note says "Limited scope" and lists the annex's NACE codes (same comparison as BAS).
- Every parsed row is checked against IAF ID 1 (each NACE code must fall in its EA
  sector). One exception is kept as written: Bureau Veritas lists NACE 74.9 under EA 35,
  which IAF ID 1 places in EA 34; the scope note says so.
- ISO 13485 (UDEM Adriatic) lists IAF MD 8 main technical areas, classified to EA with the
  ESYD table: non-active devices 13, 14, 17; active (non-implantable) 19; sterilization 35;
  devices incorporating specific substances 13; parts or services 18, 29, 31, 34, 35.
- Not imported: HRB's PED module H (Directive 2014/68/EU), a notified-body directive module
  rather than a management-system standard (as in the ESYD dataset).
- Names: curated from the certificate header and register record (the register repeats the
  legal name or names only the department). Address: the certifying department's address
  from the certificate header; DNV Adriatica and Bureau Veritas Croatia have their seat in
  Rijeka and certify from Zagreb.
- `issue_date` is the initial accreditation date, `expiry_date` the register's expiry date.
  Phone from the register record (written +385 with the area code), no e-mail in the
  register. CRO CERT's register phone has only six digits after the area code and is kept
  as given.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | haa_scraper.py | 7 bodies: HRB, DNV Adriatica, SGS Adriatica, Bureau Veritas Croatia, UDEM Adriatic, ICR Adriatica, CRO CERT |
