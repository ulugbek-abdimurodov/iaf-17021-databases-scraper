-- Reference data for the RvA dataset (data/rva-netherlands): the Dutch accreditation body.
-- Every standard its annexes accredit is already in the reference data. Dutch national schemes
-- (VCA / VCU, HKZ, NEN 7510, CO2-Prestatieladder, Groenkeur, SCIOS, CKB, BRL SVMS 007, PCSN,
-- arbodiensten, NPA), AQAP 2110, FAMI-QS, EFISC-GTP, Riskplaza, PGS 29 and the EU directive /
-- Cyber Resilience Act activities are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('RvA', 'Raad voor Accreditatie (Dutch Accreditation Council)', 'Netherlands', 'https://www.rva.nl');
