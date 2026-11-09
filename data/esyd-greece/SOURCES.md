# ESYD (Greece)

Source: ESYD register of ISO/IEC 17021 certification bodies,
http://www.esydops.gr/portal/p/esyd/en/, and the scope-of-accreditation annexes linked
from each body's page. Generated with `database/greece/esyd_scraper.py` and
`database/greece/prepare_certifind.py`; every mapping, merge, fallback and cleaned value
is listed in `database/greece/output/REVIEW.md`. Not yet verified by a person, so
`verified_at` is empty.

Extraction rules:

- One register row is one scheme of a body; its annex gives the sectors, the certificate
  number and the expiry date. ESYD lists every scheme under one 17021 certificate, so the
  accreditation standard is chosen per scheme as in the other datasets (27006, 50003,
  22003-1, 20000-6, 42006, 17021-7 for ISO 39001, 17021-9 for ISO 37001).
- Sector lists come from the annexes' IAF/EA column. ISO 14001 annexes that list NACE
  codes are converted with the IAF ID 1 table; NACE divisions IAF ID 1 splits over several
  sectors (30, 33, 35, 58, 95) map to all of them as limited scopes.
- ISO 22000 / FSSC 22000 categories, ISO 50003 technical areas and ISO 13485 technical
  areas are classified to EA by sector, as in the RENAR, DPA and TÜRKAK datasets.
- Annexes without a sector list are recorded as `ALL`. Sector schemes whose annex is
  missing get no scope row.
- Not imported: Greek national schemes (ELOT 1429, ELOT 1435, AGRO 2) and EU-directive
  notified-body modules, which are not international management-system standards.
- An expiry date already in the past is kept, even while ESYD still lists the body, so the body
  counts as expired and is removed (10 bodies on 2026-11-04). Bodies with only a scheme
  accreditation and no ISO/IEC 17021-1 row (RTA HELLAS, QS HELLAS) are removed too.
- Only bodies that currently hold a valid accreditation are kept: withdrawn, expired (including an active-listed row whose valid-to date has passed) and suspended bodies and rows are removed by `database/prune_inactive.py`, which the prepare script runs after writing the CSVs.
- Contacts: the first phone number and one email per body.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-03 | esyd_scraper.py | 62 bodies with 17021, 389 register rows; 61 bodies after merging Delta Cert |
| 2026-11-04 | prune_inactive.py | removed 10 expired bodies and 2 without a 17021-1 row; 48 bodies kept |
