# EGAC (Egypt)

Source: register of the Egyptian Accreditation Council (EGAC), https://egac.gov.eg/en/accredited-cabs/,
discipline "Management System Certification Bodies" (ISO/IEC 17021-1), every status, and each
body's schedule of accreditation (the "…B.pdf" scope file on its entity page). Generated with
`database/egypt/egac_ms_scraper.py` and `database/egypt/prepare_certifind.py`; the parser's open
points are in `database/egypt/egac_review.md`. Not yet verified by a person, so `verified_at` is
empty. `source_url` and `proof_url` are the body's EGAC entity page (the PDFs are only served
through EGAC's download API).

Extraction rules:

- The scope tree on the EGAC entity page is the same 300-line catalogue for every body, so it is
  not used. The accredited scope comes only from the schedule PDF, read with pdfplumber word
  positions. pdftotext-style text order is not used because it moves the IAF code column several
  rows away from the sector names, sometimes above the standard's heading.
- One EGAC reference number (`0105002`, `011801/1`, …) is one accreditation. Standards that other
  datasets accredit under their own scheme get their own accreditation row, as in the ESYD
  dataset: ISO 22000 and FSSC 22000 → ISO 22003-1 (`… (22000)`), ISO/IEC 27001 and 27701 →
  ISO/IEC 27006 (`… (27006)`), ISO 50001 → ISO 50003 (`… (50003)`), ISO/IEC 20000-1 →
  ISO/IEC 20000-6 (`… (20000)`), ISO 37001 → ISO/IEC 17021-9 (`… (37001)`), ISO 39001 →
  ISO/IEC 17021-7 (`… (39001)`), ISO/IEC 42001 → ISO/IEC 42006 (`… (42001)`). All other standards
  (ISO 22301, 21001, 29993, 29994, 37301, 41001, 55001, 7101, 18788, 19443, 28000, 28001, 30401,
  37101, 44001, 56001) are recorded under ISO/IEC 17021-1, even where the schedule names their own
  17021-x / 28003 part. Every body keeps its ISO/IEC 17021-1 row.
- ISO 9001 / 14001 / 45001 tables are headed "IAF Codes No.": the number is the IAF / EA code
  1-39 and is taken as written, also where EGAC prints a different sector name beside it
  (011603 ISO 45001 code 8 named "Printing companies", 011705/1 ISO 9001 code 9 named "Rubber and
  plastic products") or none at all (011602 ISO 14001 codes 2 and 10). Limits written in the
  sector column ("Limited to “Paper products”", "Electrical Equipment (excluding Medical)") go in
  `scope_note`.
- ISO 22000 and FSSC 22000 tables list ISO 22003-1 food chain categories and sub-categories;
  ISO 13485 tables list IAF MD 8 main technical areas. Both are classified to EA with the tables
  of the BAS / ESYD datasets, and the scope note names the categories or areas.
- A standard named in the schedule with no list under it (all ISO 50001 entries, since no
  schedule lists ISO 50003 technical areas; ISO/IEC 27001, ISO 22301, ISO 21001, …) is recorded
  for all EA sectors (`ALL`).
- Headings that leave out the standard's number ("Information Security Management Systems
  According to ISO/IEC 27006-1", "Business Continuity Management Systems According to …") are
  matched by the standard's name. ISO 19443 is printed as "Quality management systems for the
  application of ISO 9001 … nuclear safety" and recorded as ISO 19443, not ISO 9001.
- Not imported: ISO 37000 (012308) and ISO 10002 (012502, 012220), guidance standards that
  cannot be certified against.
- Scanned schedules without a text layer of accredited bodies (010601/1, 011806, 011902, 0121004,
  012219, 012220, 012303) were read from the PDF by hand (`MANUAL` in the prepare script). 012403
  filed a certificate under "Scopes" and its schedule under "Certificates" (`012403_scope.pdf`);
  the schedule is used.
- Seven accredited bodies' entity pages did not load during the scrape; six were fetched again
  with `database/egypt/egac_retry_incomplete.py`. 0126007 (CertiOne) still returns an incomplete
  page and has no scope rows; run the retry script again to fill it in.
- Status: only Accredited bodies are kept. Withdrawn and Expired bodies (11), and any row whose
  expiry date has passed, are removed by `database/prune_inactive.py`, which the prepare script
  runs after writing the CSVs. No body is listed as suspended.
- `issue_date` is the register's first accreditation date ("Accredited Date" on the entity page),
  or the current accreditation date where the page gives none; `expiry_date` is the register's
  expiry date (empty for some withdrawn bodies). Bodies keep the country the register gives
  (82 Egypt, 22 India, others). Contact details are the register's; phone numbers lose the
  national trunk 0 written after the country code (`+20 0100 675 5251` → `+20 100 675 5251`), and
  placeholder websites (`https://none.com`) are left empty.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | egac_ms_scraper.py | 129 bodies: 118 accredited (111 with scopes), 7 withdrawn, 4 expired |
| 2026-11-04 | egac_retry_incomplete.py, prune_inactive.py | 6 of 7 missing pages fetched; 11 withdrawn or expired bodies removed: 118 bodies, 403 accreditations, 832 scope rows |
