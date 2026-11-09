-- CertiFind PostgreSQL schema.
--
-- Domain model
--   A certification body (CB, "company B") holds one or more accreditations,
--   each granted by an accreditation body (AB) against an accreditation
--   standard (ISO/IEC 17021-1, ISO/IEC 27006, ISO 50003, ...).
--   Each accreditation entitles the CB to issue certificates for specific
--   certification standards (ISO 9001, ISO/IEC 27001, ...) in specific EA
--   sectors. One accredited_scopes row = one (standard, EA sector) right.
--
-- Search question answered by the schema
--   "Which CBs may issue <certification standard> to a company in EA <n>?"
--   = active scope rows for that standard and EA code whose accreditation is
--     active and not expired (see v_issuing_rights).

-- Reference data -------------------------------------------------------------

CREATE TABLE accreditation_bodies (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    country     VARCHAR(100) NOT NULL,
    website     VARCHAR(255)
);

-- IAF ID 1 / EA-1/22 business sectors.
CREATE TABLE ea_sectors (
    code     INTEGER PRIMARY KEY CHECK (code BETWEEN 1 AND 39),
    name_en  VARCHAR(200) NOT NULL,
    name_it  VARCHAR(200) NOT NULL
);

-- Both accreditation standards (what an AB assesses a CB against) and
-- certification standards (what a CB certifies its clients against).
CREATE TABLE standards (
    code   VARCHAR(50)  PRIMARY KEY,
    title  VARCHAR(255) NOT NULL,
    kind   VARCHAR(20)  NOT NULL CHECK (kind IN ('ACCREDITATION', 'CERTIFICATION'))
);

-- Which certification standards an accreditation standard can cover,
-- e.g. ISO/IEC 17021-1 -> ISO 9001, ISO/IEC 27006 -> ISO/IEC 27001.
CREATE TABLE accreditation_scheme_rules (
    accreditation_standard  VARCHAR(50) NOT NULL REFERENCES standards(code),
    certification_standard  VARCHAR(50) NOT NULL REFERENCES standards(code),
    PRIMARY KEY (accreditation_standard, certification_standard)
);

-- Free-text sector vocabulary (IT/EN) used to resolve what the user types
-- ("carpenteria metallica", "software") into an EA code.
CREATE TABLE sector_keywords (
    id        SERIAL PRIMARY KEY,
    keyword   VARCHAR(255) NOT NULL,
    language  VARCHAR(2)   NOT NULL CHECK (language IN ('it', 'en')),
    ea_code   INTEGER      NOT NULL REFERENCES ea_sectors(code),
    CONSTRAINT uq_sector_keyword UNIQUE (keyword, ea_code)
);

-- Certification bodies and their accreditations --------------------------------

-- registration_no is the national company ID (NIPT in Albania, CUI in Romania);
-- when known it identifies the body even if its name is spelled differently.
-- source_url / verified_at record where the contact details come from and when
-- a person last checked them against the official record.
CREATE TABLE certification_bodies (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    country          VARCHAR(100) NOT NULL,
    registration_no  VARCHAR(50),
    phone            VARCHAR(50),
    email            VARCHAR(100),
    website          VARCHAR(255),
    address          TEXT,
    source_url       TEXT,
    verified_at      DATE,
    CONSTRAINT uq_cb_country_name UNIQUE (country, name)
);

CREATE UNIQUE INDEX uq_cb_registration_no ON certification_bodies (country, registration_no)
    WHERE registration_no IS NOT NULL;

