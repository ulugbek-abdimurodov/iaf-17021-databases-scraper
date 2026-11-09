# ALGERAC (Algeria)

Sources:

- Certificates and technical annexes: ALGERAC (Organisme Algérien d'Accréditation)
  "Certificat et Annexe Technique" PDFs for management-system certification bodies, file
  group 3-1 (`3-1-001`, `3-1-006` … `3-1-009`), saved in `database/algeria`. Page 1 is a
  scanned certificate (read by eye); the annex pages are text.
- Register: https://algerac.dz/organismes-de-certification/ lists exactly these five bodies
  and links the same PDF files. The general list "LIS 04 Liste des organismes accrédités"
  (updated 2026-10-28), section 4 "Activité de Certification Systèmes de Management", has
  the same five bodies, numbers and dates, with no suspension noted.

Transcribed by hand. Not yet verified by a person, so `verified_at` is empty.

Transcription rules:

- `issue_date` is the certificate's "Date d'octroi de l'accréditation initiale";
  `expiry_date` is its "Date de fin de validité" (the annex and the LIS 04 list agree).
- ISO 9001, 14001 and 45001 share the ISO/IEC 17021-1 row. ISO 22000 gets its own row
  under ISO 22003-1 with the suffix `(22000)`, as in the other datasets (BCI, INTERTEK).
- Sectors come from the annexes' "Code EA/IAF" column. The text layer shifts the
  descriptions against the codes, so codes were counted against descriptions for every
  table (all match). The "Cluster technique" column is ignored.
- ISO 22000 categories are classified to EA by sector, as in the other datasets: C = 3.
  Both bodies hold only part of category C (BCI: CIV; INTERTEK: CII and CIV), noted in
  `scope_note`.
- EA 17 appears twice in the ALICEF and SGS ISO 14001 / 45001 annexes, once "limitée à la
  fabrication des produits métaux" and once "limité à la production de métaux de base".
  Together they cover the sector, so it is recorded as EA 17 with a note.
- INTERTEK's EA 7 is limited: ISO 9001 to paper production and pulp and paper
  manufacture, ISO 14001 to paper production. Both are noted in `scope_note`.
- `phone` and `email` are the annex's "Site concerné" contact, rewritten in international
  form (`0770 03 33 44` → `+213 770 03 33 44`, `00 213 23 700 041` → `+213 23 70 00 41`).
  ALICEF lists two numbers; the first is kept.
- Names and addresses come from the certificate page.
- `source_url` is the ALGERAC register page; `proof_url` is each body's certificate PDF on
  algerac.dz.

Gaps:

- No registration number (NIF/RC) or website is published; `registration_no` and
  `website` are empty.
- Numbers 3-1-002 … 3-1-005 are not on the register (likely withdrawn or expired).
- `database/algeria` holds the INTERTEK PDF twice (`… (1).pdf` is byte-identical).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-03 | hand transcription | 5 PDFs, 5 bodies, 7 accreditations, 14 scope rows; checked against the algerac.dz register and LIS 04 (28/10/2026) |
