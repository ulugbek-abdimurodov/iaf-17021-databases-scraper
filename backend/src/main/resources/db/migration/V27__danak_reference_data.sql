-- Reference data for the DANAK dataset (data/danak-denmark): the Danish accreditation body.
-- Every standard its registrations accredit is already in the reference data. Danish Executive
-- Order schemes (wind turbines, lifts, meter installers, energy labelling, mandatory energy
-- audits, health and safety certificate), Insurance & Pension Denmark requirements, DS 21001,
-- AQAP-2110 and the PED / RED directive modules are deliberately not added; the dataset leaves
-- them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('DANAK', 'Den Danske Akkrediteringsfond (Danish Accreditation Fund)', 'Denmark', 'https://www.danak.dk');
