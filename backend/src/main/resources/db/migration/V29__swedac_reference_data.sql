-- Reference data for the Swedish Board for Accreditation and Conformity Assessment (Swedac).
-- Swedac entries limited to management-system certification under ISO/IEC 17021-1 are imported.
-- National, product/notified-body, forestry, welding, accessibility, personal-data and
-- road-safety schemes are deliberately left out; see data/swedac-sweden/SOURCES.md.

INSERT INTO accreditation_bodies (code, name, country, website) VALUES
('SWEDAC', 'Swedish Board for Accreditation and Conformity Assessment (Swedac)', 'Sweden',
 'https://www.swedac.se');
