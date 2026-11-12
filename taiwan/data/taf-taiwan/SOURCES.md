# TAF (Taiwan)

Source: TAF register of accredited bodies, https://www.taftw.org.tw/en/find-facility/scheme/msv/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/taiwan/scrape_tw_taf.py`, converted with `database/taiwan/prepare_certifind.py`; every skipped scheme is listed in `database/taiwan/taf_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the TAF scope page (`viewApplyItems.action?unitNo=<ID>&language=EN`) that was read.

Extraction rules:
- One TAF registration (MS001 … MS035) is one accreditation under ISO/IEC 17021-1. `issue_date` is "Originally Accredited", `expiry_date` is the end of "Effective Period".
- All 23 bodies are in Taiwan; address, phone, email and website come from the register list (trailing "R.O.C." removed).
- TAF item codes: `01xx` QMS, `02xx` EMS, `0301xx` OH&S (ISO 45001) — last two digits are the EA code. `0401<cat>` FSMS → ISO 22003-1 categories mapped to EA. `0501` ISMS (no EA). `06xx` EnMS → ISO 50003 technical areas mapped to EA.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 → ISO 22003-1, with certificate suffixes from `certifind_common.py`.
- Scope items with non-active status (one: MS007 ISO 9001 EA 4) are left out of `ea_codes` and noted in `scope_note`.
- Not added: TOSHMS (0302, national OSH scheme), Cyber Security Management Act scheme (0502), Water Efficiency MS (07).
