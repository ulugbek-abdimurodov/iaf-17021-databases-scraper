# JAB (Japan)

Source: JAB register of accredited certification bodies, https://www.jab.or.jp/en/certification_institutions (Strapi API `https://www.jab.or.jp/cms/api/certifications`, cert_num `CM*`), management system certification bodies (ISO/IEC 17021-1). Scraped with `database/japan/scrape_jp_jab.py`, converted with `database/japan/prepare_certifind.py`; every skipped scheme is listed in `database/japan/jab_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the English accreditation certificate/scope PDF.

Extraction rules:
- One JAB registration (CM001, CM059 …) is one accreditation under ISO/IEC 17021-1. `issue_date` is `init_cert_date`, `expiry_date` is `exp_date`.
- Name, address, phone and website from the English register fields (`en_name`, `en_location`, `en_contact_tel`, `url`); country taken from the address tail (Japan; Perry Johnson Registrars → United States). No email is published.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- Scope from `en_cert_scope`, split by `=== <scheme> ===` headers: QMS/EMS/OHSMS lines start with IAF/EA codes; FSMS/FSSC lines with ISO 22003-1 categories (mapped to EA); MD-QMS lines with IAF MD 8 areas 1–7 (mapped to EA).
- `scope_note` lists IAF codes carrying "Limited to" or "Except" restrictions. PDFs are scanned images with the same content as the register; no emails are published by JAB.
- Not imported: AS-QMS (9100/9120), TL-QMS, JFS-C, J-OHSMS, AMS.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_jp_jab.py | 34 registrations, live API; 34 scope PDFs downloaded and checked (scanned, no extra contact data) |
| 2026-11-09 | prepare_certifind.py | 34 bodies, 45 accreditations, 97 scope rows |
