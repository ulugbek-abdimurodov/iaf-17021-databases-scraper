# NABCB (India)

Source: NABCB (National Accreditation Board for Certification Bodies, Quality Council of
India) lists of accredited management-system certification bodies, https://nabcb.qci.org.in,
and each certificate's page (contacts, validity, accreditation standards, scope table), plus
the "Accreditations withdrawn" tables. Scraped with `database/india/nabcb_ms_scraper.py`,
converted with `database/india/prepare_certifind.py`; open points are in
`database/india/nabcb_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` / `proof_url` are the NABCB certificate pages.

Extraction rules:

- NABCB gives each scheme its own certificate (QM002 QMS, EM002 EMS, OH006 OHSMS for the same
  body); the MDQMS, ISO 21001 and ISO 15378 pages reuse the QM number. ISO 9001, 14001,
  45001, 13485, 21001 and 15378 share the body's ISO/IEC 17021-1 row, as in the other
  datasets. Its number is the active QM certificate (else EM, else OH); `issue_date` is the
  earliest first-accreditation date and `expiry_date` the latest valid-to date of the merged
  certificates. Scopes from another certificate name it and its validity in the scope note.
- Other schemes get their own row under their own number: FSMS → ISO 22003-1, EnMS →
  ISO 50003, ISMS → ISO/IEC 27006, ITSMS → ISO/IEC 20000-6, BCMS → ISO/IEC 17021-6, ABMS →
  ISO/IEC 17021-9, AMS → ISO/IEC 17021-5, AIMS → ISO/IEC 42006 (NABCB prints only 17021-1),
  AS 9100 → AS 9104-1. A body without an active merged certificate still gets the 17021-1
  base row that search requires, under its first active scheme number; that scheme row gets
  a suffix (`FS029` + `FS029 (22000)`).
- QMS / EMS / OHSMS tables give IAF codes, which are the EA codes. A description that narrows
  the sector ("Limited to …", "restricted to NACE …", "except …") is a limited scope in the
  note, unless it only restates IAF ID 1 (e.g. "24 except 24.46, 25 except 25.4, 33.11").
- ISO 22003-1 food chain categories, ISO 50003 technical areas and IAF MD 8 main technical
  areas (A1.1–A1.7) are classified to EA with the BAS / ESYD tables. FSSC 22000 is recorded
  for the categories a page marks as FSSC-approved (FSSC normative document such as ISO/TS
  22002-x or PAS 221, "approved category for FSSC 22000", or an FSSC section); "Not approved
  for FSMS" (FS004 K) keeps a category out of ISO 22000. FAMI-QS feed tables are left out.
- ISO/IEC 27001, 27701 (where the ISMS page names it), 20000-1, 22301, 21001, 15378, 37001,
  55001, 42001 and AS 9100 have no sector list and are recorded for all EA sectors.
- Not imported: ICMED 9000 / ICMED 13485 (Indian national schemes), FSSC 24000 (SM001),
  ISO 16363 repositories (TD001, a UK body with no other NABCB scheme), SERI R2 (EM036 lists
  only R2v3, no ISO 14001 sectors), and the four withdrawn rows for "Standards Organisation of
  Nigeria", which repeat other bodies' certificate numbers, dates and contacts.
- Only bodies that currently hold a valid accreditation are kept. Withdrawn, expired and
  suspended certificates are left out, and so is an active-listed certificate whose valid-to
  date has passed (FS006 INDOCERT 2025-01-17, FS029 TEXA 2026-09-11, the ISO 21001 page of
  QM033 Intertek 2026-04-17); `database/prune_inactive.py` then removes any body left without
  a valid ISO/IEC 17021-1 row (39 bodies, listed in `nabcb_review.md`). QM051 (ACM) is in both
  the active and the withdrawn list; withdrawn is kept. TEXA's only other certificate (QM076,
  ISO 13485) is suspended, so TEXA is removed.
- Dates: the certificate page's valid-to date is used where it differs from the list (FS009,
  FS031, OH019: page 2030, list 2026).
- Names: NABCB's spelling of the base certificate, without notes such as "(Accreditation was
  not valid during …)". Spellings of one body on different pages are merged (TUV India,
  ISSPL / IRCLASS, International Certification(s) Services, STQC Directorate and STQC IT
  Certification Services). Country from the address (Russia, Nepal, Bhutan, Mauritius).
- Contacts: first phone in international form (+91 and the national number), first email,
  website with https://.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | nabcb_ms_scraper.py | 316 certificate pages; 123 bodies (86 active), 205 accreditations, 254 scope rows |
| 2026-11-04 | prune_inactive.py | expired, withdrawn and suspended removed: 84 bodies, 164 accreditations, 250 scope rows |
