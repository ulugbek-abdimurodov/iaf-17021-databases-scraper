# COFRAC (France)

Source: COFRAC accredited-bodies search, https://tools.cofrac.fr/en/easysearch/index.php,
section Certifications, activity "Certification of management systems (ISO/IEC 17021-1)":
each accreditation's register entry and its certificate + technical annex PDF
(`https://tools.cofrac.fr/annexes/sect4/<number>.pdf`). Scraped with
`database/france/cofrac_ms_scraper.py`, converted with `database/france/prepare_certifind.py`;
every skipped scheme and body is listed in `database/france/cofrac_review.md`. Not yet verified
by a person, so `verified_at` is empty. `source_url` is the COFRAC search page; `proof_url` is the
annex PDF that was read.

Extraction rules:

- One COFRAC accreditation number (4-0583, ...) is one accreditation under NF EN ISO/IEC
  17021-1:2015. `issue_date` / `expiry_date` are the certificate's "granting date / valid from"
  and "expiry date / valid until" (current revision).
- Only accreditations with register status "Active" are imported (11 terminated or withdrawn
  ones are not).
- Companies with several accreditations (AFNOR 4-0001 + 4-0571, Bureau Veritas 4-0572 + 4-0002,
  AB Certification 4-0023 + 4-0640, DEKRA Certification 4-0545 + 4-0604, LRQA 4-0570 + 4-0003,
  SGS 4-0008 + 4-0574) are one body. CertiFind allows one accreditation per body, AB and
  standard, so the second accreditation's schemes are merged into the first one's rows and dates.
- Accreditation standard per scheme: ISO/IEC 27001 → ISO/IEC 27006, ISO 50001 → ISO 50003,
  ISO 22000 / FSSC 22000 → ISO 22003-1, ISO 37001 → ISO/IEC 17021-9, EN 9100 → AS 9104-1
  (suffixed rows such as `4-0001 (27006)`). ISO 9001 / 14001 / 45001 / 13485 and ISO 19443 are
  under the plain accreditation row.
- The annexes come in two layouts (older "CERT CEPE FORM 56" and the newer "Liste des activités
  accréditées"); both are read as text. A section starts at its "Système de management de ... /"
  heading; the location tables and footers are not scope.
- Sectors, ISO 9001 / 14001 / 45001: the IAF codes listed under the scheme. ISO 50001: ISO 50003
  technical areas A–H; ISO 22000 / FSSC 22000: ISO 22003-1 categories; ISO 13485: IAF MD 8 codes
  (1.1–1.7) — all classified to EA with the ESYD tables. ISO/IEC 27001, ISO 37001, ISO 19443 and
  EN 9100 have no sector list and are recorded for all EA sectors.
- The aerospace section lists EN 9100, EN 9110 and EN 9120 together; only EN 9100 (AS 9100) is
  imported.
- Phone numbers are converted to international form (+33, +212); the Italian and US bodies were
  not imported.

Not imported:

- French national schemes: HDS (Hébergeurs de données de santé), CACES testing bodies,
  NF V 01-005 / 01-007 agricultural production, HAS medicine-promotion quality referential, AFAQ
  ISO 9001-based training referentials, radiation protection (CEFRI), CSE experts, legal
  metrology and decree-based schemes (LNE), PEFC France and PEFC Belgium forest management.
- Schemes not in the standards table: AQAP 2110 / 2310, EN 9110, EN 9120, health-product
  transport.
- Bodies with nothing importable: BSI Group France (4-0611, HDS only), CEFRI (4-0017),
  CERTIPHARM (4-0617), DNV Business Assurance Italy (4-0638, AQAP only), ECOCERT Environnement
  (4-0011, PEFC only), Schellman Compliance (4-0635, HDS only).
- Annex PDF not downloaded by the scraper: DEKRA Industrial (1-7448), LSTI (4-1004).

Retrieved:

| Item | Value |
| --- | --- |
| Scrape date | 2026-11-05 |
| Register entries | 64 (53 active) |
| Bodies imported | 39 (France 37, Morocco 2) |
| Accreditations | 69 |
| Scope rows | 108 |
