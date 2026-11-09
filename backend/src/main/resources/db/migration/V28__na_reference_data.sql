-- Reference data for the Norsk Akkreditering dataset (data/na-norway): the Norwegian
-- accreditation body. Every standard its registrations accredit is already in the reference
-- data. The Norwegian Eco-Lighthouse scheme (Miljøfyrtårn), the Norwegian PEFC forest standards
-- (PEFC N 02 / N 03) and the Danish Executive Order BEK 1138/2025 (mandatory energy management)
-- are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('NA', 'Norsk Akkreditering (Norwegian Accreditation)', 'Norway', 'https://www.akkreditert.no');
