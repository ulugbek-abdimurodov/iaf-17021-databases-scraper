-- Reference data for the LATAK dataset (data/latak-latvia): the Latvian accreditation body.
-- Its bodies hold only standards earlier datasets already added. PEFC forest management,
-- PAS 24000 social management and Latvian / EU regulatory schemes (competent institutions in
-- labour protection, energy audits, end-of-waste regulations, MLC 2006, PED module H) are
-- deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('LATAK', 'Latvian National Accreditation Bureau (Latvijas Nacionālais akreditācijas birojs)', 'Latvia', 'https://www.latak.gov.lv');
