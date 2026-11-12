# JSM (Malaysia)

Source: Department of Standards Malaysia (JSM), Accreditation of Certification Bodies register:
https://cab.jsm.gov.my/cab-directories/resultAcb

Schedule sample inspected:
https://cab.jsm.gov.my/documents/11396/300427/ACB0001

Extraction:
- The register provides programme-specific listings, body contact details, ACB numbers and schedule PDF links.
- The schedule PDF provides issue date, valid-until date, certification-body location, programme name, accreditation criteria, certification criteria and scope.
- One ACB schedule may contain multiple management-system programme scopes; the parser emits one accreditation/scope row per qualifying programme.
- Imported only when the programme is in the explicit allowlist and its PDF block contains ISO/IEC 17021-1.
- Scope PDFs use IAF ID 1 sector codes in the inspected sample. These are preserved in `scope_note`; `ea_codes` remains empty because the supplied helper has no verified IAF-to-EA crosswalk.
- `verified_at` is empty; rows are not manually verified.
- Skipped schemes and assumptions are listed in `database/malaysia/jsm_review.md`.

Run:
1. `python database/malaysia/scrape_my_jsm.py`
2. `python database/malaysia/prepare_certifind.py`

Dependencies: `requests`, `beautifulsoup4`, `lxml`, `pdfplumber`, and the existing project `certifind_common.py`.
