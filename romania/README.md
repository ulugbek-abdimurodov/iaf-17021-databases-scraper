# romania_scraper

Scrapes RENAR (https://www.renar.ro/index.php/oec) for accredited management-system
certification bodies, categories **5.2.1 – 5.2.8** (~92 records as of Oct 2026).

For each company: name, address, city, phone, fax, email, website, standard
(Referențial), certificate no., status, issue date, expiration date, and the
**Certificat** and **Anexa** PDFs when published.

## Run
Windows: double-click `run.bat` · macOS/Linux: `./run.sh`
(or `pip install -r requirements.txt` then `python scraper.py`)

## Options
| flag | meaning |
|---|---|
| `--acts 8 9` | only some categories (8=5.2.1 Calitate, 9=5.2.2 Mediu, 10=5.2.3 Dispozitive medicale, 11=5.2.4 SSM, 12=5.2.5 Energie, 13=5.2.6 Securitatea informației, 7=5.2.7 Siguranța alimentelor, 22=5.2.8 Anti-mită) |
| `--status ACC` | only accredited (`SUSP`, `RETR_P`, `RETR` also available) |
| `--no-pdfs` | data only |
| `--workers 4 --delay 0.5` | politeness / speed |
| `--out output` | output folder |

## Output (`output/`)
- `companies.xlsx`, `companies.csv` (UTF‑8, Excel friendly), `companies.json`
- `pdfs/<category>/<Company>__<cert no>/Certificat.pdf`, `Anexa.pdf`
- `scraper.log`

Re-running is safe: already downloaded PDFs are skipped.
A company accredited in several categories appears once per category.

## Extracting the PDFs → CSV + SQL (`extract_renar.py`)
```
python extract_renar.py output/pdfs --out output/extracted [--debug]
```
Reads every PDF under the folder (recursively), splits each into certificate and annex
pages, and merges them by RENAR certificate number (`SM 003`), so the separate
`Certificat.pdf` / `Anexa.pdf` files of a company end up together. Identical copies (the
same certificate saved under several categories) are read once.

Writes to `--out`: `certification_bodies.csv`, `accreditations.csv`,
`accredited_scopes.csv`, `review.csv` (everything missing, defaulted, inferred or OCR'd),
and `seed_romania.sql`. `--debug` also saves each PDF's raw text in `debug/`, which helps
when tuning the regexes in the `PATTERNS` section at the top of the script.
`source_pdf` is the path relative to the input folder, because every file is named
`Certificat.pdf` or `Anexa.pdf`.

### v2: database export (`extract_renar_v2.py`)
```
python extract_renar_v2.py output/pdfs --out output/db [--debug]
pytest tests
```
Groups everything by certificate number. One company gets one `certification_bodies` row,
named `LEGAL NAME (trade name after "prin")`. It gets one `accreditations` row per scheme:
ISO/IEC 17021-1 always (`SM 112`), plus ISO/IEC 27006 (`SM 112 (27006)`), ISO 50003
(`(50001)`), ISO 22003-1 (`(22000)`), ISO/IEC 17021-9 (`(37001)`), … decided by each annex's
supplementary and certification standards. It gets one `accredited_scopes` row per annex,
holding the IAF/EA codes from the annex's "Nr. IAF" column. Annexes without one (27001,
13485, 50001, 22000, 37001, …) get 1–39 and a note.
The PDFs are the source of truth. Folder names are only cross-checked: the category's expected
standard and the certificate number. Every mismatch, gap, duplicate, default and OCR'd page
goes to `review.csv`. `--debug` writes each PDF's text and tables to `debug/`.

### OCR (only needed for scanned PDFs)
Every PDF RENAR currently publishes has a text layer, so you only need this if a page
comes back empty. On Windows:
1. **Tesseract**: install from https://github.com/UB-Mannheim/tesseract/wiki. In the
   installer, under *Additional language data*, tick **Romanian**. If you skipped it,
   copy [`ron.traineddata`](https://github.com/tesseract-ocr/tessdata/raw/main/ron.traineddata)
   into `C:\Program Files\Tesseract-OCR\tessdata\`. Check: `tesseract --list-langs`
   should list `ron` and `eng`. The script finds the default install path itself;
   otherwise pass `--tesseract "C:\...\tesseract.exe"` or set `TESSERACT_CMD`.
2. **Poppler** (used by pdf2image): download a release from
   https://github.com/oschwartz10612/poppler-windows/releases, unzip it (e.g. to
   `C:\poppler`), and either add `C:\poppler\Library\bin` to PATH or pass
   `--poppler C:\poppler\Library\bin` (or set `POPPLER_PATH`).

If OCR isn't installed, pages without text are logged in `review.csv` and the run continues.

## How it works
The site's table is a DataTables server-side grid backed by
`/index.php/oec/get_oecs?act_id=<id>` (JSON). The scraper pages through it, then opens
`/index.php/oec/get_oec_details/<id>` for every row and parses the two detail tables
(labels matched diacritic-insensitively). PDFs are Alfresco shared links on cms.renar.ro.
