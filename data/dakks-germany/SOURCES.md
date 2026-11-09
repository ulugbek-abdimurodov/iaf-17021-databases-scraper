# DAkkS (Germany)

Source: DAkkS register of accredited bodies, https://www.dakks.de/, type ZM
"Zertifizierungsstelle für Managementsysteme": each accreditation's detail page
(`akkreditierte-stelle.html?id=<number>`) and its certificate / annex PDFs. Scraped with
`database/germany/dakks_scraper.py`, converted with `database/germany/prepare_certifind.py`;
every skipped programme and every annex read by hand is listed in
`database/germany/dakks_review.md` and in `MANUAL` in the converter. Not yet verified by a
person, so `verified_at` is empty. `source_url` is the body's DAkkS register page;
`proof_url` is the annex PDF behind the row (ISO 9001 where the body holds it).

Extraction rules:

- DAkkS numbers are D-ZM-<body>-<certificate>-<annex>. One accreditation certificate
  (D-ZM-16029-01-00) is one row under ISO/IEC 17021-1; its annexes (-01, -02, ...) carry the
  programmes. All ZM accreditations are granted under DIN EN ISO/IEC 17021-1. `issue_date` is
  the certificate's "Gültig ab" (date of the current version, not the first accreditation).
  German annexes have no end date, so `expiry_date` is empty; only the two foreign bodies
  (Ghana Standards Authority, China Quality Certification Centre) give one ("Valid to").
- Accreditation standard per scheme, as in the other datasets: ISO/IEC 27001 / 27701 →
  ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 and FSSC 22000 → ISO 22003-1,
  ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6, ISO 37001 →
  ISO/IEC 17021-9, ISO 55001 → ISO/IEC 17021-5, EN 9100 → AS 9104-1 (suffixed rows such as
  `D-ZM-16029-01-00 (27006)`). Everything else (ISO 9001 / 14001 / 45001 / 13485 / 15378 /
  19443 / 21001 / 29001 / 37301, EN 15224) is under the ISO/IEC 17021-1 row.
- Sectors, ISO 9001 / 14001 / 45001: the annex's IAF code table, one tick column per standard.
  In vector PDFs a tick is drawn as two diagonal lines inside the box; the converter reads
  them from the PDF drawing (checked: ticks found = X marks drawn, for every vector table).
  14 annexes are scanned images or list only the accredited codes; their codes were read from
  the page images and are in `MANUAL`. Automotive annexes (EU 2018/858 type approval, IATF /
  VDA competence) confirm ISO 9001 only for IAF 22 and refer to the main ISO 9001 annex.
- ISO 50001: ISO 50003 technical areas A–H listed in the annex; ISO 22000 / FSSC 22000:
  ISO 22003-1 food chain categories listed in the annex (for annexes holding both, the union
  of the categories is used for both); ISO 13485: IAF MD 8 main technical areas named in the
  annex. All three are classified to EA with the ESYD tables. EN 15224: health care sectors,
  EA 38.
- ISO/IEC 27001, 27701, 20000-1, ISO 22301, 37001, 37301, 55001, 21001, 15378, 19443, 29001
  and AS 9100 have no sector list in the annex and are recorded for all EA sectors.
- Not imported: German and other national schemes (SCC / SCP, IT-Sicherheitskatalog § 11 EnWG,
  BAR / DEGEMED rehabilitation QM, MAAS-BGW, VDA prototype protection, PEFC España); IATF 16949
  (IATF oversight); EN 9110 / 9120, FAMI-QS, IEC 62443, ISO/SAE 21434 (not in CertiFind's
  standards); EU directive / regulation modules (notified-body activities).
- InterCert's two partially suspended annexes (ISO 50001, ISO/IEC 27001) are left out, since
  DAkkS does not say which part is suspended. Withdrawn accreditations are not imported.
- Names: the register's name without the department suffix ("Zertifizierungsstelle für
  Managementsysteme", "Umweltgutachter..."). The address is the register's. The register
  publishes no phone, email or website: those come from each body's own website (its
  Impressum where it has one), found with `database/germany/find_contacts.py` into
  `contacts.csv`. A site is accepted only if it names the body; group or foreign pages and
  wrong matches are rejected in the script (`REJECT`). Bodies whose site could not be read
  (bot protection, broken TLS, unknown domain) keep empty contacts.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | dakks_scraper.py | 109 bodies, 365 accreditations / annexes, 395 PDFs |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 103 bodies, 238 accreditations, 345 scope rows |
