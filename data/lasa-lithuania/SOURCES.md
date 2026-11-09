# LASA (Lithuania)

Source: register of the Lithuanian accreditation body (Lietuvos akreditacijos ir
standartizacijos agentūra, LASA; formerly Nacionalinis akreditacijos biuras, NAB),
http://db.nab.lt/ais, type "Vadybos sistemų sertifikavimo įstaigos" (ISO/IEC 17021-1), and
each body's certificate with its scope ("Akreditavimo sritis"). Downloaded with
`database/lithuania/nab_scraper.py`; the CSVs are written by
`database/lithuania/prepare_certifind.py`, which holds the sector tables transcribed from
the scope PDFs. Not yet verified by a person, so `verified_at` is empty. `source_url` and
`proof_url` are the body's register record.

Extraction rules:

- One register entry is one certificate (`LA.04.00x`) under ISO/IEC 17021-1. Extra
  accreditation standards get their own row with a suffix, as in the other datasets:
  `(22000)` for ISO 22000 (ISO 22003-1), `(27006)` for ISO/IEC 27001.
- ISO 9001 / 14001 / 45001 tables give the "IAF kodas", which is the EA code, with the EVRK 2
  (NACE rev. 2) codes. Each row's NACE list is compared with IAF ID 1 (table reused from the
  BAS dataset); when it is narrower, the scope note says "Limited scope" and lists the
  annex's NACE codes. No row lists a NACE code outside its EA sector.
- ISO 22000 categories are classified to EA by sector, as in the other datasets: LST Sert
  holds category C (subcategories CI and CIV only) = EA 3.
- ISO/IEC 27001 has no sector list and is recorded as `ALL`.
- Names are as on the certificate. `registration_no` is the certificate's "juridinio
  asmens kodas". Address is the scope's "Veiklos vykdymo vietos adresas". Phone, e-mail and
  website from the register record (first one when several are given).
- `issue_date` is the initial accreditation date ("akredituota nuo"), `expiry_date` the
  certificate's "galioja iki".

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | nab_scraper.py | 5 bodies: LST Sert, Sertika, Euromatas, Bureau Veritas Lit, Sistemų registras |
