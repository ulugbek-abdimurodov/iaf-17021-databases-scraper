-- Reference data for the BELAC dataset (data/belac-belgium): the Belgian accreditation body.
-- Every standard its register accredits is already in the reference data. National schemes
-- (VCA, VCU, CO2 prestatieladder, Food Autocontrol System, Feed Chain Alliance, SHE) and the
-- EU directive activities are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('BELAC', 'BELAC - Belgian Accreditation Body (Belgische Accreditatie-instelling / Organisme belge d''accréditation)', 'Belgium', 'https://economie.fgov.be/en/themes/quality-and-safety/accreditation-belac');
