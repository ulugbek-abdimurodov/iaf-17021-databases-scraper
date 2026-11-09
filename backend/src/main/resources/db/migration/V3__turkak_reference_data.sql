-- Reference data for the TÜRKAK dataset (data/turkak-turkey): the Turkish
-- accreditation body, plus the AI and FSSC food-safety schemes that appear
-- in its annexes.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('TURKAK', 'Türk Akreditasyon Kurumu', 'Turkey', 'https://www.turkak.org.tr');

INSERT INTO standards (code, title, kind) VALUES
('ISO/IEC 42006', 'Requirements for bodies providing audit and certification of artificial intelligence management systems', 'ACCREDITATION'),
('ISO/IEC 42001', 'Artificial intelligence management systems', 'CERTIFICATION'),
('FSSC 22000',    'Food safety system certification (ISO 22000 with FSSC additional requirements)', 'CERTIFICATION');

INSERT INTO accreditation_scheme_rules (accreditation_standard, certification_standard) VALUES
('ISO/IEC 42006', 'ISO/IEC 42001'),
('ISO 22003-1',   'FSSC 22000');
