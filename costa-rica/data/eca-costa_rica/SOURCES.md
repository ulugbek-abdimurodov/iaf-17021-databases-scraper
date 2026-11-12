# ECA (Costa Rica)

Source: ECA register, https://eca.or.cr/organismos-de-certificacion-de-sistemas/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/costa_rica/scrape_cr_eca.py`, converted with `database/costa_rica/prepare_certifind.py`; skipped schemes in `database/costa_rica/eca_review.md`. `verified_at` empty.

- One OCSG registration = one accreditation per accreditation standard. `issue_date` = "Acreditado a partir del"; no expiry (indefinite).
- IAF sector codes taken from the international-recognition annex; ISO/IEC 27001 from the national annex.
- Not imported: INTE G38-3, ISO 28000, ISO 37001; ISO 22000/FSSC 22000 (reduced).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-10 | scrape_cr_eca.py | 1 registration, 2 scope PDFs |
| 2026-11-10 | prepare_certifind.py | 1 bodies, 3 accreditations, 5 scope rows |
