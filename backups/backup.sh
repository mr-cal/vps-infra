#!/usr/bin/env bash
# Backup the craft-dashboard PostgreSQL database, encrypted at rest.
#
# Intended to run via host crontab (see cron.d/backup-craft-dashboard):
#   0 3 * * * /opt/vps-infra/backups/backup.sh   (daily at 03:00 UTC)
#
# Dumps the Postgres database via the running container, then encrypts with
# GPG symmetric AES256 before leaving the VPS. This allows the backup to be
# archived as a GitHub Actions build artifact without exposing database
# contents in public repository artifacts.
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)"
RETENTION_DAYS=14
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/craft_dashboard_${TIMESTAMP}.sql.gz"
ENCRYPTED_FILE="${DUMP_FILE}.gpg"
SECRETS_ENV="/etc/vps-infra/secrets.env"

# shellcheck disable=SC1090
if [ -f "${SECRETS_ENV}" ]; then
  source "${SECRETS_ENV}"
fi

PASSPHRASE="${CRAFT_DASHBOARD_BACKUP_GPG_PASSPHRASE:-${REMARK_BACKUP_GPG_PASSPHRASE:-}}"

# Dump the database via the running postgres container.
podman-compose -f "${BACKUP_DIR}/../docker-compose.craft-dashboard.yml" \
  exec -T postgres \
  pg_dump -U craft_dashboard craft_dashboard |
  gzip >"${DUMP_FILE}"

# Sanity check: ensure valid gzip archive
gzip -t "${DUMP_FILE}"

if [ -n "${PASSPHRASE}" ]; then
  # Encrypt, then remove the plaintext dump from disk
  echo -n "${PASSPHRASE}" | gpg --batch --yes --passphrase-fd 0 \
    --cipher-algo AES256 --symmetric --output "${ENCRYPTED_FILE}" "${DUMP_FILE}"
  rm -f "${DUMP_FILE}"
  echo "Encrypted backup created: ${ENCRYPTED_FILE}"
else
  echo "Backup created (unencrypted, no passphrase found): ${DUMP_FILE}"
fi

# Delete backups older than the retention period.
find "${BACKUP_DIR}" \( -name "craft_dashboard_*.sql.gz" -o -name "craft_dashboard_*.sql.gz.gpg" \) -mtime +"${RETENTION_DAYS}" -delete

echo "Cleaned up backups older than ${RETENTION_DAYS} days."
