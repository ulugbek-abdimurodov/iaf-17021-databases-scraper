# ESYD ISO/IEC 17021-1 scraper

Downloads every body accredited for ISO/IEC 17021-1 from the register of the
Hellenic Accreditation System (ESYD), at http://www.esydops.gr/portal/p/esyd/en/.

## Run

Requires Python 3.10+.

```
pip install -r requirements.txt
python esyd_scraper.py
```

A full run should take a few minutes, with 0.3 s between requests.

Expected result, from a check of the live site in a browser on 2 November 2026:
147 bodies in the catalogue, 62 with 17021, and 389 accreditation rows. The site's
search returned 63, because it also lists INTERNATIONAL CERTIFICATION BODY SA (IQC, id
17953), whose detail page shows only ELOT EN 45011. IQC is therefore excluded.

| Option | Purpose |
| --- | --- |
| `--download-docs en\|el\|both` | Also download the scope-of-accreditation `.doc` files. Re-running resumes. |
| `-o FOLDER` | Output folder (default `output`). |
| `--limit N` | Check only the first N catalogue bodies, for a quick trial. |
| `--delay SECONDS` | Time between requests. |

## Output

| File | Contents |
| --- | --- |
| `bodies.csv` | One row per body: contact details, certificate numbers, scope count. |
| `accreditations.csv` | One row per 17021 accreditation field: certificate, date, scope document links. |
| `bodies.json` | The same data, nested. |
| `run_report.json` | Counts, errors and the search cross-check. |
| `scope_documents/` | Scope files by body, with `--download-docs`. |

The CSV files open directly in Excel with Greek intact. The exit code is 1 if any
body or document failed, and those failures are listed in `run_report.json`.

## How bodies are selected

The scraper checks all bodies in the catalogue and keeps those with a row under the
17021 standard on their detail page. Only 17021 rows are kept, so a body's 17020 or
17024 accreditations do not appear.

- **Labelling:** ESYD's accreditation tables and search say "ELOT EN ISO/IEC 17021",
  while its overview page calls the same scheme "ELOT EN ISO/IEC 17021-1". The filter
  accepts `17021` and `17021-1`, and rejects `17021-2`, `17021-3` and so on.
- **Search disagreements:** the site's search for the standard is run as a cross-check.
  If it disagrees with a detail page, the detail page wins and the body is listed in
  `run_report.json`.
- **Blank field names:** some English rows have no field name. They are filled from
  the Greek page and marked `field_language = el`.
- **Blank certificate data:** some rows have no certificate number or date on the
  site. These stay blank.

## Tests

```
pip install pytest
pytest
```

The tests run the whole scraper against a local mock of the site, built from the
HTML structure of the live pages.

## Preparing the CertiFind dataset

`prepare_certifind.py` turns the scraper output and the scope annexes into the CertiFind
dataset `certifind/data/esyd-greece` (bodies, accreditations, scopes). It reads the
annexes with `worddoc.py`, which handles both real `.doc` files and the `.docx` files the
site also serves under a `.doc` name.

```
pip install -r requirements.txt olefile
python esyd_scraper.py --download-docs en
python prepare_certifind.py --download-el --out ../../certifind/data/esyd-greece
```

`--download-el` fetches the Greek annex wherever the English one is missing (the site
returns 404 for some). The script also writes `output/REVIEW.md`, which lists every
mapping, merge, fallback and cleaned value. Read it after each run.

Then load it from `certifind/backend` (migration `V5__esyd_reference_data.sql` adds ESYD
and the new standards):

```
.\mvnw.cmd spring-boot:run "-Dspring-boot.run.profiles=import" "-Dspring-boot.run.arguments=--certifind.import.paths=../data/esyd-greece --certifind.import.dry-run=true"
```

Drop `--certifind.import.dry-run=true` to import for real. The extraction rules are in
`certifind/data/esyd-greece/SOURCES.md`.

First import, 3 November 2026: 61 bodies, 196 accreditations, 392 scope rows
(9,148 standard x sector rights).

## To review before accepting the data

None of this is verified by a person yet (`verified_at` is empty for every body).
Check these and tick them off here:

- [ ] **Category-to-EA mappings (drafts).** Food safety categories, ISO 50001 technical
  areas, ISO 13485 technical areas and EU-directive product families are converted to EA
  sectors with the tables `FOOD_CATEGORIES`, `ENERGY_AREAS`, `MEDICAL_AREAS` and
  `DIRECTIVE_FAMILIES` in `prepare_certifind.py`. The first three are shared with the
  RENAR, DPA and TÜRKAK datasets. REVIEW.md, section "Draft EA mappings" (86 rows), lists
  every use.
