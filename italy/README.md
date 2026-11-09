# Accredia scraper update

The scraper discovers company names and codes from the Accredia results page. It constructs each company URL under `/ppsearch/accredia_orgmask.jsp` and uses only that individual detail page for contacts, accreditation records, and document links. HTTP 200 alone is not enough: the response must contain the requested company plus detail-page markers. Otherwise contact and accreditation values remain blank and the failed verification is recorded.

The `Companies` sheet includes a detail-page verification flag and a source URL for each populated contact field. Fields without evidence on the company detail page remain blank. Codes are kept as text, including leading zeros.

## Run in PowerShell

From this folder:

```powershell
py -m pip install -r .\requirements.txt

# Small sample (first three companies)
py .\accredia_collector.py --limit 3 --out .\accredia_test

# Full collection
py .\accredia_collector.py --out .\accredia_output
```

The report is written to `<out>\accredia_report.xlsx`; PDFs, raw HTML, errors, and a run summary are saved alongside it. Use `--delay 0.8` (default) to retain the conservative request rate.

The supplied `0002_ICEA_Consorzio.html` is the general Accredia bank-dati overview, not a company detail page. It contains no ICEA detail record, so the scraper intentionally will not source contact information from it.
