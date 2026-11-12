# ISMS-AC review log (scraped 2026-11-09, register dated 14 October 2026)

Skipped schemes (22 register rows):
- ISMS Cloud Security (ISO/IEC 27017 add-on, 20 rows: ISR001–ISR032 subset) — sector extension of ISO/IEC 27001, not a standalone scheme in CertiFind map.
- AIMS (ISO/IEC 42001, 2 rows: AIR015 TUV Rheinland Japan, AIR021 DFEII) — ISO/IEC 42001 not in SCHEME_ACCREDITATION_MAP.
- Persons certification bodies (ISO/IEC 17024) — out of scope, not scraped.

Notes:
- ISMS-PIMS (ISO/IEC 27701 extension) merged as an extra scope on the ISR certificate.
- JATE (ISR013) and BL-QE (ISR018): no website/address in register; left empty.
- No expiry dates or EA sectors published; `expiry_date` and `ea_codes` empty.
- Workspace HTTP to isms.jp is blocked; data collected through the browser, then parsed by prepare_certifind.py.
