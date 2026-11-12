# SLAB review (2026-11-09)

- Scope: 27 active "Certification bodies – System" registrations, 8 bodies. Nothing excluded (all 6 programmes map to CertiFind schemes).
- Programme mapping (assumed from prefix): QMS→ISO 9001, EMS→ISO 14001, OHS→ISO 45001, FMS→ISO 22000 (FSSC not distinguished), ENS→ISO 50001, IMS→ISO/IEC 27001.
- **Open: EA codes empty.** Scope schedule PDFs (42) could not be parsed: sandbox has no network route to www.slab.lk, and in-browser PDF parsing was blocked. Re-run `scrape_lk_slab.py` with access, download `proof_url` PDFs and extend `prepare_certifind.py` to read IAF/EA, ISO 22003-1 and ISO 50003 categories.
- Addresses, phone, e-mail not published on SLAB profiles; websites only for SLSI and Ceycert.
- Several profiles list multiple scope PDFs (old + extension); first/current one used as `proof_url`.
- Suspended/withdrawn/expired registrations not imported.
