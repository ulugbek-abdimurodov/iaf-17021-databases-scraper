-- Reference data for the ESYD dataset (data/esyd-greece): the Greek accreditation
-- body and the international certification standards its bodies hold that no
-- earlier dataset used. Greek national schemes (ELOT 1429, ELOT 1435, AGRO 2) are
-- deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('ESYD', 'Hellenic Accreditation System (Εθνικό Σύστημα Διαπίστευσης)', 'Greece', 'https://www.esyd.gr');

INSERT INTO standards (code, title, kind) VALUES
('EN 15224',  'Quality management systems for healthcare', 'CERTIFICATION'),
('ISO 18295', 'Customer contact centres', 'CERTIFICATION'),
('ISO 21001', 'Management systems for educational organizations', 'CERTIFICATION'),
('ISO 21401', 'Sustainability management systems for accommodation establishments', 'CERTIFICATION'),
('ISO 29993', 'Learning services outside formal education', 'CERTIFICATION'),
('ISO 37301', 'Compliance management systems', 'CERTIFICATION'),
('ISO 3834',  'Quality requirements for fusion welding of metallic materials', 'CERTIFICATION'),
('ISO 41001', 'Facility management systems', 'CERTIFICATION'),
('ISO 46001', 'Water efficiency management systems', 'CERTIFICATION'),
('ISO 55001', 'Asset management systems', 'CERTIFICATION');

INSERT INTO accreditation_scheme_rules (accreditation_standard, certification_standard) VALUES
('ISO/IEC 17021-1', 'EN 15224'),
('ISO/IEC 17021-1', 'ISO 18295'),
('ISO/IEC 17021-1', 'ISO 21001'),
('ISO/IEC 17021-1', 'ISO 21401'),
('ISO/IEC 17021-1', 'ISO 29993'),
('ISO/IEC 17021-1', 'ISO 37301'),
('ISO/IEC 17021-1', 'ISO 3834'),
('ISO/IEC 17021-1', 'ISO 41001'),
('ISO/IEC 17021-1', 'ISO 46001'),
('ISO/IEC 17021-1', 'ISO 55001');
