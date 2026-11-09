-- Reference data for the IPAC dataset (data/ipac-portugal): the Portuguese accreditation body.
-- Every management-system standard its registrations accredit is already in the reference data.
-- The Portuguese national work-family-personal life reconciliation scheme (NP 4552), the PEFC
-- sustainable forest management scheme (NP 4406), and EU directive notified-body modules
-- (2014/32/EU MI and 2014/68/EU PED Module H) are deliberately not added; see
-- data/ipac-portugal/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('IPAC', 'Instituto Português de Acreditação, I.P. (IPAC)', 'Portugal', 'https://www.ipac.pt');

