#!/bin/bash
set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_CONTAINER="${DB_CONTAINER:-osint-db-1}"
DB_USER="${DB_USER:-osint_user}"
DB_NAME="${DB_NAME:-osint_db}"

# Setup backup directory if not exists
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/osint_backup_${TIMESTAMP}.sql.gz"

echo "[$(date)] Starting database backup..."

# Use Docker exec to run pg_dump locally inside the container
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -F c | gzip > "$BACKUP_FILE"

echo "[$(date)] Backup completed: ${BACKUP_FILE}"

# Cleanup backups older than 7 days
echo "[$(date)] Cleaning up old backups (>7 days)..."
find "$BACKUP_DIR" -type f -name "osint_backup_*.sql.gz" -mtime +7 -exec rm {} \;

echo "[$(date)] Done."
