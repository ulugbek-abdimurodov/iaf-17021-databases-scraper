# Akkreditierung Austria (Austria)

Source: Akkreditierung Austria public register, https://akkreditierung-austria.gv.at/,
program 928 "Certification Body for Managementsystems" (Managementzertifizierungsstelle):
each body's record and every scope revision (`/overview/<scope id>`). Scraped with
`database/austria/scrape_akkreditierung_austria.py`, converted with
`database/austria/prepare_certifind.py`; every skipped scheme and data difference is listed in
`database/austria/akkreditierung_review.md`. Not yet verified by a person, so `verified_at` is
empty. `source_url` is the register home page; `proof_url` is the register page of the scope
behind the row (ISO 9001 where the body holds it).

Extraction rules:

- One identification number (e.g. 0901) is one accreditation under EN ISO/IEC 17021-1:2015;
  it is the body's `registration_no`. The register gives one initial accreditation date per
  body, used as `issue_date` on every row, and no end date: Austrian accreditations are
  open-ended and kept under surveillance, so `expiry_date` is empty.
- Only scopes of type N (accredited standards, all VALID) are imported. The other types are
  applicable documents (EA-3/01, IAF MDs, ISO/IEC 17021-2 / -3 / TS 17021-x, ISO 22003-1,
  ISO 50003, ISO/TS 22002-x, ...) and are only used to cross-check.
- Accreditation standard per scheme: ISO 9001 / 14001 / 45001 / 13485 / 37301 / 21001 / 29993 /
  7101 / 3834 under ISO/IEC 17021-1; ISO/IEC 27001, 27701, 27017, 27018 → ISO/IEC 27006,
  ISO 50001 → ISO 50003, ISO 22000 and FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 →
  ISO/IEC 20000-6, ISO/IEC 42001 → ISO/IEC 42006, ISO 22301 → ISO/IEC 17021-6, ISO 37001 →
  ISO/IEC 17021-9, ISO 55001 → ISO/IEC 17021-5, EN 9100 → AS 9104-1. Those rows carry a suffix
  (`0901 (27006)`). CIS (0924) and OCG (0948) hold only such schemes and still get the
  ISO/IEC 17021-1 row search requires, without scopes. Several editions of one standard
  (ISO/IEC 27001:2013 and :2022, ISO 37001:2016 and :2025, ÖNORM EN ISO 45001:2023, ÖVE/ÖNORM
  EN ISO 13485:2022, ...) are merged into one scope.
- Sectors (ISO 9001 / 14001 / 45001): the IAF codes in the scope's "field/ range" text
  ("IAF-Codes 1, 2, 3 ... und 39"), together with the codes of its technical fields
  (`90.002.17.U` = IAF 17; cluster entries such as `90.006.00.C.05A.14A`). The technical fields
  name only part of the codes for most bodies; none names a code the text leaves out.
  Bureau Veritas's ISO 45001 EA 17 is limited to fabricated metal products (scope note).
- ISO 22003-1 food chain categories (technical fields `90.420.*`, `90.221.*`), ISO 50003
  technical areas (technical fields `90.600.0N` and the ISO 50001 field/ range text) and
  IAF MD 8 main technical areas (`90.500.0N`, ISO 13485) are classified to EA with the ESYD
  tables. SystemCERT's ISO 50003 document lists fewer areas than its ISO 50001 scope (no
  buildings / building complexes) though its title names them; the ISO 50001 scope is used.
- ISO/IEC 27001, 27701, 27017, 27018, 20000-1, 42001, ISO 22301, 37001, 37301, 55001, 21001,
  29993, 7101, 3834 and AS 9100 have no sector list in the register and are recorded for all
  EA sectors.
- Not imported: Austrian and German national schemes (AUVA-SGM, SCC-VAZ, IT-Sicherheitskatalog
  § 11 EnWG); EN 9110, EN 15085-2, TL 9000, ISO/IEC 27002 / 27011 / 27019, ISO/IEC TR 20000-9,
  IEC 62443-2-1 and ISO 29990 (withdrawn), which are not in CertiFind's standards; Regulation
  (EU) 2018/762 and 2018/858 and Directive 2014/68/EU module H.
- All 9 bodies of the program hold a valid accreditation; none is suspended or withdrawn.
- Names: the register's legal entity. The TU Graz testing centre is listed as "Technische
  Universität Graz – Europaprüfstelle für Medizinprodukte", since the university alone does
  not identify the body. All bodies are in Austria.
- Contacts: the register's phone, email and website; the address is the body's business
  address (TÜV SÜD: Arsenal, Wien; TÜV AUSTRIA: Brunn am Gebirge), not the legal entity's seat.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | scrape_akkreditierung_austria.py | 9 bodies, 214 scope rows (109 accredited standards) |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 9 bodies, 32 accreditations, 63 scope rows |
