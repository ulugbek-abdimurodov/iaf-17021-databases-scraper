-- Reference data for the NCA dataset (data/nca-kazakhstan): the Kazakh accreditation body.
-- Deliberately not added: OHSAS 18001, ISO/TS 29001, ST RK 1179/1352, GOST 12.0.x schemes; see data/nca-kazakhstan/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('NCA', 'National Center for Accreditation', 'Kazakhstan', 'https://nca.kz');
