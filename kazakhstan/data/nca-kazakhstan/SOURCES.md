# NCA (Kazakhstan)

Source: NCA register of accreditation subjects (Реестр субъектов аккредитации), https://techreg.kezekte.kz/ru/acc/subjects, activity type "ОПС системы менеджмента" (ISO/IEC 17021-1). Scraped with `database/kazakhstan/scrape_kz_nca.py`, converted with `database/kazakhstan/prepare_certifind.py`; every skipped scheme/registration is listed in `database/kazakhstan/nca_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope annex download (Область аккредитации) for that attestat.

Extraction rules:
- One NCA attestat (KZ.Q.01.0720, KZ.Q.02.E0973, …) is one accreditation under ISO/IEC 17021-1. `issue_date` is "Дата начала действия АА", `expiry_date` is "Дата окончания действия АА". Only attestats with status "Действует" are imported; "Отозван" ones are logged in the review file.
- All bodies are in Kazakhstan; name = legal name with ТОО/АО form moved to an LLP/JSC suffix; phone, email and address (factual address, else legal) come from the register "Контактные данные" column. Websites are not published in the register.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 / 27701 → ISO/IEC 27006, ISO 50001 → ISO 50003, ISO 22000 / FSSC 22000 → ISO 22003-1, ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6.
- The annex is published as HTML tables on the subject page, one table per standard (СТ РК ISO 9001-2016 etc.). QMS/EMS/OHS tables list "IAF n" sectors (used directly as EA codes); ISO 22000 tables list ISO 22003 categories (A–K, some by name only) → EA via the category map; ISO 50001 tables list ISO 50003 technical areas by name → EA via the area map.
- Not imported: OHSAS 18001, ISO/TS 29001, ST RK 1179, ST RK 1352, GOST/ST RK 12.0.x; 49 withdrawn attestats.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-09 | scrape_kz_nca.py (browser run) | 58 registrations, 57 scope pages |
| 2026-11-09 | prepare_certifind.py | 9 bodies, 14 accreditations, 26 scope rows |
