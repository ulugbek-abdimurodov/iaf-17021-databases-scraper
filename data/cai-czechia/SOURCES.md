# CAI (Czechia)

Source: CAI (Český institut pro akreditaci, Czech Accreditation Institute) register of
certification bodies certifying management systems, https://www.cai.cz (category
"certifikacni-organy-certifikujici-systemy"), each body's detail page (IČO, address, website)
and its current "Osvědčení o akreditaci" (certificate of accreditation, PDF) with its annex
("Příloha"). Scraped with `database/czechia/cai_scraper.py`, converted with
`database/czechia/prepare_certifind.py`; every skipped scheme, merge and fallback is listed in
`database/czechia/cai_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` is the body's CAI register page, `proof_url` the certificate PDF on cai.cz. The
register gives no phone numbers or email addresses.

Extraction rules:

- Every CAI certificate is issued under ISO/IEC 17021-1. CertiFind keeps one accreditation per
  body and accreditation standard, so a certificate is split per accreditation standard:
  ISO 9001 / 14001 / 45001 / 13485 / 3834 under ISO/IEC 17021-1 (plain number, e.g.
  `279/2025`); ISO 22000 and FSSC 22000 → ISO 22003-1, ISO 50001 → ISO 50003,
  ISO/IEC 27001 → ISO/IEC 27006, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 →
  ISO/IEC 17021-6, ISO 37001 → ISO/IEC 17021-9. Those rows carry a suffix
  (`279/2025 (50003)`). Every row has the certificate's issue date and validity.
- Two bodies hold two certificates. LL-C: 88/2026 plus 514/2023 (ISO/IEC 20000-1, kept as
  `514/2023 (20000)`). 3EC International: 21/2026 plus 516/2025, which covers only HACCP and
  CFCS forest certification and is not imported.
- Only the Czech annex is read; it is the authoritative text. The English annexes were parsed
  the same way as a check and give the same EA codes, food categories and medical areas.
- Sectors come from each annex's "Kód oboru" (EA code) column. The "Omezeno na (kódy
  CZ-NACE)" column is compared with the complete CZ-NACE list CAI prints for an unrestricted
  EA code (MPA 50-01 annex 5); a row listing fewer codes is a limited scope and its NACE
  codes are given in the scope note (114 scope rows). The scope still counts for the whole
  EA code in search, so check the note. DEKRA's EA 17 is limited in the name column
  ("manufacture of metallurgical and fabricated metal products").
- ISO 9001 "ve spojení s" (in conjunction with) ISO 3834-2 / -3 / -4 is recorded as ISO 3834.
  ISO 9001 with Council Regulation (EU) No 333/2011 counts as plain ISO 9001.
- Where the specification cell spans several EA rows (merged cell; VUPS, STAVCERT, ČSÚ,
  eucert, ČSJ), every row in the span gets its standards. Checked against the rendered PDF.
- ISO 22003-1 food chain categories (ISO 22000, FSSC 22000), ISO 50003 technical areas
  (ISO 50001) and IAF MD 8 main technical areas (ISO 13485) are classified to EA with the
  ESYD tables.
- ISO/IEC 27001, ISO/IEC 20000-1, ISO 22301 and ISO 37001 rows without an EA code are
  recorded for all EA sectors. INTERCERT's ISO 22301 is listed under EA 33 only and is
  recorded as such.
- Not imported (rows without an EA code, or sections that are not management-system
  certification): HACCP per Věstník MZe 2/2010, SJ-PK (Czech road-construction quality
  system), CFCS 1002/1003 forest certification, ČSN 01 0391 (corporate social
  responsibility), EMAS environmental verification (Regulation (EC) No 1221/2009) and the
  notified-body sections ("Akreditace pro účely autorizace/oznámení").
- INTERCERT DOOEL, Skopje (North Macedonia) holds no ISO 9001 / 14001 / 45001 scheme. Its
  CAI certificate is still issued under ISO/IEC 17021-1, so it keeps the ISO/IEC 17021-1 row
  search requires, without scopes. It is also in `data/iarm-north-macedonia`; its body row is
  copied from there verbatim, because the importer matches bodies on country and name and
  would otherwise overwrite the IARM contact details on every run.
- Names: the register's name of the legal entity. Bodies are in Czechia, except INTERCERT.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | cai_scraper.py | 44 register entries (one certificate each) under 42 bodies, 69 PDFs |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 42 bodies, 121 accreditations, 212 scope rows (4,796 EA scopes) |
