-- Reference data for the COFRAC dataset (data/cofrac-france): the French national accreditation body
-- (section Certifications, ISO/IEC 17021-1 management system certification bodies).
-- Deliberately not added: French national schemes (HDS health-data hosting, CACES testing bodies,
-- NF V 01-005 / 01-007 agricultural production, HAS medicine-promotion referential, AFAQ ISO 9001-based
-- training referentials, radiation-protection and CSE expert schemes, legal metrology and decrees,
-- PEFC France / Belgium), and schemes not in the standards table (AQAP 2110 / 2310, EN 9110, EN 9120,
-- health-product transport); see data/cofrac-france/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('COFRAC', 'Comité Français d''Accréditation', 'France', 'https://www.cofrac.fr');
