# FINAS (Finland)

Source: FINAS register of accredited operators, https://www.finas.fi/sites/en/operators/Pages/default.aspx
(SharePoint search over https://www.finas.fi/Scopes), management system certification bodies
(ISO/IEC 17021-1). Each record is one scope PDF ("Liite 1 / Appendix 1"). Scraped with
`database/finland/scrape_fi_finas.py`, converted with `database/finland/prepare_certifind.py`;
every skipped scheme is listed in `database/finland/finas_review.md`. Not yet verified by a person,
so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF that was read.

Extraction rules:

- One FINAS registration (S001, S002, ...) is one accreditation under SFS-EN ISO/IEC 17021-1:2015.
  `issue_date` is the current decision date, `expiry_date` the decision's last day of validity.
- All bodies are in Finland. Addresses are the register's; city names are re-cased, and the company
  name repeated in two addresses (Nixu S047, Testmill S051) is removed. Websites come from the
  register, or from the annex's first page when the register has none. The register lists no phone
  numbers or emails.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006,
  ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6,
  ISO 22301 → ISO/IEC 17021-6 (suffixed rows such as `S001 (27006)`). ISO 9001 / 14001 / 45001 /
  13485, ISO 3834 and EN 15224 are under the plain registration row.
- Two annex layouts. Older annexes interleave Finnish and English lines in a "certification category /
  technical area" table. Newer annexes (decision numbers like S074/A01/2026) have a Finnish and an
  English half, and the English half is read. Each of their headings is "category/standard/IAF NN
  sector". No FINAS annex has struck-through text.
- Sectors, ISO 9001 / 14001 / 45001: the IAF (EA) codes in the table (rows such as "17 C 33.1", or
  "IAF 38" in the heading). Some annexes list ISO 14001 by NACE code only (DNV S001, SGS S009,
  Eurofins S021, AKL S044, DEKRA S053). Those codes are classified to EA with the ESYD NACE table,
  and the scope note lists the NACE codes. ISO 22000 / FSSC 22000: ISO 22003-1 categories. ISO 50001:
  ISO 50003 technical areas. ISO 13485: IAF MD 8 main technical areas. All three are classified to
  EA with the ESYD tables. EN 15224: EA 38. ISO 3834 takes the IAF codes it is listed with, or for
  Kiwa S002 ("see ISO 9001 technical sectors") the ISO 9001 codes. Kiwa's ISO/IEC 20000-1 lists IAF 33.
  ISO/IEC 27001 / 27701 and ISO 22301 have no sector list ("No classification") and are recorded
  for all EA sectors.
- Not imported: PEFC FI forest certification (Finnish national scheme; DNV S001, Kiwa S002);
  EN 15593 food-packaging hygiene (only in combination with ISO 9001 / ISO 22000, not in CertiFind;
  S001, S002); AQAP 2110 (Kiwa S002); EU directive notified-body modules (pressure equipment
  2014/68/EU, radio equipment 2014/53/EU, legacy medical-device directives; SGS S009, Eurofins S021,
  DEKRA S053, Kiwa Tarkastus S056); vehicle type-approval technical service, category C (Kiwa
  S002, Testmill S051). Kiwa Tarkastus Oy (S056) holds only a pressure-equipment module and is left out.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | scrape_fi_finas.py | 18 registrations, 18 scope PDFs |
| 2026-11-06 | prepare_certifind.py + prune_inactive.py | 17 bodies, 30 accreditations, 57 scope rows |
