# GAC review log

Register: https://gac.org.sa/accredited-bodies/ (filter: Accredited, Management System Certification) — 23 bodies.

## Excluded bodies (out-of-scope schemes only)
- MSC 0016 NATIONAL INSPECTION & TECHNICAL TESTING COMPANY (FAHSS), Saudi Arabia — GPCA plastic pellets/flakes/powders scheme (EMS) only.
- MSC 0015 DNV Business Assurance Group AS, Dubai Branch, UAE — GPCA plastic pellets scheme (EMS) only.

## Notes / manual checks
- MSC 0025 SGS Española de Control: ISO 9001 limited to IAF 35 (NACE 69, 74) for the OECD Free Trade Zone scheme; kept with scope_note.
- ISO 13485 scopes (MSC 0019, MSC 0012): technical areas not mapped; ea_codes empty.
- MSC 0014 TQA: issue date not in scope PDF (older layout); taken from the accreditation certificate PDF (19 October 2024).
- IAF codes were extracted from PDF table text; spot-check bodies with large code lists.
- Workspace had no network access to gac.org.sa; extraction ran in-browser (pdf.js) with the same logic as scrape_gcc_gac.py.

## Phone fixes (prepare_certifind.py)
- MSC 0005 Vision International Management Service: phone `+975 66 65 9810` does not start with +974 (Qatar); left empty.
- MSC 0018 United Quality Assurance Services LLC: phone `+9689944560` has the wrong length for +968; left empty.
- MSC 0011 QUALITAS DE CERTIFICATE WLL: phone `+966507879405` is a +966 number although the body is in Bahrain; kept.
- MSC 0018 United Quality Assurance Services LLC: only ISO 22000 (no ISO/IEC 17021-1 row); dropped by prune_inactive.
