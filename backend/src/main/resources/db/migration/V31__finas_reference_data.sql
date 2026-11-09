-- Reference data for the FINAS dataset (data/finas-finland): the Finnish accreditation body.
-- Every management-system standard its registrations accredit is already in the reference data.
-- Deliberately not added: PEFC FI forest certification (Finnish national scheme), EN 15593
-- (food-packaging hygiene, only accredited in combination with ISO 9001 / ISO 22000), AQAP 2110,
-- EU directive notified-body modules (2014/68/EU pressure equipment, 2014/53/EU radio equipment)
-- and vehicle type-approval technical-service activities; see data/finas-finland/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('FINAS', 'FINAS Finnish Accreditation Service', 'Finland', 'https://www.finas.fi');
