# ARMNAB scraper

Scrapes ARMNAB's register of accredited management-system certification bodies
(https://armnab.am/management-systems) and converts it into a CertiFind dataset.

Put this folder at `CertiFind/database/armenia`, next to `greece`.

## Setup and run

```
pip install -r requirements.txt
python armnab_scraper.py --download-docs
python prepare_certifind.py
python -m pytest
```

Nothing is imported into the database.

## armnab_scraper.py

Writes `output/bodies.csv`, `output/accreditations.csv`, `output/bodies.json` and `output/run_report.json`.

- The list page only serves its first 15 rows without a SignalR connection, so the scraper walks detail IDs from `MS00000001` and checks the total against the list page.
- Unknown IDs return HTTP 200 with "Չի գտնվել", which is treated as not found.
- Waits 0.3 s between requests, retries twice, and lists failures in `run_report.json`.
- `--download-docs` saves each detail page to `output/scope_documents/`, plus any linked PDF, Word or Excel file. Files already there are skipped. In November 2026 the site linked no certificate or annex files.

## prepare_certifind.py

Writes `bodies.csv`, `accreditations.csv` and `scopes.csv` to `../../certifind/data/armnab-armenia/`, and `output/REVIEW.md`.

Options: `--input`, `--dataset`, `--greece`, `--include-withdrawn`.

The mapping tables are loaded from `../greece/prepare_certifind.py`, so that file must define `NACE_TO_EA`, `NACE_SPANS`, `FOOD_CATEGORIES`, `ENERGY_AREAS`, `MEDICAL_AREAS`, `EXCLUDED_SCHEMES`, `SCHEMES` and `SECTOR_SCHEMES`.

The dataset needs ARMNAB and its standards in CertiFind's reference data: `V11__armnab_reference_data.sql`.

### Scope rules

- Scopes come from the page text: the scope block, plus the extension block.
- Reductions (inline decision notes, ending in `։` or `:`, and the reduction block) are applied per scheme: EA codes, ARMNAB sub-sectors, NACE sections (`ԲԱԺԻՆՆԵՐ C, G`) and ISO 50001 technical areas.
- EA codes are written in the importer's format (`1-3;5`). Sub-sectors (17.1, 29/1, ...) count as their EA sector; a partly held sector is named in the scope note.
- Food, energy and medical schemes use the Greek category tables, mapped to EA. Older FSSC 22000 scopes use ISO/TS 22003:2007 letters (L, M), which are mapped to the current categories.
- Accreditations are split by accreditation standard (Greek `SCHEMES`, plus ISO 22301 → ISO/IEC 17021-6, ISO 28000 → ISO 28003, ISO 20121 → ISO/IEC 17021-4); the extra rows get a suffix such as `006/M-012 (22000)`.
- A non-sector scheme with no sector rows gets `ALL`, as does a list of every NACE section A-S. A sector scheme (`SECTOR_SCHEMES`) with no sector rows is left out.
- OHSAS 18001 and other standards named in a scope (ISO 31000, HACCP, and so on) are listed in `REVIEW.md`, not written.
- Names are "English (Armenian)"; the English names are translations in `ENGLISH_NAMES`. `registration_no` and `verified_at` are left empty.
- Terminated records are left out: CertiFind allows one accreditation per body, accreditation body and accreditation standard, and ARMNAB keeps every renewal as a separate record. `--include-withdrawn` writes them for review, but the importer rejects that output.
- Lines the parser can't read go to `REVIEW.md`.

## Tests

`tests/` runs against a local mock site. `tests/build_fixtures.py` regenerates the fixtures, which use markup and text copied from armnab.am with long scope lists shortened. The converter tests load the real tables from `../greece/prepare_certifind.py` and are skipped without it.