- [ ] **NACE-to-EA table.** Some ISO 14001 annexes (EQA, EUROCERT, LETRINA and others)
  list NACE codes, converted with `NACE_TO_EA` (written from the IAF ID 1 table). Check it
  against the official IAF ID 1 document, especially divisions 33, 37-39, 63 and 74-82.
- [ ] **EU directives scheme ("EU Directives QA"), 8 bodies.** These are notified-body
  quality-assurance modules (pressure equipment, lifts, medical devices, recreational
  craft), not a management-system standard. Decide whether CertiFind should show them at
  all. Today they are searchable under EA 17-18 (pressure equipment, lifts), 13-14 and 19
  (medical devices) and 20 (recreational craft).
- [ ] **"All sectors" schemes.** 135 annexes have no sector list (27001, 37001, 39001,
  37301, 41001, 55001, EN 15224, ELOT 1429/1435, ...) and are recorded as ALL, as in the
  other countries. EN 15224 (healthcare) might be better limited to its sector.
- [ ] **Delta Cert merge.** The two register entries (432090, the 2024 partnership, and
  444089, the 2025 single-member company) were merged into 444089, on the assumption that
  the company replaced the partnership. Confirm with ESYD or the company. The merge is
  `MERGE_BODIES` in `prepare_certifind.py`.
- [ ] **Accreditation standard choices.** ISO 37001 and ISO 39001 are put under ISO/IEC
  17021-9 and 17021-7 (as in the DPA dataset), ISO 22301 under 17021-1 (as in TÜRKAK).
  ESYD itself labels everything "ELOT EN ISO/IEC 17021".
- [ ] **Spot-check a few bodies** against their ESYD page and annexes: sectors, certificate
  number, dates and contacts. Then fill in `verified_at` for the ones you checked.

## Do not forget

Things that are incomplete or will go stale:

- **Expiry dates left empty (13 bodies).** For 10, the latest date in the annexes is
  already past while ESYD still lists the body, so the annexes were probably not reissued
  after a renewal: A CERT, LETRINA, MIRTEC, DQS HELLAS, NOVA CERTIFICATIONS, ERGOCERT,
  COSMOCERT, SWISS APPROVAL, GLOBAL CERT, KYROS. For 3, no annex gives a date: Hellenic
  Lloyd's, PPC INSPECTRA, FQM. Ask ESYD or look at the certificates. An empty expiry means
  the body never expires in search.
- **Missing annexes (19).** These return 404 in both English and Greek:
  - Sector schemes (12 annexes, 7 bodies), which get **no scope rows**: UCERT (22000),
    BQV (14001, and its separate ISO 50003 row; the 50001 row has sectors), Hellenic
    Lloyd's (50001), PPC INSPECTRA (9001, 14001, 45001), Delta Cert (9001 and 22000 of the
    older entry; the newer entry's annexes have sectors), SI CERT (22000), FQM (9001,
    14001). So PPC INSPECTRA, FQM, UCERT 22000, SI CERT 22000 and BQV 14001 do not
    appear in search for those standards.
  - Schemes without a sector list (7 annexes), recorded as ALL anyway: Bureau Veritas
    (39001, ELOT 1435), ISONIKE (one of its two 37001 rows), BQV (37001), Health Cert,
    MEGNUSCERT and SI CERT (27001).

  Re-run the scraper later, because ESYD may publish them.
- **Hellenic Lloyd's** (id 17649) has one ISO 50001 row with no date, number or annex. It
  is imported as a body without an accreditation and never appears in search.
- **Placeholder certificate number.** FQM (id 451101) has no number anywhere and uses
  `ESYD-451101`. Replace it when ESYD publishes one. The importer then withdraws the old
  row and inserts a new one.
- **Status is always ACTIVE.** The register shows no suspensions. A body that disappears
  from the register is withdrawn by the importer on the next run.
- **One contact per body.** Only the first phone number and one email are kept. The others
  are in `output/bodies.csv` and in REVIEW.md ("Normalised values").
- **Other datasets.** ISO 46001 is now a CertiFind standard. The TÜRKAK dataset still
  skips it (`STANDARD_PATTERNS` / `SCHEMES` in `turkak-scraper/prepare_certifind.py`).
- **Re-run regularly.** ESYD reissues annexes often (several were dated September 2026).
  Re-run the three commands above and read the new REVIEW.md before importing.
