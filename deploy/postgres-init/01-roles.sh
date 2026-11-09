#!/bin/sh
# Runs once, on a new volume (Docker's initdb entrypoint). Creates the two roles
# CertiFind uses; Flyway then creates the tables as certifind_import.
#   certifind_import  owns schema public: migrations and CSV imports
#   certifind_app     read-only: the backend API
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v db="$POSTGRES_DB" \
     -v import_pw="$CERTIFIND_IMPORT_PASSWORD" \
     -v app_pw="$CERTIFIND_APP_PASSWORD" <<'EOSQL'
CREATE ROLE certifind_import LOGIN PASSWORD :'import_pw';
CREATE ROLE certifind_app    LOGIN PASSWORD :'app_pw';

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO certifind_import, certifind_app;

ALTER SCHEMA public OWNER TO certifind_import;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO certifind_app;

-- Every table and view certifind_import creates later is readable by the app.
ALTER DEFAULT PRIVILEGES FOR ROLE certifind_import IN SCHEMA public
    GRANT SELECT ON TABLES TO certifind_app;
EOSQL
