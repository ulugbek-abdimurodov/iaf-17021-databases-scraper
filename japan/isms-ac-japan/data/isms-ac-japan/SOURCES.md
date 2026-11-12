# ISMS-AC (Japan)

Source: ISMS-AC registers of accredited certification bodies, https://isms.jp/english/lst/isr/isr.html (plus ITSMS, BCMS, PIMS and ISMS-PIMS lists), register dated 14 October 2026. Scraped with `database/japan/scrape_jp_isms-ac.py`, converted with `database/japan/prepare_certifind.py`; every skipped scheme is listed in `database/japan/isms-ac_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scheme list page.

Extraction rules:
- One ISMS-AC registration (ISR001, ITR005, BCR021, PIR022) is one accreditation. `issue_date` is the register's "Accr. date"; `expiry_date` is not published.
- All bodies are Japanese; address and website taken from the register entry.
- Accreditation standard per scheme: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6. ISMS-PIMS (27701) is added as a scope on the ISR certificate.
- Not added: ISO/IEC 27017 cloud add-on, ISO/IEC 42001 (AIMS), persons certification.
