#!/usr/bin/env bash
# Backup Remark42 comments for pcbisolation, encrypted at rest.
#
# Intended to run via host crontab (see cron.d/backup-remark42):
#   0 4 * * 0 /opt/vps-infra/backups/backup_remark42.sh   (weekly, Sunday 04:00)
#
# Exports all comments via Remark42's native admin export endpoint, then
# encrypts the export with a symmetric passphrase before it ever touches
# disk in plaintext. This matters because vps-infra is a PUBLIC repo and the
# encrypted file is later uploaded as a GitHub Actions artifact (see
# .github/workflows/backup-remark42.yml) — public-repo artifacts are
# downloadable by any signed-in GitHub user, and the export contains
# commenter emails and IP addresses.
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)"
RETENTION_DAYS=90  # ~12 weekly backups retained locally on the VPS
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SITE="pcbisolation"
EXPORT_FILE="${BACKUP_DIR}/remark42_${SITE}_${TIMESTAMP}.json.gz"
ENCRYPTED_FILE="${EXPORT_FILE}.gpg"
SECRETS_ENV="/etc/vps-infra/secrets.env"

# shellcheck disable=SC1090
source "${SECRETS_ENV}"

: "${REMARK_ADMIN_EMAIL:?REMARK_ADMIN_EMAIL missing from ${SECRETS_ENV}}"
: "${REMARK_ADMIN_PASSWD:?REMARK_ADMIN_PASSWD missing from ${SECRETS_ENV}}"
: "${REMARK_BACKUP_GPG_PASSPHRASE:?REMARK_BACKUP_GPG_PASSPHRASE missing from ${SECRETS_ENV}}"

curl -sf -u "${REMARK_ADMIN_EMAIL}:${REMARK_ADMIN_PASSWD}" \
  "https://comments.pcbisolation.com/api/v1/admin/export?site=${SITE}&mode=file" \
  -o "${EXPORT_FILE}"

# Sanity check: a valid export is a real gzip file, not an error JSON body.
gzip -t "${EXPORT_FILE}"

# Encrypt, then remove the plaintext export — never leave it sitting on disk.
echo -n "${REMARK_BACKUP_GPG_PASSPHRASE}" | gpg --batch --yes --passphrase-fd 0 \
  --cipher-algo AES256 --symmetric --output "${ENCRYPTED_FILE}" "${EXPORT_FILE}"
rm -f "${EXPORT_FILE}"

echo "Backup created: ${ENCRYPTED_FILE}"

find "${BACKUP_DIR}" -name "remark42_${SITE}_*.json.gz.gpg" -mtime +"${RETENTION_DAYS}" -delete
echo "Cleaned up backups older than ${RETENTION_DAYS} days."
