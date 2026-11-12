# JAB review — skipped schemes / bodies

Source: JAB Strapi API `/cms/api/certifications` (cert_num `CM*`, 34 management system CABs, register lastUpdate 2026-11-06).
No body was excluded entirely (every CAB holds ISO 9001, ISO 14001 or ISO 45001).

Skipped schemes (not in CertiFind scheme map):

| CAB | Scheme | Reason |
| --- | --- | --- |
| CM002, CM009, CM023, CM042 | AS-QMS (9100) | Aerospace QMS (IAQG), not mapped |
| CM002, CM009 | AS-QMS (9120) | Aerospace distributors, not mapped |
| CM009 | TL-QMS | TL 9000, not mapped |
| CM004, CM009, CM014 | JFS-C | Japanese food safety standard (JFSM), not mapped |
| CM058 | J-OHSMS | Japanese OHS specification (JIS Q 45100), not mapped |
| CM015, CM021, CM024 | AMS | Scheme section has no codes; not mapped |

Notes:
- ISO/IEC 27001 scope rows (CM044, CM059) have no EA codes: JAB lists ISMS without technical areas.
- CM028 QMS section contains stray tokens (`DQS`, `1500`) that were dropped.
- "Limited to / Except" restrictions are recorded per IAF code in `scope_note` (47 scope rows); full wording is in the proof PDF.
- Accreditation PDFs are scanned images (no text layer). Checked: they contain no email/contact data beyond the register fields, so they were not OCR-parsed.
