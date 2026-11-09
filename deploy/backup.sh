#!/bin/sh
# Nightly backup of the CertiFind database: one pg_dump file per run, old files
# pruned, optionally copied off the server. Run from cron on the server, e.g.
#   15 3 * * * /opt/certifind/deploy/backup.sh >> /var/log/certifind-backup.log 2>&1
#
# Settings (environment variables, all optional):
#   BACKUP_DIR  where dumps are written       (default /var/backups/certifind)
#   KEEP_DAYS   delete dumps older than this  (default 14)
#   CONTAINER   PostgreSQL container name     (default certifind-postgres)
#   OFFSITE     rsync target for a copy off this server, e.g. backup@nas:/backups/certifind/
#
# Restore (replaces the database contents):
#   docker exec -i certifind-postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < FILE.dump
set -eu

BACKUP_DIR=${BACKUP_DIR:-/var/backups/certifind}
KEEP_DAYS=${KEEP_DAYS:-14}
CONTAINER=${CONTAINER:-certifind-postgres}

mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/certifind_db-$(date +%Y%m%d-%H%M%S).dump"

# Write to a temporary name first so a failed dump never looks like a good one.
docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$file.tmp"
mv "$file.tmp" "$file"
echo "$(date -Iseconds) wrote $file ($(du -h "$file" | cut -f1))"

find "$BACKUP_DIR" -name 'certifind_db-*.dump' -mtime +"$KEEP_DAYS" -delete

if [ -n "${OFFSITE:-}" ]; then
    rsync -a "$file" "$OFFSITE"
    echo "$(date -Iseconds) copied to $OFFSITE"
fi
