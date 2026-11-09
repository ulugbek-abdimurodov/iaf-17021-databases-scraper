-- Reference data for the INAB dataset (data/inab-ireland): the Irish accreditation body.
-- Every standard its schedules accredit is already in the reference data. The EU directive
-- notified-body activities ("Notified bodies - Mgt Sys": pressure equipment, recreational craft)
-- are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('INAB', 'Irish National Accreditation Board', 'Ireland', 'https://www.inab.ie');
