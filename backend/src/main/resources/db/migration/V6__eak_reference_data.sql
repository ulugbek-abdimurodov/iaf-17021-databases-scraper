-- Reference data for the EAK dataset (data/eak-estonia): the Estonian accreditation
-- body. Its bodies hold only standards earlier datasets already added; PEFC national
-- forest-management schemes are deliberately not added, the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('EAK', 'Estonian Accreditation Centre (Eesti Akrediteerimiskeskus)', 'Estonia', 'https://www.eak.ee');
