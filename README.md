# ISO/IEC 17021-1 National Accreditation Registries Scraper

A unified multi-country web scraper and dataset normalization pipeline for **ISO/IEC 17021-1** (*Conformity assessment — Requirements for bodies providing audit and certification of management systems*) national accreditation registries across **38 countries**.

Previously maintained as separate per-country micro-projects, this repository consolidates all national accreditation body scrapers, PDF/Word/Excel annex parsers, and dataset converters behind a single CLI entry point (`scrape.py`).

---

## Features

- **One-Command Execution (`scrape.py`)**: Scrape any country's accreditation register (by country name, folder name, ISO code, or accreditation body code) or run all 34 automated scrapers in a single command.
- **Annex & Scope Extraction**: Automatically downloads and parses accreditation certificates and technical scope annexes (PDF, Word `.doc`/`.docx`, Excel `.xlsx`, XML, and JSON/GraphQL APIs).
- **Standardized Dataset Conversion (`prepare_certifind.py`)**: Normalizes country-specific registers into a uniform three-table relational CSV schema (`bodies.csv`, `accreditations.csv`, `scopes.csv`) mapped to IAF/EA sector codes and management system standards (ISO 9001, ISO 14001, ISO 45001, ISO/IEC 27001, ISO 22000, FSSC 22000, ISO 50001, ISO 13485, ISO 22301, ISO 37001, etc.).
- **Active-Only Pruning (`prune_inactive.py`)**: Filters out withdrawn, suspended, or expired accreditations and retains only certification bodies holding an active `ISO/IEC 17021-1` accreditation.
- **Resumable & Polite Scraping**: All scrapers use read-only public endpoints, conservative request delays, automatic retries, and local file caching so interrupted runs resume cleanly.

---

## Quick Start

