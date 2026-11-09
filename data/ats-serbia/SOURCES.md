# ATS (Serbia)

Sources:

- Scopes: ATS (Akreditaciono telo Srbije) scope-of-accreditation PDFs for management-system
  certification bodies, file group 2-05 (`2-05-001.pdf` … `2-05-028.pdf`), saved in
  `database/serbia`.
- Contacts, status and expiry: the ATS register, searched for active 17021-1 certification
  bodies (`vrsta_akreditacije=13`, `status=A`),
  http://www.registar.ats.rs/?q=&status=A&suspendovan=1&vrsta_akreditacije=13, saved as
  `database/serbia/ats_register.html`. Its 17 bodies are exactly the 17 PDFs.

Converted with `database/serbia/prepare_certifind.py`, which prints every body, scope and
anything it could not match. Not yet verified by a person, so `verified_at` is empty.

```
python prepare_certifind.py --out <certifind>/data/ats-serbia
```

Extraction rules:

- `issue_date` is the PDF's "date of initial accreditation". For 08-001, 08-006 and 08-007
  the register shows a date one day later, which looks like a time-zone shift on the site,
  so the signed PDF is kept.
- `expiry_date` comes from the register, which includes extensions the PDFs predate:
  EVROCERT (08-002) is extended by decision 612/2026 from 2026-09-20 to 2026-12-20 at the
  latest, until ATS decides on reaccreditation. The other bodies' dates match the PDFs.
- `status` comes from the register: "Akreditovan" and "Bez suspenzije" = ACTIVE (all 17).
- ATS lists every scheme under one certificate (`08-0xx`); each extra accreditation
  standard gets its own row with a suffix, as in the other datasets: `(22000)` for ISO
  22000 (ISO 22003-1), `(27006)` for ISO/IEC 27001, `(50003)` for ISO 50001. ISO 13485
  stays on the 17021-1 row. SIQ Ljubljana's only scheme is ISO/IEC 27001, but it still gets
  the 17021-1 base row, which search requires.
- ISO 9001 / 14001 / 45001 sectors come from the "Област бр." (EA) column. Each row's
  NACE list was compared with IAF ID 1:2023; all of them match, so no scope is limited.
- ISO 22000 categories are classified to EA by sector, as in the RENAR, DPA, ESYD and EAK
  datasets: A, B = 1, C, D = 3, E = 30, F = 29, G = 31, I = 7, 14, 15, 17. ISO 13485 main
  technical areas (IAF MD 9) are classified as in the ESYD dataset.
- ISO/IEC 27001 and ISO 50001 annexes list no sectors and are recorded as `ALL`.
- `registration_no` is the register's PIB (Serbian tax ID); the Ministry of Defence's
  Military Quality Control has none. `website` is the register's "Web" field.
- `phone` is the first number of the body's "Tel" field, rewritten in international form
  (`+38111 3628188, 362 8189` → `+381 11 3628188`); CERTOP has none, so its contact
  person's mobile is used. `email` is the register's contact-person email (the register
  has no general address); PANCERT has none.
- `source_url` / `proof_url` are each body's register page (`/predmet/<id>/`).
- Names and addresses come from the PDFs, transliterated from Serbian Cyrillic to Latin.
  PANCERT's descriptive prefix "Društvo za sertifikaciju sistema menadžmenta" is dropped.
- `2-05-009.pdf` holds the same four pages twice; they are read once.
- SIQ Ljubljana (08-022) is a Slovenian body with an ATS accreditation, so its country is
  Slovenia.

Gaps:

- Two addresses differ between the PDF and the register; the PDF (dated 2026) is kept:
  WRG EUROPE (PDF Živka Davidovića 73A/32, register Koste Abraševića 27/2) and CERTOP CO
  (PDF Karađorđeva 62, register Lasla Gala 1, Kanjiža).
- File numbers 2-05-006 … 008, 012, 013, 015, 018 … 021 and 027 are neither in the folder
  nor in the active register (likely withdrawn).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-03 | prepare_certifind.py | 17 PDFs, 17 bodies (16 Serbia, 1 Slovenia), 31 accreditations, 61 scope rows |
| 2026-11-03 | prepare_certifind.py | ATS register: PIB, phone, email, website, register links, EVROCERT extension |
