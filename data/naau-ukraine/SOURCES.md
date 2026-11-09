# NAAU (Ukraine)

Source: register of the National Accreditation Agency of Ukraine (Національне агентство з
акредитації України), https://naau.org.ua/en/3-reiestr-akreditovanikh-oov, list of
management-system certification bodies accredited to ДСТУ EN ISO/IEC 17021-1 (Ukrainian XLSX
and English DOC of 20.10.2026), and each body's scope annex ("Сфера акредитації") from the
Google Drive link in the register. Generated with `database/ukraine/naau_ms_scraper.py` and
`database/ukraine/prepare_certifind.py`; the parser's open points are in
`database/ukraine/naau_review.md`. Not yet verified by a person, so `verified_at` is empty.
The register has no page per body, so `source_url` is the register page and `proof_url` the
body's annex link.

Extraction rules:

- One register entry is one NAAU certificate (`8O001` …, written with a Latin O). Standards
  that other datasets accredit under their own scheme get their own accreditation row, as in
  the BAS dataset: ISO 22000 → ISO 22003-1 (`… (22000)`), ISO 50001 → ISO 50003 (`… (50003)`),
  ISO/IEC 27001 → ISO/IEC 27006 (`… (27006)`), ISO 37001 → ISO/IEC 17021-9 (`… (37001)`).
  Every body also keeps its ISO/IEC 17021-1 row (the register is the 17021-1 register), even
  without 17021-1 scopes (8O147), since search reads the scheme rows on top of it.
- ISO 9001 / 14001 / 45001 / 29001 and EN 15224 tables list "Порядковий № напрямку галузі
  економіки" with the sector name: the number is the IAF / EA code, and the names are the EA
  sector names, so codes are taken as written. Where the name narrows the sector
  ("Обмежено до …", or KVED codes in brackets; KVED is the Ukrainian NACE Rev. 2) the scope
  note says "Limited scope" and gives the restriction in English.
- One standard cell can name two standards for the same rows (8O081: ISO 9001 and ISO 29001;
  8O015, 8O050, 8O098, 8O113: ISO 9001 and EN 15224); each gets the rows.
- ISO 22000 tables list ISO 22003-1 food chain categories, ISO 50001 tables ISO 50003
  technical areas, ISO 13485 tables IAF MD 8 main technical areas. All three are classified to
  EA with the tables of the BAS / ESYD datasets, and the scope note names the categories.
- ISO 37001, ISO/IEC 27001 and ISO 22716 have no sector list in the annex and are recorded
  for all EA sectors.
- Not imported: NATO AQAP-2110 (8O048, 8O095, 8O117), and the notified-body modules of
  Ukrainian technical regulations (medical devices, machinery, lifts, pressure equipment,
  radio equipment, …), which are not management-system standards.
- 8O107: the register summary lists ISO 45001, the annex of 18.05.2026 does not; the annex
  is followed.
- Scanned annexes without text: those of active bodies 8O011, 8O043, 8O047 and 8O070 were
  read from the PDF by hand (`MANUAL` in the prepare script). Suspended bodies with scanned
  or missing annexes have no scope rows; search shows only active scopes anyway.
- Status: only `active` register entries are imported; `suspended`, `expired` and `cancelled`
  bodies are removed.
- Only bodies that currently hold a valid accreditation are kept: withdrawn, expired (including an active-listed row whose valid-to date has passed) and suspended bodies and rows are removed by `database/prune_inactive.py`, which the prepare script runs after writing the CSVs.
- Names: the register's English name as printed (NAAU's casing kept; Cyrillic look-alike
  letters inside Latin words corrected). No address, e-mail or website in the register.
  Phone: the first complete number, written +380 with the area code; two register numbers
  with too few or too many digits (8O165, 8O172) are left empty.
- `issue_date` is the first accreditation date, `expiry_date` the current certificate's
  valid-to date.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | naau_ms_scraper.py | 104 bodies: 64 active, 13 suspended, 27 expired or cancelled |
| 2026-11-04 | prune_inactive.py | removed 40 suspended, expired or cancelled bodies; 64 active bodies kept |