-- One accreditation certificate held by a CB.
CREATE TABLE accreditations (
    id                      SERIAL PRIMARY KEY,
    certification_body_id   INTEGER     NOT NULL REFERENCES certification_bodies(id) ON DELETE CASCADE,
    accreditation_body_id   INTEGER     NOT NULL REFERENCES accreditation_bodies(id) ON DELETE RESTRICT,
    accreditation_standard  VARCHAR(50) NOT NULL REFERENCES standards(code),
    certificate_number      VARCHAR(50) NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE', 'SUSPENDED', 'WITHDRAWN')),
    issue_date              DATE        NOT NULL,
    expiry_date             DATE,
    proof_url               TEXT,
    -- Dataset folder under data/ that owns this row (e.g. 'dpa-albania'). The
    -- importer withdraws a dataset's accreditations that vanish from its CSVs.
    data_source             VARCHAR(50),
    CONSTRAINT uq_accreditation_certificate UNIQUE (accreditation_body_id, certificate_number),
    CONSTRAINT uq_cb_ab_standard UNIQUE (certification_body_id, accreditation_body_id, accreditation_standard),
    CONSTRAINT ck_accreditation_dates CHECK (expiry_date IS NULL OR expiry_date >= issue_date),
    -- Target of the composite FK from accredited_scopes.
    CONSTRAINT uq_accreditation_id_standard UNIQUE (id, accreditation_standard)
);

-- One issuing right: certification standard x EA sector under an accreditation.
-- accreditation_standard is repeated here only so the two composite FKs can
-- guarantee the scope is allowed by the accreditation's scheme (a 27006
-- accreditation can never carry an ISO 9001 scope).
CREATE TABLE accredited_scopes (
    id                      SERIAL PRIMARY KEY,
    accreditation_id        INTEGER     NOT NULL,
    accreditation_standard  VARCHAR(50) NOT NULL,
    certification_standard  VARCHAR(50) NOT NULL,
    ea_code                 INTEGER     NOT NULL REFERENCES ea_sectors(code),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE', 'SUSPENDED', 'WITHDRAWN')),
    scope_note              TEXT,
    CONSTRAINT fk_scope_accreditation FOREIGN KEY (accreditation_id, accreditation_standard)
        REFERENCES accreditations (id, accreditation_standard) ON DELETE CASCADE,
    CONSTRAINT fk_scope_scheme_rule FOREIGN KEY (accreditation_standard, certification_standard)
        REFERENCES accreditation_scheme_rules (accreditation_standard, certification_standard),
    CONSTRAINT uq_scope UNIQUE (accreditation_id, certification_standard, ea_code)
);

-- Indexes for the search path and company detail lookups.
CREATE INDEX idx_scopes_search        ON accredited_scopes (certification_standard, ea_code, status);
CREATE INDEX idx_accreditations_cb    ON accreditations (certification_body_id);
CREATE INDEX idx_accreditations_src   ON accreditations (data_source);
CREATE INDEX idx_sector_keywords_ea   ON sector_keywords (ea_code);
CREATE INDEX idx_sector_keywords_text ON sector_keywords (lower(keyword));

-- Every currently valid issuing right, flattened for search and analytics.
CREATE VIEW v_issuing_rights AS
SELECT cb.id                    AS certification_body_id,
       cb.name                  AS certification_body,
       cb.country,
       ab.code                  AS accreditation_body,
       a.accreditation_standard,
       a.certificate_number,
       a.expiry_date,
       s.certification_standard,
       s.ea_code,
       ea.name_en               AS ea_sector
FROM accredited_scopes s
JOIN accreditations a        ON a.id = s.accreditation_id
JOIN certification_bodies cb ON cb.id = a.certification_body_id
JOIN accreditation_bodies ab ON ab.id = a.accreditation_body_id
JOIN ea_sectors ea           ON ea.code = s.ea_code
WHERE s.status = 'ACTIVE'
  AND a.status = 'ACTIVE'
  AND (a.expiry_date IS NULL OR a.expiry_date >= CURRENT_DATE)
  -- A certification body must also hold an active 17021-1 accreditation
  -- (27001 needs 17021-1 + 27006, 50001 needs 17021-1 + 50003).
  AND (a.accreditation_standard = 'ISO/IEC 17021-1'
       OR EXISTS (SELECT 1
                  FROM accreditations base
                  WHERE base.certification_body_id = a.certification_body_id
                    AND base.accreditation_standard = 'ISO/IEC 17021-1'
                    AND base.status = 'ACTIVE'
                    AND (base.expiry_date IS NULL OR base.expiry_date >= CURRENT_DATE)));
