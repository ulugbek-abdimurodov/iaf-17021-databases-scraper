# RvA (Netherlands)

Source: RvA register of accredited bodies, https://www.rva.nl/alle-geaccrediteerden/, filter
"norm:17021-1" (management system certification bodies): each registration's detail page and
its "Annex to declaration of accreditation" PDF (English `-sce.pdf`, Dutch `-scn.pdf`). Scraped
with `database/netherlands/rva_scraper.py`, converted with `database/netherlands/prepare_certifind.py`;
every skipped scheme is listed in `database/netherlands/rva_review.md`. Not yet verified by a
person, so `verified_at` is empty. `source_url` is the registration's RvA page; `proof_url` is
the annex PDF that was read.

Extraction rules:

- One RvA registration (C010, C589, ...) is one accreditation under EN ISO/IEC 17021-1:2015.
  `issue_date` / `expiry_date` are the annex's "valid from" / "to" dates (current annex version,
  not the first accreditation). The English annex is read when published, otherwise the Dutch one.
- Companies with several registrations (DEKRA C013 + C589, Bureau Veritas C248 + C558, SGS
  C055 + C625, Kiwa Assurance C637 + C700) are one body. CertiFind allows one accreditation per
  body, accreditation body and standard, so a second registration's schemes are merged into the
  first registration's rows and dates. Only DEKRA is affected: C589's ISO 9001 / ISO 13485 scope
  is under C013 (C589's own annex runs to 2027-03-01, C013's to 2030-01-01). The other second
  registrations hold nothing importable.
- Accreditation standard per scheme as in the DAkkS dataset: ISO/IEC 27001 / 27701 → ISO/IEC 27006,
  ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6,
  ISO/IEC 42001 → ISO/IEC 42006, ISO 22301 → ISO/IEC 17021-6, ISO 55001 → ISO/IEC 17021-5
  (suffixed rows such as `C024 (27006)`). ISO 9001 / 14001 / 45001 / 13485, ISO 3834 and
  EN 15224 are under the plain registration row.
- The annex is a two-column table (scheme | scope); the converter splits the columns by x position.
  Location tables (which repeat scheme names per site) are not scope.
- Sectors, ISO 9001 / 14001 / 45001: the IAF codes listed under the scheme. ISO 50001: the IAF
  codes in the annex's ISO 50003 technical-area table. ISO 22000 / FSSC 22000: ISO 22003-1
  categories; ISO 13485: IAF MD 8 main technical areas — both classified to EA with the ESYD
  tables. EN 15224: health care, EA 38. ISO/IEC 27001, 27701, 20000-1, 42001, ISO 22301, 55001
  and ISO 3834 have no sector list and are recorded for all EA sectors. Restrictions written
  next to a code (e.g. "35 other services (limited to NACE 78-82)") are not kept.
- FSSC 22000 is written in RvA annexes as "ISO 22000, ISO/TS 22002-x, Additional FSSC
  requirements" and is recorded as FSSC 22000.
- Crossed-out activities (voluntary withdrawal, e.g. TÜV Rheinland C058, EY C466, Control Union
  C499, JIA C141) are struck through in the PDF; struck words are dropped, so withdrawn IAF
  codes are not imported.
- Not imported: Dutch national schemes (VCA / VCU, HKZ, NEN 7510, CO2-Prestatieladder, Groenkeur,
  SCIOS, CKB, BRL SVMS 007, PCSN / PEFC, arbodiensten, CERTEX, NPA); AQAP 2110, FAMI-QS,
  EFISC-GTP, Riskplaza (not in CertiFind); PGS 29, pressure equipment and Cyber Resilience Act
  product activities (notified-body work). Eight registrations hold only such schemes and are left
  out: Safex C495, Energie Consult Holland C621, NHG Praktijk Accreditering C709, SGS Brightsight
  C717, UL International C721, and the second registrations BV C558, SGS C625, Kiwa Assurance C700.
- Contacts: the register's phone, email and website. `address` is the register's postal address
  (often a Postbus).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | rva_scraper.py | 56 registrations, 77 annex PDFs |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 47 bodies, 91 accreditations, 129 scope rows |
