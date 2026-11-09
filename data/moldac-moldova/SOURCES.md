# MOLDAC (Moldova)

Source: MOLDAC register of management-system certification bodies (OCsm),
https://www.acreditare.md, and the signed accreditation certificates and annexes.
Transcribed by hand. Not yet verified by a person, so `verified_at` is empty.

Transcription rules:

- `issue_date` is the current accreditation date (initial date when never renewed),
  `expiry_date` the certificate's expiry date. Every row of a certificate shares them.
- `registration_no` is the CUIIO code printed on the certificate.
- Sector lists come from the "Cod IAF" column of each annex.
- ISO 22000 categories are classified to EA codes by sector, as in the RENAR and DPA
  datasets: C = 3, F = 29, G = 31.
- NACE exclusions in the annexes are recorded in `scope_note`.
- `proof_url` and `source_url` are the MOLDAC home page; replace them with the
  certificate's own URL when known.
- ISO 14001 (17021-2) and ISO 45001 (17021-10) are level-4 standards under the same
  ISO/IEC 17021-1 accreditation, so their scopes sit on the 17021-1 row, as in RENAR.

Documents transcribed: OCsm-001 certificate (06.01.2026), Annex 1 ISO 9001 (06.01.2026),
Annex 2 ISO 22000 (23.07.2025); OCsm-004 certificate (17.10.2025), Annex 1 ISO 9001
(12.06.2025), Annex 2 ISO 14001 and Annex 3 ISO 45001 (17.10.2025).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-02 | (by hand) | All certificates and annexes of OCsm-001 and OCsm-004 |
