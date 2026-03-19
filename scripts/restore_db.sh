#!/bin/bash
set -e

BACKUP_FILE=$1
DB_CONTAINER="${DB_CONTAINER:-osint-db-1}"
DB_USER="${DB_USER:-osint_user}"
DB_NAME="${DB_NAME:-osint_db}"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: ./restore_db.sh <backup_file.sql.gz>"
    echo "Files available in ./backups:"
    ls -l ./backups
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: File $BACKUP_FILE not found."
    exit 1
fi

echo "[$(date)] Restoring database from: ${BACKUP_FILE}"
echo "WARNING: This will overwrite existing data. Press Ctrl+C to abort."
sleep 3

# Unzip and pipe to pg_restore inside the container
# -c: clean (drop) database objects before recreating
gunzip -c "$BACKUP_FILE" | docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" -1 -c

echo "[$(date)] Restore completed successfully."
