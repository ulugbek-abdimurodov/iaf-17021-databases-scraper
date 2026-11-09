-- Reference data for the NAH dataset (data/nah-hungary): the Hungarian accreditation body.
-- Every standard its annexes accredit is already in the reference data. MEES (Hungarian
-- health-care standards), MER (Hungarian forest certification), ISO/TS 22163 (railway) and
-- the 2014/68/EU module H notified-body activity are deliberately not added; the dataset
-- leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('NAH', 'Nemzeti Akkreditáló Hatóság (National Accreditation Authority)', 'Hungary', 'https://nah.gov.hu');
