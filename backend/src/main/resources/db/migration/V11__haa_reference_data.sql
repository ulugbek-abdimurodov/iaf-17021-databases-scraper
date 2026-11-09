-- Reference data for the HAA dataset (data/haa-croatia): the Croatian accreditation body.
-- Its bodies hold only standards earlier datasets already added. HRB's PED module H
-- (notified-body directive module) is deliberately not added; the dataset leaves it out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('HAA', 'Croatian Accreditation Agency (Hrvatska akreditacijska agencija)', 'Croatia', 'https://www.akreditacija.hr');
