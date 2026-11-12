# OSA (El Salvador)

Source: OSA register of accredited certification bodies, https://www.osa.gob.sv/organismos-de-certificacion-acreditados/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/el_salvador/scrape_sv_osa.py`, converted with `database/el_salvador/prepare_certifind.py`; every skipped scheme is listed in `database/el_salvador/osa_review.md`. Not yet verified by a person, so `verified_at` is empty. `source_url` is the register page; `proof_url` is the scope PDF page that was read.

Extraction rules:
- One OSA registration (OCA-01:07, OCA-01:15) is one accreditation under ISO/IEC 17021-1. `issue_date`/`expiry_date` are the start/end of "Vigencia de la acreditación".
- Country, address, phone, email and website come from the header of the scope PDF (F 9.1.29).
- Sectors are IAF/EA codes listed in the PDF ("Sector NN").
- Accreditation standard per scheme as in the other datasets. Not added: ISO 37001.
