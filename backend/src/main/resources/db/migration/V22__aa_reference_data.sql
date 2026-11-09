-- Reference data for the Akkreditierung Austria dataset (data/aa-austria): the Austrian
-- accreditation body. Every standard its register accredits is already in the reference data.
-- Austrian and German national schemes (AUVA-SGM, SCC-VAZ, IT-Sicherheitskatalog § 11 EnWG),
-- EN 9110, EN 15085-2, TL 9000, ISO/IEC 27002 / 27011 / 27019, ISO/IEC TR 20000-9,
-- IEC 62443-2-1, ISO 29990 and the EU regulation / directive activities (2018/762, 2018/858,
-- 2014/68/EU module H) are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('AA', 'Akkreditierung Austria (Austrian accreditation body)', 'Austria', 'https://akkreditierung-austria.gv.at');
