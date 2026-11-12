# IAS review log

## Bodies not imported (only out-of-scope schemes)

- MSCB-393 ALL ABOUT ESG SHPK (Albania): only ISO 39001
- MSCB-188 AMTIVO GROUP LIMITED (United Kingdom): only ISO 37301

## Schemes skipped (no CertiFind accreditation-standard mapping)

- ISO 20121: 2 — MSCB-193, MSCB-111
- ISO 21001: 5 — MSCB-366, MSCB-150, MSCB-131, MSCB-107, MSCB-153
- ISO 29993: 1 — MSCB-104
- ISO 37001: 19 — MSCB-212, MSCB-193, MSCB-253, MSCB-265, MSCB-113, MSCB-366, MSCB-224, MSCB-142, MSCB-196, MSCB-251, MSCB-240, MSCB-111, MSCB-150, MSCB-131, MSCB-107, MSCB-153, MSCB-231, MSCB-154, MSCB-404
- ISO 37301: 6 — MSCB-188, MSCB-193, MSCB-238, MSCB-251, MSCB-270, MSCB-107
- ISO 39001: 5 — MSCB-280, MSCB-393, MSCB-193, MSCB-320, MSCB-231
- ISO 41001: 5 — MSCB-212, MSCB-328, MSCB-254, MSCB-131, MSCB-231
- ISO 55001: 4 — MSCB-212, MSCB-328, MSCB-339, MSCB-273
- ISO/IEC 42001: 18 — MSCB-226, MSCB-312, MSCB-376, MSCB-193, MSCB-258, MSCB-352, MSCB-273, MSCB-416, MSCB-306, MSCB-290, MSCB-111, MSCB-356, MSCB-389, MSCB-267, MSCB-270, MSCB-218, MSCB-107, MSCB-231
- ISO/IEC TS 17021-10: 1 — MSCB-230

## Other notes

- Register row 'IGNYTE ASSURANCE LLC.' without a certificate link was a duplicate of MSCB-391; dropped.
- Suspended bodies (MSCB-277, -294, -335, -360): imported with status `suspended`; address left empty because the suspension watermark replaces page 1.
- Country is the register's country column (e.g. MSCB-283 listed SA with a Chinese address, MSCB-218 listed IN with a US address).
- ISO 50001 / 27001 / 27701 / 20000-1 / 22301 scopes carry no sectors in IAS annexes, so `ea_codes` is empty.
- Spurious 'Table A1.x' / letter matches outside ISO 13485 / ISO 22000 blocks were ignored.
