# CAEQ (Canada)

Source: CAEQ register of accredited organizations, https://caeq.ca/accredited-organizations/, management system certification bodies (ISO/IEC 17021-1). Scraped with `database/canada/scrape_ca_caeq.py`, converted with `database/canada/prepare_certifind.py`; every skipped scheme is listed in `database/canada/caeq_review.md`. `verified_at` empty.

Result: the register lists 20 bodies, all accredited only for organic / reserved-designation product certification (ISO/IEC 17065). No ISO/IEC 17021-1 accreditation exists, so `bodies.csv`, `accreditations.csv` and `scopes.csv` contain headers only.
