-- Reference data for the BAS dataset (data/bas-bulgaria): the Bulgarian accreditation body.
-- Its bodies hold only standards earlier datasets already added. PEFC forest management and
-- PAS 24000 / FSSC 24000 social management are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('BAS', 'Executive Agency Bulgarian Accreditation Service (Изпълнителна агенция „Българска служба за акредитация“)', 'Bulgaria', 'https://www.nab-bas.bg');
