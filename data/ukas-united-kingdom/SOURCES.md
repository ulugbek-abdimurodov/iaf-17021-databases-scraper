# UKAS (United Kingdom)

Source: UKAS directory of accredited organisations, "Management Systems Certification" category,
https://www.ukas.com/find-an-organisation/browse-by-category/?cat=2567 (listing cards: name,
address, telephone, categories) and each body's "Schedule of Accreditation" PDF
(`https://www.ukas.com/download-schedule/<number>/ManagementSystems`). Scraped with
`database/uk/ukas_ms_scraper.py --skip-certcheck` (the UKAS CertCheck API answers HTTP 403, so
certificate-level data was not collected), converted with `database/uk/prepare_certifind.py`; every
skipped scheme is listed in `database/uk/ukas_review.md`. Not yet verified by a person, so
`verified_at` is empty. `source_url` is the UKAS category listing (there is no per-body page);
`proof_url` is the schedule PDF that was read. No migration: UKAS is in `V2__reference_data.sql`
and every standard the schedules accredit is already in the reference data.

Extraction rules:

- One UKAS accreditation number (0001, 8289, ...) is one accreditation under ISO/IEC 17021-1:2015.
  `issue_date` is the schedule's current "Issue date" (not the first accreditation); UKAS schedules
  carry no expiry date, so `expiry_date` is empty.
- Bodies are accredited worldwide: `country` is the last part of the listing address (United
  Kingdom, China, United States, Japan, Malaysia, Qatar, Malta, Taiwan), never the AB's country.
- Accreditation standard per scheme as in the DAkkS / RvA datasets: ISO/IEC 27001 / 27701 →
  ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 →
  ISO/IEC 20000-6, ISO/IEC 42001 → ISO/IEC 42006, ISO 22301 → ISO/IEC 17021-6, ISO 37001 →
  ISO/IEC 17021-9, ISO 55001 → ISO/IEC 17021-5, AS 9100 → AS 9104-1 (suffixed rows such as
  `0001 (27006)`). Everything else is under the plain accreditation-number row.
- Schedule layout: each scope page repeats a header; a scheme section starts at "In accordance
  with ISO/IEC 17021-1 ..." and the next line names the scheme. Summary and location pages are
  not scope.
- Sectors: ISO 9001 / 14001 / 45001, ISO 22301, ISO 37001, ISO 55001, ISO 19443 and the other
  schemes that list them: the IAF codes in the table (`IAF 16 ...`, or `IAF 3, 5, 6` for
  ISO 55001). "Limited" accreditations are recorded for the whole IAF code; the limitation text
  is not kept. ISO 22000 / FSSC 22000: ISO 22003-1 categories (incl. sub-categories written
  `CI:`, `BIII:`); ISO 50001: ISO 50003 technical areas a)–h); ISO 13485: IAF MD 8 main technical
  areas — classified to EA with the ESYD tables. Schemes without a sector list (ISO/IEC 27001,
  27701, 20000-1, 42001, ISO 28000, 44001, 18788, AS 9100) are recorded for all EA sectors.
- Sector-scheme pages: AS 9100 (Aerospace Sector Certification Scheme, EN 9104-001) and
  ISO/IEC 27701 (ISO/IEC 27001 sector scheme) are imported; the rest of those pages is not.
- Struck-through words are dropped (only NQA 0015 has any: a superseded 27006 edition).
- Contacts: phone from the listing, normalised to international format (first number only);
  email and website from the schedule's contact block (the listing's Cloudflare-encoded email
  is used only when the schedule has none).
- Not imported: UK national / sector schemes (SSIP, National Highway Sector Schemes, TickIT Plus,
  tScheme, Weights and Measures Act self-verification, Energy & Utility Skills competence
  schemes, BS 9997 fire risk), the Dutch SCCM scheme, PEFC forest certification, FAMI-QS,
  ANSI/ASIS PSC.1, and UK Approved Body / Northern Ireland Notified Body product activities.
  Bodies left out because nothing importable remains: Soil Association 0107 (PEFC), MMRA 6168
  (BS 9997), LRQA Verification 6445 and NMi Certin UK 23275 (product conformity modules),
  Certsure/NICEIC 7975 (competence scheme), HORIBA MIRA 9998 (Weights and Measures). Ex Veritas
  8613 is missing: its schedule URL returned HTTP 502 on two runs.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | ukas_ms_scraper.py --skip-certcheck | 105 bodies, 104 schedule PDFs |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 98 bodies, 209 accreditations, 356 scope rows |
