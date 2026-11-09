# TUNAC (Tunisia)

Source: register of the Tunisian accreditation council (Conseil National d'Accréditation,
TUNAC), https://www.tunac.tn, domain "Cert.Management" (ISO/IEC 17021-1), and each body's
technical annex (F.C.48F / F.C.48E). Generated with `database/tunisia/tunac_scraper.py`;
the annexes are scanned PDFs without a text layer, so the sector tables were transcribed
by reading them. Not yet verified by a person, so `verified_at` is empty. `proof_url` is
the annex PDF on tunac.tn.

Extraction rules:

- One TUNAC accreditation number is one accreditation. TUNAC gives the food-safety scheme
  its own number (AFAQ 3-0007, STC Veritas 3-0015), recorded under ISO 22003-1. AFAQ's
  ISO/IEC 27001 scope sits in the 3-0003 annex and gets its own row `3-0003 (27006)`, as in
  the other datasets.
- ISO 9001 / 14001 / 45001 tables give the "Code IAF/EA", used as the EA code. The
  "Groupe Technique" column is ignored. Limits written in the annex (EA 7 "limité à
  l'industrie du papier et du carton", EA 17 "limité aux produits métalliques fabriqués")
  go in `scope_note`. Where EA 17 or EA 7 is listed twice with two different limits, it is
  recorded once with a note.
- ISO 22000 categories are classified to EA by sector, as in the other datasets:
  B = 1, C, D = 3, E = 30, K = 12, 13. Partial categories are noted.
- ISO/IEC 27001 has no sector list and is recorded as `ALL`.
- Not imported: the four bodies accredited only for PAFC Bassin du Congo forest management
  (Bureau Veritas Douala 3-0016, Control Union Italia 3-0018, SGS South Africa 3-0022,
  Preferred by Nature 3-0024), not an international management-system standard (as PEFC
  in the BAS and EAK datasets).
- The register lists STC Veritas twice (3-0006, 3-0015) and AFAQ AFNOR International twice
  (3-0003, 3-0007); each is one body here. Names are the annex's "Nom de l'organisme".
- `issue_date` / `expiry_date` are the register's current accreditation cycle
  ("Accrédité entre"), not the initial accreditation date. Phone and e-mail are the
  register's contact, rewritten in international form (`71806758` → `+216 71 806 758`).

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-04 | tunac_scraper.py | 4 bodies, 7 accreditations: INNORPI, AFAQ AFNOR International, STC Veritas, ICM |
