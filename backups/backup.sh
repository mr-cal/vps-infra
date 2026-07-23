#!/usr/bin/env bash
# Backup the craft-dashboard PostgreSQL database.
# Intended to run via host crontab:
#   0 3 * * * /opt/vps-infra/backups/backup.sh
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)"
RETENTION_DAYS=14
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/craft_dashboard_${TIMESTAMP}.sql.gz"

# Dump the database via the running postgres container.
podman-compose -f "${BACKUP_DIR}/../docker-compose.craft-dashboard.yml" \
  exec -T postgres \
  pg_dump -U craft_dashboard craft_dashboard |
  gzip >"${BACKUP_FILE}"

echo "Backup created: ${BACKUP_FILE}"

# Delete backups older than the retention period.
find "${BACKUP_DIR}" -name "craft_dashboard_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete

echo "Cleaned up backups older than ${RETENTION_DAYS} days."
