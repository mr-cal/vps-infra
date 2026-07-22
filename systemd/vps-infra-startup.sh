#!/bin/bash
# Start VPS containers and apply all required firewall rules.
# Run on boot via vps-infra-startup.service.
# Mirrors the deploy workflow so a reboot brings the site back up automatically.

set -euo pipefail

cd /opt/vps-infra

# Remove any leftover containers and stale network state (same logic as the
# deploy workflow). Netavark leaves NETAVARK_FORWARD chains in the kernel when
# the network is removed; clean them up so the next network create succeeds.
podman rm -f vps-infra_craft-dashboard_1 2>/dev/null || true
podman rm -f vps-infra_caddy_1 2>/dev/null || true
podman rm -f vps-infra_postgres_1 2>/dev/null || true
podman rm -f vps-infra_llm-evaluate_1 2>/dev/null || true
podman network rm vps-net 2>/dev/null || true
nft flush chain ip  filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip  filter NETAVARK_FORWARD 2>/dev/null || true
nft flush chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
podman network create --ipv6 vps-net

# Start services (uses locally cached images — no pull on boot).
podman-compose -f docker-compose.caddy.yml up -d
podman-compose -f docker-compose.craft-dashboard.yml up -d
podman-compose -f docker-compose.llm-evaluate.yml up -d

# Add missing ct state new rules to NETAVARK_FORWARD (netavark omits them).
SUBNET=$(podman network inspect vps-net \
  --format '{{range .Subnets}}{{.Subnet}} {{end}}' \
  | tr ' ' '\n' | grep -v ':' | head -1)
IPV6_SUBNET=$(podman network inspect vps-net \
  --format '{{range .Subnets}}{{.Subnet}} {{end}}' \
  | tr ' ' '\n' | grep ':' | head -1)
nft insert rule ip  filter NETAVARK_FORWARD ip  daddr "$SUBNET"      ct state new accept 2>/dev/null || true
nft insert rule ip6 filter NETAVARK_FORWARD ip6 daddr "$IPV6_SUBNET" ct state new accept 2>/dev/null || true

# Fix netavark's broken IPv6 DNAT rules (see deploy.yml for full explanation).
# IMPORTANT: the OUTPUT rule must be scoped with -d "$PUBLIC_IPV6" (hairpin NAT only).
# An earlier version matched --dport with no destination filter, which hijacked
# EVERY outbound IPv6 HTTPS/HTTP connection from the host itself (snap, apt, curl to
# any external site) -- not just the intended health-check hairpin. Stale rules from
# previous runs are removed by line number (not by rule spec) since the DNAT target
# changes every time the caddy container is recreated.
CADDY_IPV6=$(podman inspect vps-infra_caddy_1 \
  --format '{{range .NetworkSettings.Networks}}{{.GlobalIPv6Address}}{{end}}')
PUBLIC_IPV6=$(ip -6 addr show eth0 | awk '/inet6.*global/{print $2}' | cut -d/ -f1 | head -1)
for CHAIN in PREROUTING OUTPUT; do
  while true; do
    LINE=$(ip6tables -t nat -L "$CHAIN" --line-numbers -n | awk '/vps-infra-ipv6-dnat/{print $1; exit}')
    [ -z "$LINE" ] && break
    ip6tables -t nat -D "$CHAIN" "$LINE"
  done
done
for PORT in 80 443; do
  # PREROUTING: genuinely inbound traffic from external IPv6 clients.
  ip6tables -t nat -I PREROUTING 1 -p tcp --dport "$PORT" \
    -m comment --comment "vps-infra-ipv6-dnat" \
    -j DNAT --to-destination ["$CADDY_IPV6"]:"$PORT"
  # OUTPUT: ONLY hairpin traffic the host sends to its OWN public IPv6 address.
  ip6tables -t nat -I OUTPUT 1 -p tcp -d "$PUBLIC_IPV6" --dport "$PORT" \
    -m comment --comment "vps-infra-ipv6-dnat" \
    -j DNAT --to-destination ["$CADDY_IPV6"]:"$PORT"
done
