# JASANZ (Australia / New Zealand)

Source: JASANZ register of accredited bodies, https://register.jasanz.org/accredited-bodies (public JSON API `jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/` — GetFilteredCABRegister, GetCABsInformation, CabSchemeScopeDetails), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/australia/scrape_au_jasanz.py`, converted with `database/australia/prepare_certifind.py`; every skipped scheme/body is listed in `database/australia/jasanz_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` and `proof_url` are the register page (scope data comes from the API, no PDFs).

Extraction rules:
- One JASANZ accreditation number (e.g. M1900799IM) is the base ID. `issue_date` is "Last Accreditation Issued", `expiry_date` is "Accreditation Expiry Date".
- Country/address/contacts come from the CAB's head-office location (all countries kept; Korea → South Korea, Viet Nam → Vietnam, Taiwan Province of China → Taiwan).
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, others → ISO/IEC 17021-1.
- EA codes: register technical sectors (IAF/EA numbers) used directly; ISO 22000/FSSC food chain categories mapped via ISO 22003-1; ISO 13485 technical areas via IAF MD 8. ISO/IEC 27001, 20000-1 and 50001 have no sectors in the register (empty `ea_codes`).
- Deliberately not added: product, personnel, food/organic/halal, NDIS/human-services, CodeMark, GLOBALG.A.P., SQF, ISO 55001, ISO/IEC 42001 and other non-mapped schemes.
