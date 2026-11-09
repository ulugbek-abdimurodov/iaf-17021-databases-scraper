-- Reference data for the ENAC dataset (data/enac-spain): the Spanish national accreditation body.
-- Deliberately not added: digital tachograph centres, end-of-waste, innovation management (UNE 166002),
-- TEDAE aerospace scheme, criminal/general compliance (UNE 19601 / ISO 37301), PEFC forest management,
-- anti-bribery (ISO 37001), aerospace quality (EN 9100), vehicle type-approval, asset management
-- (ISO 55001); see data/enac-spain/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('ENAC', 'Entidad Nacional de Acreditación', 'Spain', 'https://www.enac.es');
