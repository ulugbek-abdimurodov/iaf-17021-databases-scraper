# Swedac (Sweden)

Source: [Swedac accreditation register](https://ackrediteringar.swedac.se/en), management-system
certification entries under SS-EN ISO/IEC 17021-1:2015. The source was collected by
`database/sweden/swedac_ms_scraper.py` and converted by
`database/sweden/prepare_certifind.py`.

The converter uses Swedac's structured scope columns. IAF sectors are retained for ISO 9001,
ISO 14001, and ISO 45001; ISO 22000/FSSC 22000 food categories, ISO 50001 technical areas,
and ISO 13485 medical-device areas are classified to EA sectors. EN 15224 is classified to
EA 38. Entries without a sector list use all EA sectors.

National, product/notified-body, forestry, welding, accessibility, personal-data, and road-safety
schemes are left out. Every skipped section and invalid phone is listed in
`database/sweden/swedac_review.md`. Two registrations with no importable management-system
standard were omitted.

| Retrieved | Bodies | Accreditations | Scope rows |
| --- | ---: | ---: | ---: |
| 2026-11-05 | 16 | 34 | 67 |
