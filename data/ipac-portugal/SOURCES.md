# IPAC (Portugal)

Source: the [IPAC accredited-body register](https://www.ipac.pt/pesquisa/acredita.asp)
(`https://www.ipac.pt/docs/2partyEA/ScopeIPAC2.xml`), every management-system certification
registration (`A00xx`) under NP EN ISO/IEC 17021-1. Scraped with `database/portugal/ipac_scraper.py`
(each body's live HTML profile page `https://www.ipac.pt/pesquisa/ficha_ocf.asp?ID=A00xx`, which
holds the current technical annex in force across all accredited sites) and converted with
`database/portugal/prepare_certifind.py`; every skipped scheme and suspended entry is listed in
`database/portugal/ipac_review.md`. Not yet verified by a person, so `verified_at` is empty.
`source_url` and `proof_url` are the body's IPAC profile page.

Extraction rules:

- One IPAC registration per certification body. For multi-site registrations (`A0002`, `A0017`,
  `A0019`), active scopes across all accredited sites are combined per standard.
- `issue_date` is the profile's `Certificado em vigor` date (`certificate_date`), or the initial
  grant date (`Data de concessão`) when absent; `expiry_date` is empty (IPAC open-ended
  accreditations do not carry an expiry date on the profile page).
- Accreditation standard per scheme as in the DAkkS, RvA, DANAK, NA, and Swedac datasets:
  ISO 22000 → ISO 22003-1, ISO 50001 → ISO 50003, ISO/IEC 27001 → ISO/IEC 27006,
  ISO/IEC 20000-1 → ISO/IEC 20000-6, ISO 22301 → ISO/IEC 17021-6, ISO 55001 → ISO/IEC 17021-5,
  ISO 39001 → ISO/IEC 17021-7 (suffixed rows such as `A0002 (22000)`). ISO 9001, ISO 14001,
  ISO 45001, ISO 56001, and ISO 3834 (accredited in conjunction with ISO 9001 on `A0003`) are
  recorded under the plain `ISO/IEC 17021-1` row.
- Sectors:
  - ISO 9001, ISO 14001, ISO 45001, ISO 55001, ISO 56001: explicit `IAF <n>` codes (1–39) from the
    profile page. When a sector carries a NACE exclusion (`exceto NACE ...`) rather than
    `(completo)`, the EA code is retained and `scope_note` records `Limited scope: EA <n> (...)`.
  - ISO 22000: ISO 22003-1 food-chain categories (`B`–`K`), classified to EA sectors with the ESYD
    table.
  - ISO 50001: ISO 50003 technical areas numbered `1`–`8` (`A`–`H`), classified to EA sectors with
    the ESYD table.
  - ISO/IEC 27001, ISO/IEC 20000-1, ISO 22301, and ISO 39001 do not list EA/IAF sectors and are
    recorded for all EA sectors (`1-39`) with an explanatory `scope_note`.
- Suspensions:
  - Partially suspended scopes exclude the suspended IAF sectors and note them in `scope_note`:
    `A0008` (EIC) excludes `IAF 5` under ISO 9001 and `IAF 17, 29` under ISO 56001 (suspended since
    `2026-06-25`); `A0025` (QEC PT) excludes `IAF 31` under ISO 45001 (suspended since
    `2026-10-02`).
  - `A0021` (INNOQ, Mozambique) has all 13 of its ISO 9001 IAF sectors suspended since `2026-03-13`
    and is removed by `prune_inactive.py`.
- Not imported (national, forestry, and notified-body / directive schemes):
  - `NP 4552` (*Sistemas de Gestão da Conciliação entre a vida profissional, familiar e pessoal*):
    Portuguese national standard (`A0002`, `A0003`, `A0005`).
  - `PEFC` (*Sistemas de Gestão Florestal Sustentável PEFC* / `NP 4406`): forest management scheme
    (`A0002`, `A0018`, `A0019`).
  - *Certificação de sistemas de gestão no âmbito regulamentar* (Directive 2014/32/EU MI and
    Directive 2014/68/EU PED Module H): notified-body regulatory modules (`A0002`, `A0022`).
    `A0022` (SGS Portugal - Industrial) holds only Directive 2014/68/EU Module H and is not
    imported.
- Contacts: primary site address, email, and 9-digit Portuguese phone numbers normalized to
  `+351 XXX XXX XXX`.

| Retrieved | By | Notes |
| --- | --- | --- |
| 2026-11-05 | ipac_scraper.py | 12 registrations, 1,081 scope lines |
| 2026-11-05 | prepare_certifind.py + prune_inactive.py | 10 bodies, 32 accreditations, 50 scope rows |

