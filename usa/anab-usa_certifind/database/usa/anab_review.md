# ANAB (United States) – review log

Run 2026-11-10. Directory: 113 management-system CBs across 32 standards; 113 scope PDFs parsed.

## Excluded bodies (only out-of-scope schemes)
| ANAB ID | Body | Schemes |
| --- | --- | --- |
| MS-3467 | Scientific Certification Systems, Inc., DBA SCS Global Services | SFI, ATFS |
| MS-1032 | Eurofins Assurance Audit and Certification Services US, LLC | FAMI-QS |
| MS-6950 | ISSPL Limited | ISO 28000 |
| MS-5479 | Speeki Pte. Ltd. | ISO 37001 |
| MS-1036 | Shanghai Ingeer Certification Assessment Co., Ltd | ISO 37301 |
| MS-4287 | Palindrome Technologies | ISO/IEC 42001 |
| MS-1033 | Zertia USA Corp. | ISO/IEC 42001 |
| MS-1431 | Averum, LLC | Leading Harvest |

## Skipped schemes on included bodies
AS9100/AS9110/AS9120 (AS9104/1 programme), AS6081, TL 9000, RC14001, ISO 15378, ISO 55001, ISO 37001, ISO 37301,
ISO 28000, ISO/IEC 42001, SFI, ATFS, R2, RIOS, BA 9000, SN 9001, e-Stewards, FAMI-QS, Leading Harvest – no CertiFind
scheme mapping. Per-body list is in `anab_raw.psv` (last column).

## Notes for manual check
- ISO 50001, ISO/IEC 27001/27701/20000-1, ISO 22301 scopes list no sectors → `ea_codes` empty.
- FSSC 22000 with no own category block on the PDF (6 bodies) → `ea_codes` empty.
- BLISS CB LLC (MS-1030): ISO 14001 listed without a sector block → empty.
- MS-1033 is used by both Emagine Compliance (included) and Zertia USA Corp. (excluded) in the directory titles.
- Viscount (MS-6115) PDF header prints MS-6116; directory ID kept.
- AEA Quality Registrars is a virtual office (address = "NY").
