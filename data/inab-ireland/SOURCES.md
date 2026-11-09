# INAB (Ireland)

Source: INAB directory of accredited bodies, "Certification Bodies → Management Systems
Certification", https://www.inab.ie/inab-directory/certification-bodies/management-systems-certification/:
each body's directory page, its "Schedule of Accreditation" PDF (`<no>-sc.pdf`) and its
certificate of accreditation (`<no>-ac.pdf`). Scraped with `database/ireland/inab_scraper.py`,
converted with `database/ireland/prepare_certifind.py`; every skipped classification is listed in
`database/ireland/inab_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` is the body's INAB directory page; `proof_url` is the schedule PDF that was read.

Extraction rules:

- One INAB registration (5001, 5006, ...) is one accreditation under EN ISO/IEC 17021-1:2015.
  `issue_date` is the certificate's "Date of last renewal of accreditation" (the award date when
  the body has not been renewed yet); `expiry_date` is "Expiry date of this certificate of
  accreditation".
- Accreditation standard per scheme as in the DAkkS and RvA datasets: ISO/IEC 27001 → ISO/IEC 27006,
  ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1 (suffixed rows such as
  `5001 (27006)`). ISO 9001 / 14001 / 45001 / 13485 and ISO 19443 are under the plain
  registration row.
- The schedule's page 1 lists the "Scope Classification"s; each scheme section of the "Scope of
  Accreditation" pages starts with a line holding only that classification. The "Sites" table is
  not scope (every body has one site, its head office).
- Sectors, ISO 9001 / 14001 / 45001: the IAF codes listed under the scheme (all of a code's rows
  are one code; restrictions in the "Detail" column, e.g. "13 Pharmaceuticals - Limited to ...",
  are not kept). ISO 50001: the ISO 50003 technical areas 01–08 (= A–H). ISO 22000 / FSSC 22000:
  ISO 22003-1 categories ("Cat C", "Catering ... E"); ISO 13485: IAF MD 8 main technical areas —
  all three classified to EA with the ESYD tables. ISO/IEC 27001 and ISO 19443 have no sector
  list and are recorded for all EA sectors.
- FSSC 22000 is the classification "FSSC" (FSSC V6) and is recorded as FSSC 22000.
- Struck-through words would be dropped as withdrawn activities, as for RvA; no current schedule
  has any.
- Not imported: the EU-directive notified-body activities ("Notified bodies - Mgt Sys": PED
  2014/68/EU Module H, RCD 2013/53/EU Module H). Two bodies hold only these and are left out:
  HPI Verification Services 5018 and Vertigo Inspection (Irish Engineering Services) 5019.
  Hartford Steam Boiler 5017 is imported for ISO 19443 only.
- Contacts: the directory page's phone, email, website and address; the schedule's phone and
  website fill gaps. Irish numbers are written in international form (+353); HSB's only number is
  a 1800 freephone, which has no international form, so its phone is empty. NSAI publishes no phone number.
  NSAI's directory email links to a different address than it shows; the shown one (also on the
  schedule) is used.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | inab_scraper.py | 8 bodies, 16 PDFs (schedule + certificate each) |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 6 bodies, 12 accreditations, 24 scope rows |
