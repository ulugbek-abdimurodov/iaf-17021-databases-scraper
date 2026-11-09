-- Reference data for the CAI dataset (data/cai-czechia): the Czech accreditation body.
-- Every standard its annexes accredit is already in the reference data. HACCP (Věstník MZe
-- 2/2010), SJ-PK (Czech road-construction quality system), CFCS forest certification,
-- ČSN 01 0391 (corporate social responsibility), EMAS verification and the notified-body
-- activities are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('CAI', 'Český institut pro akreditaci, o.p.s. (Czech Accreditation Institute)', 'Czechia', 'https://www.cai.cz');
