# EAK (Estonia)

Source: EAK register of management-system certification bodies (MSC certificates),
https://eak.ee/index_eng.php?pageId=33, and the scope annexes linked from each body's
page. Scraped with `database/estonia/eak_scraper.py`, converted with
`database/estonia/prepare_certifind.py`. Not yet verified by a person, so `verified_at`
is empty.

Extraction rules:

- `issue_date` / `expiry_date` are the register's "accreditation effective" and "valid
  until" dates. ISO 22000 gets its own row under ISO 22003-1 (`MSC004 (22000)`), as in
  the other datasets; ISO 9001, 14001 and 45001 share the ISO/IEC 17021-1 row.
- The annexes list NACE Rev. 2.1 divisions with an extent ("Full", "Except 20.13",
  "Limited to 33.11; ..."). They are converted to EA with the IAF ID 1 table (Rev. 2.1
  moved materials recovery to 38.2 and motor vehicle repair to 95.3). An EA sector is
  noted as limited in `scope_note` unless every NACE code IAF ID 1 assigns to it is held,
  so a body holding only NACE 02 has EA 1 as a limited scope.
- KIWA's single annex holds three tables (1.1 ISO 9001, 1.2 ISO 14001, 1.3 ISO 45001);
  the scraper did not label them, so they were split by hand from the annex text.
- ISO 22000 categories are classified to EA by sector, as in the RENAR, DPA and ESYD
  datasets: C = 3, F = 29, G = 31, I = 7, 14, 15, 17, K = 12, 13.
- Phone numbers are rewritten in international form (`+3726599470` → `+372 6599470`).

Gaps:

- Metrosert (MSC001): all five annex links on the EAK page return 404 (checked again on
  2026-11-03), so the body has its 17021-1 accreditation but no scope rows. The register
  describes it as "QMS, EMS, OHSAS, FSMS and ISMS"; add the scopes, and the 22003-1 and
  27006 rows, once the annexes are published.
- Not imported: Preferred by Nature OÜ (MSC005) and NCS Estonia OÜ (MSC006), whose only
  scope is PEFC forest-management certification against national PEFC standards (PEFC
  EST 1003, PEFC DK 001), which are not international management-system standards.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-03 | eak_scraper.py | 5 bodies, 8 annexes read, 5 annexes missing (Metrosert); 3 bodies imported |
