# GAC (GCC)

Source: GAC (GCC Accreditation Center) register of accredited bodies, https://gac.org.sa/accredited-bodies/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/gcc/scrape_gcc_gac.py`, converted with `database/gcc/prepare_certifind.py`; every skipped scheme is listed in `database/gcc/gac_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF that was read.

Extraction rules:
- One GAC registration (MSC 0001 … MSC 0029) is one accreditation under ISO/IEC 17021-1. `issue_date` is the "Accreditation Certificate Issue Date" in the PDF, `expiry_date` is "Valid Until" on the register.
- Country from the register card; address is Location 1 of the scope PDF; phone/email/website from the scope contact block.
- Accreditation standard per scheme as in the other datasets: ISO 22000 → ISO 22003-1 (certificate suffix " (22000)"); ISO 9001/14001/45001/13485 → ISO/IEC 17021-1. ISO 22000 categories mapped to EA via ISO 22003-1 table.
- Excluded: GPCA plastic pellets scheme (MSC 0015, MSC 0016).
