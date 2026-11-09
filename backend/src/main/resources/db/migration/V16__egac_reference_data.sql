-- Reference data for the EGAC dataset (data/egac-egypt): the Egyptian accreditation body and
-- the certification standards its schedules accredit that earlier datasets did not add. As in
-- the ESYD dataset, these are recorded under ISO/IEC 17021-1 (their own 17021-x / 28003 parts
-- are not separate accreditation standards here). ISO 37000 and ISO 10002 (guidance, not
-- certifiable) are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('EGAC', 'Egyptian Accreditation Council (EGAC)', 'Egypt', 'https://egac.gov.eg');

INSERT INTO standards (code, title, kind) VALUES
('ISO 7101',  'Healthcare organization management systems', 'CERTIFICATION'),
('ISO 18788', 'Management systems for private security operations', 'CERTIFICATION'),
('ISO 19443', 'Quality management systems for the nuclear energy supply chain (application of ISO 9001)', 'CERTIFICATION'),
('ISO 28000', 'Security and resilience — Security management systems', 'CERTIFICATION'),
('ISO 28001', 'Security management systems for the supply chain — Best practices for supply chain security', 'CERTIFICATION'),
('ISO 29994', 'Education and learning services — Requirements for distance learning', 'CERTIFICATION'),
('ISO 30401', 'Knowledge management systems', 'CERTIFICATION'),
('ISO 37101', 'Management systems for sustainable development in communities', 'CERTIFICATION'),
('ISO 44001', 'Collaborative business relationship management systems', 'CERTIFICATION'),
('ISO 56001', 'Innovation management systems', 'CERTIFICATION');

INSERT INTO accreditation_scheme_rules (accreditation_standard, certification_standard) VALUES
('ISO/IEC 17021-1', 'ISO 7101'),
('ISO/IEC 17021-1', 'ISO 18788'),
('ISO/IEC 17021-1', 'ISO 19443'),
('ISO/IEC 17021-1', 'ISO 28000'),
('ISO/IEC 17021-1', 'ISO 28001'),
('ISO/IEC 17021-1', 'ISO 29994'),
('ISO/IEC 17021-1', 'ISO 30401'),
('ISO/IEC 17021-1', 'ISO 37101'),
('ISO/IEC 17021-1', 'ISO 44001'),
('ISO/IEC 17021-1', 'ISO 56001');
