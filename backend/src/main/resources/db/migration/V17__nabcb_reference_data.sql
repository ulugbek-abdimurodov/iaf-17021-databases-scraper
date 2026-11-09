-- Reference data for the NABCB dataset (data/nabcb-india): the Indian accreditation body
-- and the standards its certification bodies hold that no earlier dataset used.
-- ICMED 9000 / ICMED 13485 (Indian national medical-device schemes), FSSC 24000 and
-- ISO 16363 repository audits are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('NABCB', 'National Accreditation Board for Certification Bodies (Quality Council of India)', 'India', 'https://nabcb.qci.org.in');

INSERT INTO standards (code, title, kind) VALUES
('ISO/IEC 17021-5', 'Requirements for bodies providing audit and certification of asset management systems', 'ACCREDITATION'),
('AS 9104-1',       'Requirements for aviation, space and defence quality management system certification programs', 'ACCREDITATION'),
('AS 9100',         'Quality management systems for aviation, space and defence organizations', 'CERTIFICATION'),
('ISO 15378',       'Primary packaging materials for medicinal products — Particular requirements for the application of ISO 9001 with reference to GMP', 'CERTIFICATION');

INSERT INTO accreditation_scheme_rules (accreditation_standard, certification_standard) VALUES
('ISO/IEC 17021-5', 'ISO 55001'),
('AS 9104-1',       'AS 9100'),
('ISO/IEC 17021-1', 'ISO 15378');
