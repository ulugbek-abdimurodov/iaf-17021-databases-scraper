# Norsk Akkreditering (Norway)

Source: the Norsk Akkreditering register,
https://www.akkreditert.no/en/akkrediterte-organisasjoner/?scope=SysCert, every "MSYS"
registration under NS-EN ISO/IEC 17021-1:2015 (management system certification). Scraped with
`database/norway/no_ms_scraper.py` (each registration's HTML page, English and Norwegian, with
its scheme tables; no PDF annexes), converted with `database/norway/prepare_certifind.py`; every
skipped scheme is listed in `database/norway/na_review.md`. Not yet verified by a person, so
`verified_at` is empty. `source_url` and `proof_url` are the body's NA register page.

Extraction rules:

- One NA registration per company; no merging was needed.
- `issue_date` is the register's "renewed" date when given, otherwise the date accreditation was
  first granted; `expiry_date` is the register's valid-to date.
- Accreditation standard per scheme as in the DAkkS and RvA datasets: ISO/IEC 27001 and
  ISO/IEC 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 → ISO 22003-1, ISO 22301 →
  ISO/IEC 17021-6, ISO 39001 → ISO/IEC 17021-7, ISO 37001 → ISO/IEC 17021-9 (suffixed rows such
  as `MSYS 001 (27006)`). ISO 9001 / 14001 / 45001 / 13485 / 21001 / 3834 are under the plain
  registration row.
- NA lists ISO 14001:2015 and ISO 14001:2026 as separate schemes; both are ISO 14001 and their
  IAF codes are combined. "NS-EN ISO 3834-2:2021 and ISO 9001:2015" is recorded as ISO 3834 (the
  bodies holding it also hold ISO 9001 separately).
- Sectors, ISO 9001 / 14001 / 45001: the IAF codes ("IAF 17") in the scheme table. ISO 50001:
  EnMS1–EnMS8 = ISO 50003 technical areas A–H; ISO 22000: ISO 22003-1 categories ("Category
  C"); ISO 13485: IAF MD 8 main technical areas ("1_1_1 Non-Active Medical Devices") — all three
  classified to EA with the ESYD tables. ISO/IEC 27001, 27701, ISO 22301, 39001, 37001, 21001
  and 3834 have no sector list and are recorded for all EA sectors.
- Not imported (national schemes): Eco-Lighthouse scheme (Miljøfyrtårn), PEFC N 02 / N 03
  (Norwegian PEFC forest standard) and BEK 1138/2025 with ISO 14001 (Danish mandatory energy
  management order). Certnor AS (MSYS 025) holds only Eco-Lighthouse and is left out.
  Personnel / ETS registrations that mention management systems (PERS 005, VV 006) are not
  ISO/IEC 17021-1 accreditations and are not imported.
- Contacts: the registration's phone, email and website; the address is the unit's visiting
  address (the register's postal address is often a "Postboks"). Norwegian 8-digit numbers are
  written as +47; Stiftelsen Kontrollrådet's fax number is dropped. "DNV PRODUCT ASSURANCE AS"
  is written "DNV Product Assurance AS".

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | no_ms_scraper.py | 12 registrations, 12 companies |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 11 bodies, 24 accreditations, 50 scope rows |
