# MNAS (Mongolia)

Source: MNAS register of accredited bodies, https://e-accreditation.gov.mn/login (public list, POST /ref/list, /ref/show), management system certification bodies (MNS ISO/IEC 17021-1). Scraped with `database/mongolia/scrape_mn_mnas.py`, converted with `database/mongolia/prepare_certifind.py`; every skipped scheme is listed in `database/mongolia/mnas_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the accreditation certificate PDF that was read.

Extraction rules:
- One MNAS registration (MSC 01 … MSC 08) is one accreditation under ISO/IEC 17021-1. `issue_date` / `expiry_date` are the register's accredited / expiry dates.
- Phone and email from the register detail; address translated from the certificate header (Mongolian); names in English transliteration.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Certificates list IAF (=EA) codes per scheme; ISO 22000 food-chain categories mapped to EA; ISO/IEC 27001 has no sector restriction.
- Not imported: ISO 37001 (MSC 03).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_mn_mnas.py | 7 registrations, 7 certificate PDFs |
| 2026-11-09 | prepare_certifind.py | 7 bodies, 17 accreditations, 28 scope rows |
