# SAS (Switzerland)

Source: SAS (Schweizerische Akkreditierungsstelle, Swiss Accreditation Service, part of SECO)
register of management-system certification bodies (SCESm),
https://www.seco.admin.ch/en/search-accredited-bodies-sas, and each body's "SCESm directory"
(accreditation details and scope annex, PDF) in every language SAS publishes (de / fr / it /
en). Scraped with `database/switzerland/sas_scraper.py`, converted with
`database/switzerland/prepare_certifind.py`; every skipped scheme and fallback is listed in
`database/switzerland/sas_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` is the SECO search page, `proof_url` the directory PDF in the prevailing language.

Extraction rules:

- One SCESm number is one accreditation with one validity (current accreditation period).
  The register number is the body's `registration_no`.
- Language: each directory says which version prevails in case of contradiction, German for
  all but IAS Register (SCESm 0095, Italian). IAF codes are read from the prevailing version
  and compared with every other language version; they agree for all bodies. SI Cert
  (SCESm 0067) is published only in Italian and EdelCert (SCESm 0128) only in French. Food
  categories, ISO 50003 areas and IAF MD 8 areas are read by name from the English version.
  The English Bureau Veritas directory mislabels some ISO 9001 rows (e.g. "Machinery and
  equipment 22"); the codes are taken from the German version, where they match.
- Accreditation standard per scheme: ISO 9001 / 14001 / 45001 / 13485 / 3834 / 21001 / 15378
  under ISO/IEC 17021-1; ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 and
  FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO/IEC 42001 → ISO/IEC 42006,
  EN 9100 / AS 9100 → AS 9104-1 (EN 9104-001). Those rows carry a suffix
  (`SCESm 0001 (27006)`). KPMG (SCESm 0071) holds only such schemes and still gets the
  ISO/IEC 17021-1 row search requires, without scopes.
- Sectors come from the IAF code column (ISO 9001 / 14001 / 45001, and KPMG's
  ISO/IEC 20000-1: 31, 33, 35). Where ISO 9001 and 14001 share one table, codes marked
  "only for ISO 9001" (QS Zürich EA 4 and 13) go to ISO 9001 only. Restrictions printed with a
  code are kept in the scope note (SWISO EA 37 adult continuing education only; QS Schaffhausen
  EA 33 without software development; SQS EA 20 NACE 35.12 pleasure and sporting boats).
- ISO 22003-1 food chain categories (ISO 22000; FSSC 22000 subcategories BIII, C0–CIV, FI/FII
  by their letter), ISO 50003 technical areas and IAF MD 8 main technical areas (ISO 13485)
  are classified to EA with the ESYD tables. IAS Register's ISO 50001 lists no technical area
  and is recorded for all EA sectors.
- ISO/IEC 27001, 42001, ISO 3834, ISO 21001, ISO 15378, AS 9100 and the ISO/IEC 20000-1 of SQS
  and Swiss Safety Center have no sector list in the directory and are recorded for all EA
  sectors.
- Not imported: Swiss national schemes, so Concret AG (SCESm 0052, Swiss Care Excellence
  Certificate), IOL / OST (SCESm 0073, eduQua) and SanaCERT Suisse (SCESm 0097) are not in
  the dataset; eduQua, IN-Qualis and QSC of the other bodies; VDSZ data-protection and EPDV
  electronic-patient-record certification; pressure-equipment and lift module H (notified
  body); EN 9120 / AS 9120, NATO AQAP 2110, FAMI-QS, DIN EN 15593, ISO 27799, ISO 21188,
  BS 10008, CA/Browser Forum and WebTrust audits.
- SECO's lists of withdrawn (2026-09-04) and suspended (2026-08-10) accreditations name no
  SCESm body; all 16 SCESm accreditations are current.
- Names: the legal entity; the department or branch SAS prints after it is dropped (Swiss
  Safety Center AG "Certifications", KPMG AG "Zertifizierungsstelle", IAS Register AG
  "Sede Legale ed Operativa", SGS "International Certification Services", QS Zürich AG
  "Zweigstelle Basel", whose Therwil address is the accredited site). All bodies are in
  Switzerland.
- Contacts: the directory's phone, email and website (https:// when no scheme is given).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | sas_scraper.py | 16 SCESm bodies, 36 directory PDFs |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 13 bodies, 31 accreditations, 65 scope rows |
