# ENAC (Spain)

Source: ENAC (Entidad Nacional de Acreditación) register of accredited bodies, filtered to **Management System Certification** (ISO/IEC 17021-1), https://www.enac.es/web/english/accredited-bodies/products-and-services-searchs . Scraped with `database/spain/scrape_es_enac.py`, converted with `database/spain/prepare_certifind.py`; every skipped scheme and body is listed in `database/spain/enac_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register search page; `proof_url` is the ENAC Technical Annex PDF (`/documents/7020/<uuid>`) that was read.

Extraction rules:
- ENAC assigns a **separate accreditation number per scheme** (e.g. `01/C-SC003` quality, `01/C-MA001` environmental, `1/C-SG065` energy), not one base ID with suffixes. Each ENAC number is therefore kept as its own `certificate_number` in `accreditations.csv`/`scopes.csv` rather than being synthesised from a base ID. A body's `registration_no` in `bodies.csv` is its ISO 9001 (Calidad) number when it holds one, otherwise its first in-scope number.
- `issue_date` is the annex "Fecha de entrada en vigor / Coming into effect" date. `expiry_date` is empty: ENAC accreditations are open-ended and the annex states no expiry (status changes are published separately under Suspensions and withdrawals).
- Two portlet resource views of one search are combined: `destino=listado&delta=500` gives body name, address, phone, email and the annex PDF link for all results on one page; `destino=impresion` gives the ENAC number and Spanish scope title per row, in the same order. The two are index-aligned (verified: 0 mismatches over 131 rows).
- `country` is Spain for every body (all addresses are Spanish provinces). `address` is normalised to "street, postal-code city"; ALL-CAPS city names are title-cased. `website` is derived from the body's own e-mail domain (generic mailbox providers excluded) as the register listing carries no website field.
- Accreditation standard per scheme as in the other datasets: ISO/IEC 27001 → ISO/IEC 27006; ISO 50001 → ISO 50003; ISO 22000 → ISO 22003-1; ISO/IEC 20000-1 → ISO/IEC 20000-6; ISO 22301 → ISO/IEC 17021-6; ISO 9001 / 14001 / 45001 / 13485 → ISO/IEC 17021-1.
- EA/sector codes come from each Technical Annex: for ISO 9001 / 14001 / 45001 / 50001 / 22301 the annex lists IAF/EA sector codes directly (1-39); for ISO 22000 the food-chain categories (A-K) are mapped to EA via ISO 22003-1; for ISO 13485 the IAF MD 8 technical areas are mapped to EA. ISO/IEC 27001 (and 27701) and ISO/IEC 20000-1 annexes list the standard rather than sectors, so `ea_codes` is empty with an explanatory `scope_note` (accreditation is not sector-restricted).
- Not imported: schemes with no ISO/IEC 17021-1 CertiFind mapping — digital tachograph centres, end-of-waste, innovation management (UNE 166002), TEDAE aerospace scheme, criminal/general compliance (UNE 19601 / ISO 37301), PEFC forest management, anti-bribery (ISO 37001), aerospace quality (EN 9100), vehicle type-approval, asset management (ISO 55001). Four bodies holding only such schemes are dropped entirely (F2I2, NQA, PMM, TÜV SÜD AMT). See `enac_review.md`.

A note on access: in the Cowork sandbox the egress proxy blocks `enac.es` (HTTP 403), so the production run was executed through the browser (Claude in Chrome) against the identical portlet endpoints, with the Technical Annex PDFs fetched same-origin and parsed in-page with pdf.js using the logic reproduced in `scrape_es_enac.py`.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-06 | scrape_es_enac.py | 131 register rows, 95 in-scope annex PDFs read |
| 2026-11-06 | prepare_certifind.py | 28 bodies, 95 accreditations, 95 scope rows, 36 schemes excluded |
