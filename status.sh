#!/usr/bin/env bash
# status.sh — check site availability and container health on the VPS

set -euo pipefail

VPS_HOST="167.99.14.211"
VPS_USER="root"
SITE="craft-dashboard.name"
SITE_URL="https://${SITE}/"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }

# ── Network checks ──────────────────────────────────────────────────────────

echo ""
echo "━━━ Network reachability ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# IPv4
STATUS4=$(curl -4 -s -o /dev/null -w "%{http_code}" --max-time 10 "${SITE_URL}" 2>/dev/null || echo "000")
if [ "${STATUS4}" = "200" ]; then
  ok "IPv4  ${SITE_URL}  →  HTTP ${STATUS4}"
else
  fail "IPv4  ${SITE_URL}  →  HTTP ${STATUS4}"
fi

# IPv6
IPV6_ADDR=$(dig +short AAAA "${SITE}" 2>/dev/null | head -1)
if [ -n "${IPV6_ADDR}" ]; then
  STATUS6=$(curl -6 -s -o /dev/null -w "%{http_code}" --max-time 10 \
    --resolve "${SITE}:443:[${IPV6_ADDR}]" "${SITE_URL}" 2>/dev/null || echo "000")
  if [ "${STATUS6}" = "200" ]; then
    ok "IPv6  ${SITE_URL}  (${IPV6_ADDR})  →  HTTP ${STATUS6}"
  else
    fail "IPv6  ${SITE_URL}  (${IPV6_ADDR})  →  HTTP ${STATUS6}"
  fi
else
  warn "IPv6  no AAAA record for ${SITE}"
fi

# ── Container + host checks via SSH ─────────────────────────────────────────

echo ""
echo "━━━ VPS containers (${VPS_HOST}) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" \
  'podman ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"' 2>/dev/null \
  | while IFS= read -r line; do
      if echo "${line}" | grep -qE '^(NAMES|NAME)'; then
        echo "  ${line}"
      elif echo "${line}" | grep -q "Up "; then
        echo -e "  ${GREEN}${line}${NC}"
      else
        echo -e "  ${RED}${line}${NC}"
      fi
    done

echo ""
echo "━━━ VPS system ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" '
  echo "  Uptime:    $(uptime -p)"
  echo "  Load:      $(cut -d" " -f1-3 /proc/loadavg)"
  echo "  Memory:    $(free -h | awk "/^Mem/{printf \"%s used / %s total\", \$3, \$2}")"
  echo "  Disk (/):  $(df -h / | awk "NR==2{printf \"%s used / %s total (%s)\", \$3, \$2, \$5}")"
  echo "  IPv6 DNAT: $(ip6tables -t nat -L OUTPUT -n 2>/dev/null | grep -c "vps-infra-ipv6-dnat") rule(s) tagged vps-infra-ipv6-dnat"
' 2>/dev/null

echo ""
