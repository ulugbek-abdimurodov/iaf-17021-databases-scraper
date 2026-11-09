-- Reference data for the NAAU dataset (data/naau-ukraine): the Ukrainian accreditation body
-- and the two certification standards its bodies hold that no earlier dataset used.
-- NATO AQAP-2110 and the notified-body modules of Ukrainian technical regulations are
-- deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('NAAU', 'National Accreditation Agency of Ukraine (Національне агентство з акредитації України)', 'Ukraine', 'https://naau.org.ua');

INSERT INTO standards (code, title, kind) VALUES
('ISO 22716', 'Cosmetics — Good manufacturing practices (GMP)', 'CERTIFICATION'),
('ISO 29001', 'Quality management systems for the petroleum, petrochemical and natural gas industries', 'CERTIFICATION');

INSERT INTO accreditation_scheme_rules (accreditation_standard, certification_standard) VALUES
('ISO/IEC 17021-1', 'ISO 22716'),
('ISO/IEC 17021-1', 'ISO 29001');
