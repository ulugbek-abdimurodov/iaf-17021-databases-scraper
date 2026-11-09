-- Reference data for the OLAS dataset (data/olas-luxembourg): the Luxembourg accreditation
-- body. Every standard its register accredits is already in the reference data. The national
-- PSDC scheme (ILNAS 106) and the EU 2018/858 automotive activities are deliberately not
-- added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('OLAS', 'OLAS - Office Luxembourgeois d''Accréditation et de Surveillance', 'Luxembourg', 'https://portail-qualite.public.lu');
