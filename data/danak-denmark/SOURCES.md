# DANAK (Denmark)

Source: the DANAK accreditation registry, https://registry.danak.dk/registry/<no>, every
registration under DS/EN ISO/IEC 17021-1:2015 (management system certification). Scraped with
`database/denmark/danak_ms_scraper.py` (the registry's JSON per registration, with its scheme
tables), converted with `database/denmark/prepare_certifind.py`; every skipped scheme is listed
in `database/denmark/danak_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` and `proof_url` are the body's DANAK registry page.

Extraction rules:

- DANAK gives one company several registrations: 5xxx (quality and most other schemes), 6xxx
  (environment / energy) and 65xx (occupational health and safety). CertiFind allows one
  accreditation per body, accreditation body and standard, so they are merged into the
  company's lowest registration number, whose dates are used. A scope row that came from
  another registration says so in `scope_note` ("DANAK registration 6001").
- `issue_date` is the registry's "renewed" date (the start date when the registration has not
  been renewed yet); `expiry_date` is its expiry date.
- Accreditation standard per scheme as in the DAkkS and RvA datasets: ISO/IEC 27001 →
  ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO 55001 →
  ISO/IEC 17021-5 (suffixed rows such as `5001 (50003)`). ISO 9001 / 14001 / 45001 / 13485 are
  under the plain registration row.
- Sectors, ISO 9001 / 14001 / 45001: the IAF codes in the scheme table. NACE exceptions in the
  "Exceptions" column (e.g. "25.40 Manufacture of weapons and ammunition") are not kept; the
  IAF code is recorded. ISO 50001: ISO 50003 technical areas A–H; ISO 22000 / FSSC 22000:
  ISO 22003-1 categories (FSSC sub-categories CI–CIV, FI–FII count as C, F); ISO 13485: IAF MD 8
  main technical areas — all three classified to EA with the ESYD tables. ISO 55001: the IAF
  codes listed in the scope. ISO/IEC 27001 has no sector list and is recorded for all EA sectors.
- Not imported (Danish national schemes and schemes not in CertiFind): the Executive Orders
  (wind turbine service, lifts expert companies, meter installers, energy labelling of
  buildings, mandatory energy audits / energy management, excess heat, health and safety
  certificate, use of pressure equipment), Insurance & Pension Denmark requirements, DS 21001
  (railway safety), AQAP-2110, PED 2014/68/EU and RED 2014/53/EU Module H. Two registrations
  hold only these and are left out: Byggeriets Kvalitetskontrol 5013 and TÜV SÜD Danmark 5020.
- Contacts: the registration's contact person phone and email, its website and address
  (", Danmark" dropped). Danish 8-digit numbers are written as +45; Intertek's number is
  Swedish (+46) as published.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | danak_ms_scraper.py | 25 registrations, 15 companies |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 13 bodies, 23 accreditations, 31 scope rows |
