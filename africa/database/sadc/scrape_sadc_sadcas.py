"""SADCAS register scrape (https://www.sadcas.org/accredited-organisations/management-bodies).
The site blocks non-browser clients, so extraction ran in the browser: the register table
(18 rows, single page) was read from the DOM and each Cert & SoA PDF was text-extracted
with pdf.js 4.0.379. IAF codes were taken from the 'IAF CODE DESCRIPTION' tables of
Annexure A; ISO 22000 categories from the 'CLUSTER CATEGORY SUB-CATEGORY' tables.
Result saved to sadcas_raw.json: [id, name, issue, expiry, pdf_path, iaf_codes, categories].
Browser snippet (run in page context):
  rows=[...document.querySelectorAll('table tr')].slice(1)
  pdf text -> split(/ANNEXURE A/) -> after 'Expiry' -> before 'Original date'
  IAF: /(?:^| )(\\d{1,2}) (?=[A-Z])/g ; categories: /\\b([A-K])(?: ?(?:I{1,3}|IV|V))?\\b/g
"""
