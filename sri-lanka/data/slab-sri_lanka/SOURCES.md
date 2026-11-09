# SLAB (Sri Lanka)

Source: SLAB register of accredited operators, https://www.slab.lk/directory (scheme "Certification bodies – System", status Active), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/sri_lanka/scrape_lk_slab.py`, converted with `database/sri_lanka/prepare_certifind.py`; open items in `database/sri_lanka/slab_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the registry profile; `proof_url` is the scope PDF.

Extraction rules:
- One SLAB registration (QMS 001-01, FMS 010-01, …) is one accreditation; `issue_date`/`expiry_date` are the profile validity period.
- Country Sri Lanka for all bodies; the register gives no address or contacts.
- Accreditation standard per scheme: ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 → ISO 22003-1.
- EA codes not yet extracted from scope PDFs.
- Not imported: inactive registrations.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_lk_slab.py (browser capture) | 27 registrations, 42 scope PDFs listed |
| 2026-11-09 | prepare_certifind.py | 8 bodies, 27 accreditations, 27 scope rows |
