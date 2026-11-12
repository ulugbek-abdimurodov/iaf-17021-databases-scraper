# UAF (United States)

Source: UAF register of accredited CABs, https://www.uafaccreditation.org/directory/listofAccreditedCabs (API newprodapi.uafaccreditation.org), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/united-states/scrape_us_uaf.py`, converted with `database/united-states/prepare_certifind.py`; every skipped scheme is listed in `database/united-states/uaf_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the CAB details page; `proof_url` is the certificate & schedule PDF that was read.

Extraction rules:
- UAF issues one accreditation number per scheme (e.g. 51810410121); each is one accreditation under ISO/IEC 17021-1 (or the scheme-specific standard). `issue_date` is "Accreditation Valid Date", `expiry_date` is "Accreditation Valid Up to"; status `expired` if expiry < retrieval date. `registration_no` is the UAF CAB short code.
- Country/address/contact from the CAB's primary key location in the API; bodies in all countries kept.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Scope: IAF codes 1–39 listed per scheme; FSMS ISO 22003-1 categories and ISO 13485 IAF MD 8 main technical areas converted to EA.
- Not imported: ABMS, AIMS, FMMS, AMS, EOMS, ESMS, CMS, MDD/MDR/IVDR, GHG, inspection/lab/product schedules; International Conformity Assessment services Inc (AMS only).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_us_uaf.py | 64 CABs, 69 schedule PDFs |
| 2026-11-10 | prepare_certifind.py | 63 bodies, 281 accreditations, 281 scope rows |
