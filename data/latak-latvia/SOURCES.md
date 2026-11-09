# LATAK (Latvia)

Source: register of the Latvian National Accreditation Bureau (Latvijas Nacionālais
akreditācijas birojs), scope S2 "management system certification bodies" (LVS EN ISO/IEC
17021-1), https://www.latak.gov.lv, and each body's accreditation certificate with its annex
(one PDF per body, linked from the register; `proof_url`). Generated with
`database/latvia/latak_s2_scraper.py` and `database/latvia/prepare_certifind.py`; open points
are in `database/latvia/latak_review.md`. Not yet verified by a person, so `verified_at` is
empty.

Extraction rules:

- One register entry (`S2-307` …) is one accreditation; the certificate number printed on
  the PDF (e.g. LATAK-S2-307-34-2005) changes with every revision, so the register ID is
  used. As in the BAS dataset, ISO 22000 / FSSC 22000 get an ISO 22003-1 row (`… (22000)`),
  ISO 50001 an ISO 50003 row (`… (50003)`), ISO/IEC 27001 / 27701 an ISO/IEC 27006 row
  (`… (27006)`), ISO/IEC 20000-1 an ISO/IEC 20000-6 row (`… (20000-6)`). Every body keeps its
  ISO/IEC 17021-1 row.
- ISO 9001 / 14001 / 45001 tables list "IAF n" (or the bare number in "Global
  ACI-TECH-3-021" tables) with a NACE Rev. 2 list. The number is the EA code. Each row is
  checked against IAF ID 1 via its NACE list; where they disagree, the code that keeps the
  list in EA order is used: S2-697 prints "6" for concrete (EA 16) and "2" for financial
  intermediation (EA 32); S2-424 prints NACE 23.5, 23.6 under IAF 28 (construction, kept);
  S2-564 prints NACE 38.2 under IAF 24 (recycling, kept).
- A NACE list narrower than the IAF ID 1 sector gives a "Limited scope" note. A sector is
  treated as complete when the annex lists its divisions / groups, or at least two sub-codes
  of each (several annexes list whole sectors class by class).
- Some tables lose the standard column; the standards then follow the order the annex text
  names them, a new block starting where the EA numbering restarts (S2-402, S2-443).
- ISO 22000 / FSSC 22000: ISO 22003-1 food chain categories; ISO 13485: IAF MD 8 main
  technical areas; both classified to EA with the BAS / ESYD tables.
- ISO 50001 ("assessed according to ISO 50003", no technical areas), ISO/IEC 27001, 27701,
  20000-1, ISO 22301, 37001, 21001 and ISO 3834 have no sector list and are recorded for all
  EA sectors.
- Not imported: certification of competent institutions in labour protection (Cabinet
  Regulation No. 723), environmental management with energy consumption evaluation (Cabinet
  Regulation No. 487), quality management under EU end-of-waste regulations 333/2011,
  1179/2012, 715/2013, quality management with MLC 2006, pressure equipment module H, PEFC
  forest management and PAS 24000. S2-700 (STEP UP Certification), S2-702 (SGS Latvija) and
  S2-710 (Nepcon) hold only PEFC and are left out.
- Names, registration numbers and addresses as the register prints them (the working
  address where two are given). Phone written +371; RCA's register number (393479041) is not
  a Latvian number and is left empty; DANEM MDC's is Turkish and kept.
- `issue_date` / `expiry_date` are the current accreditation period on the certificate.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | latak_s2_scraper.py | 14 active S2 bodies; 11 imported |
