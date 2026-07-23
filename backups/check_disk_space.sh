#!/usr/bin/env bash
# check_disk_space.sh — alert by email when root disk usage crosses a threshold.
#
# Root-caused incident (2026-07-23): the VPS disk filled to 100% with no
# alerting in place, which cascaded into a Remark42 comment-data-loss event.
# This script closes that gap. It is intentionally simple (df + curl to the
# Resend API) rather than depending on a local MTA.
#
# Sends at most one email per calendar day while usage stays over WARN_PCT,
# to avoid alert fatigue from the 15-minute cron cadence. Resets as soon as
# usage drops back below the threshold, so a fresh breach always alerts
# immediately.
set -euo pipefail

WARN_PCT=80
SECRETS_ENV="/etc/vps-infra/secrets.env"
STATE_FILE="/var/lib/vps-infra/disk-alert-last-sent"

# shellcheck disable=SC1090
[ -f "${SECRETS_ENV}" ] && source "${SECRETS_ENV}"

USAGE_PCT="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
TODAY="$(date +%Y-%m-%d)"

mkdir -p "$(dirname "${STATE_FILE}")"
LAST_SENT="$(cat "${STATE_FILE}" 2>/dev/null || echo "")"

if [ "${USAGE_PCT}" -lt "${WARN_PCT}" ]; then
  rm -f "${STATE_FILE}"
  echo "OK: disk usage ${USAGE_PCT}% (< ${WARN_PCT}%)."
  exit 0
fi

if [ "${LAST_SENT}" = "${TODAY}" ]; then
  echo "WARN: disk usage ${USAGE_PCT}% (>= ${WARN_PCT}%), already alerted today (${TODAY})."
  exit 0
fi

if [ -z "${RESEND_API_KEY:-}" ] || [ -z "${ALERT_EMAIL_TO:-}" ] || [ -z "${ALERT_EMAIL_FROM:-}" ]; then
  echo "ERROR: disk usage ${USAGE_PCT}% (>= ${WARN_PCT}%) but RESEND_API_KEY/ALERT_EMAIL_TO/ALERT_EMAIL_FROM missing from ${SECRETS_ENV}; cannot send alert." >&2
  exit 1
fi

DF_DETAIL="$(df -h / | tail -1)"

curl -sf -X POST "https://api.resend.com/emails" \
  -H "Authorization: Bearer ${RESEND_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"from":"%s","to":["%s"],"subject":"vps-infra: disk usage at %s%% on %s","text":"Root disk usage is %s%% (threshold %s%%).\n\ndf -h /:\n%s\n\nInvestigate before this cascades into an outage (see plans/2026-07-23-remark42-comment-backup-recovery.md in pcbisolation for the incident this is guarding against)."}' \
    "${ALERT_EMAIL_FROM}" "${ALERT_EMAIL_TO}" "${USAGE_PCT}" "$(hostname)" "${USAGE_PCT}" "${WARN_PCT}" "${DF_DETAIL}")"

echo "${TODAY}" > "${STATE_FILE}"
echo "ALERT SENT: disk usage ${USAGE_PCT}% (>= ${WARN_PCT}%)."
