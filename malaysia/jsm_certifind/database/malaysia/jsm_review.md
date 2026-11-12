# JSM review notes

## Initial inspection (2026-11-09)
- Live register: https://cab.jsm.gov.my/cab-directories/resultAcb
- The visible browser result was filtered to Quality Management Systems (QMS), status ACCREDITED, and showed 34 records. This is not a complete inventory.
- Individual schedule link pattern observed: `https://cab.jsm.gov.my/documents/11396/300427/ACB0001`.
- Sample ACB 001 schedule: 55 pages; schedule issue date 18 September 2026; valid until 16 February 2030. It lists multiple programmes and separate programme-specific scopes.
- QMS sample block explicitly lists ISO/IEC 17021-1:2015, ISO 9001:2015, and IAF ID 1 sector codes.
- The sample also includes ISO 14001, ISO 45001, ISO/IEC 27001, ISO 13485, ISO 50001, and other schemes. Do not equate every programme on a schedule with ISO/IEC 17021-1 eligibility.

## Assumptions
- Search each programme/status combination discovered from the register form.
- Import only explicitly mapped management-system standards with explicit ISO/IEC 17021-1 evidence in the relevant PDF programme block.
- Keep non-allowlisted schemes in the review log rather than silently mapping them.
- The schedule lists IAF ID 1 codes, not necessarily NACE or EA codes. Do not write IAF codes into the `ea_codes` column.
- The provided helper module has no IAF-to-EA crosswalk. EA values therefore remain blank until a validated crosswalk is added.
- The register's body address is the body location; it does not establish that every CAB operates in every country. Foreign countries should only be recorded where the register/schedule explicitly identifies them.

## DevTools fallback
If the automated form discovery fails, open DevTools → Network → Fetch/XHR, clear the log, submit one programme filter (e.g. QMS + ACCREDITED), then copy:
1. the request URL and HTTP method;
2. the full request payload/form data (including CSRF token fields);
3. a small JSON/HTML response sample containing one result row and its schedule link.
