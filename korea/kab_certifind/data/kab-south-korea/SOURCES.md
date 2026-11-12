# KAB (South Korea)

Source: KAB register of accredited management system certification bodies, https://eng.kab.or.kr/eng/kcn/kcn/list.do (detail pages `view.do?orgIdx=<id>`), ISO/IEC 17021-1. Scraped with `database/south-korea/scrape_kr_kab.py`, converted with `database/south-korea/prepare_certifind.py`; skipped schemes are listed in `database/south-korea/kab_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` and `proof_url` are the body's KAB detail page (certificate PDFs use a date-bound token URL).

Extraction rules:
- Each KAB accreditation number per scheme (KAB-QC-01, KAB-EC-01, ...) is one accreditation. `issue_date` is the date shown next to the number; KAB publishes no expiry, so `expiry_date` is empty. `registration_no` is the body's ISO 9001 number.
- Phone, website and head-office address from the detail page; country "Republic of Korea" stripped from addresses.
- EA codes taken directly from the register for ISO 9001/14001/45001. ISO 22000/FSSC 22000 categories → EA via ISO 22003-1 mapping; ISO 13485 areas A–G → EA via IAF MD 8; ISO 22301 sector groups use the EA numbers listed. ISO/IEC 27001, 27701 and ISO 50001 carry no sector list (empty `ea_codes`).
- Accreditation standard per scheme: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000/FSSC → ISO 22003-1, ISO 22301 → ISO/IEC 17021-6, others → ISO/IEC 17021-1.
- Not added: TL 9000, KS Q 9100 (AS 9100), ISO 37001, ISO 37301, ISO 19443, ISO 42001, ISO 21001.
