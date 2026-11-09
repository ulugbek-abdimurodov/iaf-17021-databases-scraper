-- Reference data for the SAS dataset (data/sas-switzerland): the Swiss accreditation body.
-- Every standard its SCESm directories accredit is already in the reference data. Swiss
-- national schemes (eduQua, IN-Qualis, QSC, SanaCERT, Swiss Care Excellence Certificate,
-- VDSZ data-protection and EPDV patient-record ordinances), EN 9120, NATO AQAP 2110, FAMI-QS,
-- DIN EN 15593, ISO 27799, ISO 21188, BS 10008, CA/Browser Forum and WebTrust audits and the
-- notified-body module H activities are deliberately not added; the dataset leaves them out.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('SAS', 'Schweizerische Akkreditierungsstelle (Swiss Accreditation Service)', 'Switzerland', 'https://www.sas.admin.ch');
