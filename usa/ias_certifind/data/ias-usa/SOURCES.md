# IAS (United States)

Source: IAS register of accredited organizations, https://www.iasonline.org/search-accredited-organizations-2/ (program "Management Systems Certification Bodies", AC477), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/usa/scrape_us_ias.py`, converted with `database/usa/prepare_certifind.py`; every skipped scheme is listed in `database/usa/ias_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the certificate/scope PDF that was read.

Extraction rules:
- One IAS registration (MSCB-101 … MSCB-444) is one accreditation under ISO/IEC 17021-1. `issue_date` is the certificate "Effective Date", `expiry_date` is the register "Expires" column. Register status "Suspended (…)" → `suspended`, otherwise `active`.
- Bodies are worldwide (28 countries); `country` is the register country column. Address is taken from page 1 of the certificate PDF; website from the scope pages. No phone/email is published.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Annex layout: per "Certification Standard:" block; ISO 9001/14001/45001 list IAF/EA sectors as "NN: description"; ISO 13485 lists IAF MD 8 Tables A1.1–A1.7 (converted via MD8_TO_EA); ISO 22000/FSSC list ISO 22003-1 categories "C: …" (converted via ISO22003_TO_EA); ISO 50001, ISO/IEC 27001/27701/20000-1 and ISO 22301 show "Certification Sectors – N/A" (empty `ea_codes`).
- Not imported: ISO/IEC 42001, ISO 37001, ISO 37301, ISO 39001, ISO 41001, ISO 55001, ISO 21001, ISO 20121, ISO 29993, ISO/IEC TS 17021-10 schemes; bodies MSCB-393 and MSCB-188 (only such schemes).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_us_ias.py | 220 registrations, 220 certificate PDFs |
| 2026-11-10 | prepare_certifind.py | 218 bodies, 402 accreditations, 765 scope rows |