### 1. Install Dependencies

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
```

> **Note:** For OCR extraction on scanned PDF annexes (only used in Romania's `extract_renar_v2.py` fallback), install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (with the `ron` language pack) and [Poppler](https://poppler.freedesktop.org/).

### 2. Run with One Command

List all 38 supported countries, accreditation bodies, and scripts:

```bash
python scrape.py --list
```

Download the ISO/IEC 17021-1 database for a single country (by country name, ISO code, or accreditation body code):

```bash
python scrape.py germany
# or by accreditation body code / ISO code:
python scrape.py dakks
python scrape.py DE
```

Download multiple countries and convert them into normalized datasets in one command:

```bash
python scrape.py armenia greece turkey uk --prepare
```

Pass custom flags directly to a country's underlying scraper after `--`:

```bash
python scrape.py turkey -- --limit 5
python scrape.py greece -- --download-docs both
```

Convert already-downloaded scrape data without re-scraping:

```bash
python scrape.py germany uk --prepare-only --datasets-dir ./datasets
```

Run all automated country scrapers:

```bash
python scrape.py --all
```

Prune expired, suspended, or withdrawn rows from generated dataset folders:

```bash
python scrape.py --prune ./datasets/dakks-germany ./datasets/ukas-united-kingdom
```

---

## Supported Countries & Accreditation Bodies (38)

| Folder | ISO | AB Code | Country | National Accreditation Body | Scraper Script | Converter Script | Dataset ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `albania/` | `AL` | **DPA** | Albania | [General Directorate of Accreditation (DPA)](https://dpa.gov.al/organe-te-akredituara/) | `dpa_scraper.py` / `dpa_cs_scraper.py` | `parse_scope_pdf.py` | `dpa-albania` |
| `algeria/` | `DZ` | **ALGERAC** | Algeria | [Organisme Algérien d'Accréditation](https://algerac.dz/organismes-de-certification/) | *(source PDFs)* | — | `algerac-algeria` |
| `armenia/` | `AM` | **ARMNAB** | Armenia | [National Accreditation Body of Armenia](https://armnab.am/management-systems) | `armnab_scraper.py` | `prepare_certifind.py` | `armnab-armenia` |
| `austria/` | `AT` | **AA** | Austria | [Akkreditierung Austria](https://akkreditierung-austria.gv.at) | `scrape_akkreditierung_austria.py` | `prepare_certifind.py` | `aa-austria` |
| `belgium/` | `BE` | **BELAC** | Belgium | [Belgian Accreditation Body (BELAC)](https://weblist.economie.fgov.be/en/belac/list/qms) | `belac_qms_scraper.py` | `prepare_certifind.py` | `belac-belgium` |
| `bosnia/` | `BA` | **BATA** | Bosnia and Herzegovina | [Institute for Accreditation of Bosnia and Herzegovina](https://www.bata.gov.ba) | *(source PDF)* | — | `bata-bosnia` |
| `bulgaria/` | `BG` | **BAS** | Bulgaria | [Executive Agency Bulgarian Accreditation Service](https://nab-bas.bg) | `nab_scraper.py` | `prepare_certifind.py` | `bas-bulgaria` |
| `croatia/` | `HR` | **HAA** | Croatia | [Croatian Accreditation Agency](https://akreditacija.gov.hr/frontend/registar-akreditacija) | `haa_scraper.py` | `prepare_certifind.py` | `haa-croatia` |
| `czechia/` | `CZ` | **CAI** | Czechia | [Czech Accreditation Institute (ČIA)](https://www.cai.cz) | `cai_scraper.py` | `prepare_certifind.py` | `cai-czechia` |
| `denmark/` | `DK` | **DANAK** | Denmark | [The Danish Accreditation Fund](https://registry.danak.dk) | `danak_ms_scraper.py` | `prepare_certifind.py` | `danak-denmark` |
| `egypt/` | `EG` | **EGAC** | Egypt | [Egyptian Accreditation Council](https://egac.gov.eg/en/accredited-cabs/) | `egac_ms_scraper.py` | `prepare_certifind.py` | `egac-egypt` |
| `estonia/` | `EE` | **EAK** | Estonia | [Estonian Accreditation Centre](https://www.eak.ee) | `eak_scraper.py` | `prepare_certifind.py` | `eak-estonia` |
| `finland/` | `FI` | **FINAS** | Finland | [Finnish Accreditation Service](https://www.finas.fi/sites/en/operators/Pages/default.aspx) | `scrape_fi_finas.py` | `prepare_certifind.py` | `finas-finland` |
| `france/` | `FR` | **COFRAC** | France | [Comité Français d'Accréditation](https://tools.cofrac.fr/en/easysearch) | `cofrac_ms_scraper.py` | — | `cofrac-france` |
| `germany/` | `DE` | **DAkkS** | Germany | [Deutsche Akkreditierungsstelle](https://www.dakks.de/en/accredited-bodies-search.html) | `dakks_scraper.py` | `prepare_certifind.py` | `dakks-germany` |
| `greece/` | `GR` | **ESYD** | Greece | [Hellenic Accreditation System](http://www.esydops.gr/portal/p/esyd/en/) | `esyd_scraper.py` | `prepare_certifind.py` | `esyd-greece` |
| `hungary/` | `HU` | **NAH** | Hungary | [National Accreditation Authority (NAH)](https://www.nah.gov.hu) | `nah_scraper.py` | `prepare_certifind.py` | `nah-hungary` |
| `india/` | `IN` | **NABCB** | India | [National Accreditation Board for Certification Bodies](https://nabcb.qci.org.in) | `nabcb_ms_scraper.py` | `prepare_certifind.py` | `nabcb-india` |
| `ireland/` | `IE` | **INAB** | Ireland | [Irish National Accreditation Board](https://www.inab.ie) | `inab_scraper.py` | `prepare_certifind.py` | `inab-ireland` |
| `italy/` | `IT` | **ACCREDIA** | Italy | [L'Ente Italiano di Accreditamento](https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310) | `accredia_collector.py` | — | `accredia-italy` |
| `latvia/` | `LV` | **LATAK** | Latvia | [Latvian National Accreditation Bureau](https://www.latak.gov.lv) | `latak_s2_scraper.py` | `prepare_certifind.py` | `latak-latvia` |
| `lithuania/` | `LT` | **LASA** | Lithuania | [Lithuanian National Accreditation Bureau (NAB)](http://db.nab.lt/ais/accreditation) | `nab_scraper.py` | `prepare_certifind.py` | `lasa-lithuania` |
| `luxembourg/` | `LU` | **OLAS** | Luxembourg | [Office Luxembourgeois d'Accréditation et de Surveillance](https://portail-qualite.public.lu) | `olas_17021_scraper.py` | `prepare_certifind.py` | `olas-luxembourg` |
| `macedonia/` | `MK` | **IARM** | North Macedonia | [Institute for Accreditation of North Macedonia](https://iarm.gov.mk) | `iarm_scraper.py` | `prepare_certifind.py` | `iarm-north-macedonia` |
| `moldova/` | `MD` | **MOLDAC** | Moldova | [National Accreditation Centre of Moldova](https://www.acreditare.md) | *(source PDFs)* | — | `moldac-moldova` |
| `netherlands/` | `NL` | **RvA** | Netherlands | [Dutch Accreditation Council (RvA)](https://www.rva.nl) | `rva_scraper.py` | `prepare_certifind.py` | `rva-netherlands` |
| `norway/` | `NO` | **NA** | Norway | [Norsk Akkreditering](https://www.akkreditert.no/en/akkrediterte-organisasjoner/?scope=SysCert) | `no_ms_scraper.py` | `prepare_certifind.py` | `na-norway` |
| `poland/` | `PL` | **PCA** | Poland | [Polish Centre for Accreditation (PCA)](https://www.pca.gov.pl) | `pca_scraper.py` | `prepare_certifind.py` | `pca-poland` |
| `portugal/` | `PT` | **IPAC** | Portugal | [Instituto Português de Acreditação](https://www.ipac.pt) | `ipac_scraper.py` | `prepare_certifind.py` | `ipac-portugal` |
| `romania/` | `RO` | **RENAR** | Romania | [Romanian Accreditation Association (RENAR)](https://www.renar.ro/index.php/oec) | `scraper.py` | `extract_renar_v2.py` | `renar-romania` |
| `serbia/` | `RS` | **ATS** | Serbia | [Accreditation Body of Serbia](https://www.ats.rs) | *(source PDFs)* | `prepare_certifind.py` | `ats-serbia` |
| `slovakia/` | `SK` | **SNAS** | Slovakia | [Slovak National Accreditation Service](https://ais.snas.sk/web-report) | `snas_scraper.py` | `prepare_certifind.py` | `snas-slovakia` |
| `sweden/` | `SE` | **SWEDAC** | Sweden | [Swedac](https://ackrediteringar.swedac.se/en) | `swedac_ms_scraper.py` | `prepare_certifind.py` | `swedac-sweden` |
| `switzerland/` | `CH` | **SAS** | Switzerland | [Swiss Accreditation Service (SAS)](https://www.sas.admin.ch) | `sas_scraper.py` | `prepare_certifind.py` | `sas-switzerland` |
| `tunisia/` | `TN` | **TUNAC** | Tunisia | [Tunisian Accreditation Council (TUNAC)](https://www.tunac.tn) | `tunac_scraper.py` | — | `tunac-tunisia` |
| `turkey/` | `TR` | **TURKAK** | Turkey | [Turkish Accreditation Agency (TÜRKAK)](https://asist.turkak.org.tr/en/accreditation/accreditationagencysearch?institutionType=YS) | `turkak_scraper.py` | `prepare_certifind.py` | `turkak-turkey` |
| `uk/` | `GB` | **UKAS** | United Kingdom | [United Kingdom Accreditation Service (UKAS)](https://www.ukas.com) | `ukas_ms_scraper.py` | `prepare_certifind.py` | `ukas-united-kingdom` |
| `ukraine/` | `UA` | **NAAU** | Ukraine | [National Accreditation Agency of Ukraine](https://naau.org.ua) | `naau_ms_scraper.py` | `prepare_certifind.py` | `naau-ukraine` |

---

## Output Dataset Format

When running with `--prepare` (or `--prepare-only`), each country's `prepare_certifind.py` writes three standardized UTF-8 CSV files into `<datasets-dir>/<dataset-id>/`:

1. **`bodies.csv`**: Accredited certification bodies (`name`, `country`, `registration_no`, `address`, `website`, `email`, `phone`, `source_url`, `verified_at`).
2. **`accreditations.csv`**: Accreditation certificates (`body_name`, `accreditation_body`, `certificate_number`, `accreditation_standard`, `status`, `issue_date`, `expiry_date`, `proof_url`).
3. **`scopes.csv`**: Accredited management system standards and IAF/EA sector scopes (`certificate_number`, `standard_code`, `ea_codes`, `scope_note`, `status`).

### Active-Only Pruning (`prune_inactive.py`)

Every converter invokes `prune_inactive.py` (which can also be run standalone via `python scrape.py --prune <folder>`):
- Keeps only `ACTIVE` accreditations whose `expiry_date` is empty or not before today.
- Keeps only `ACTIVE` scopes belonging to a kept accreditation.
- Keeps only certification bodies that hold a valid `ISO/IEC 17021-1` base accreditation.

---

## Project Structure

```text
.
├── scrape.py                 # Unified one-command CLI runner for all countries
├── prune_inactive.py         # Dataset filter for active ISO/IEC 17021-1 accreditations
├── requirements.txt          # Consolidated Python dependencies
├── pytest.ini                # Unified test runner configuration
├── <country>/                # One folder per country (38 countries)
│   ├── *_scraper.py          # Country-specific registry & annex downloader
│   ├── prepare_certifind.py  # Converter to normalized CSV dataset + REVIEW.md
│   └── tests/                # Offline unit tests with mock fixtures (where present)
└── README.md
```

---

## Running Tests

Offline unit and integration test suites (using local HTML/API/PDF fixtures without touching live registries) are included and can be run from the root directory with a single command:

```bash
pytest
```
