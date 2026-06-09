# vps-infra

## Server

- IP: ask user
- SSH: ask user
- OS: Ubuntu 24.04
- RAM: 458MB + 1GB swap (`/swapfile`)
- Disk: 10GB
- Hosting: DigitalOcean — firewall managed via cloud console, not UFW

## Architecture

Two podman-compose stacks sharing a `vps-net` bridge network:

- `docker-compose.caddy.yml` — Caddy reverse proxy, handles TLS automatically
- `docker-compose.craft-dashboard.yml` — FastAPI app + PostgreSQL (pgvector)

Both stacks use project name `vps-infra` (inferred from `/opt/vps-infra`). Never use
`--remove-orphans` — it will remove containers from the other stack.

## Deployment

Push to `main` triggers `.github/workflows/deploy.yml` via `appleboy/ssh-action`.

Required GitHub Actions secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `DB_PASSWORD`.

The DB password is passed as a podman secret (not an env var) so it doesn't appear
in `podman inspect` output or logs or in CI logs.

## Known Quirks

**podman-compose exit codes**: `podman-compose up -d` exits 0 even on failure. Use
`podman ps --filter status=running | grep -q <name>` to verify containers actually started.

**podman wait**: `podman wait --condition running` always exits 0. Don't use it to
check startup success.

**nftables forward rule**: A systemd service (`podman-forward-fix.service`) inserts
missing nftables rules on boot that allow new inbound connections to reach containers.
Without it, external traffic to ports 80/443 is silently dropped even with the DO
firewall open. If containers are unreachable externally after a reboot, check
`systemctl status podman-forward-fix.service`. The deploy script also inserts these
rules after starting containers. The service runs `/usr/local/sbin/podman-forward-fix.sh`
which adds both IPv4 (`ip filter NETAVARK_FORWARD`) and IPv6 (`ip6 filter NETAVARK_FORWARD`)
rules.

**Netavark "Chain already exists" (Podman 4.9.3 bug)**: When a container joins
`vps-net`, Netavark creates `NETAVARK_FORWARD` chains in the kernel's ip and ip6 filter
tables. When the network is removed, Netavark leaves the chains behind. On the next
deploy, the first container fails to start because Netavark tries to create
`NETAVARK_FORWARD` and it already exists. Fix: after `podman network rm`, explicitly
delete both chains with `nft flush/delete chain ip filter NETAVARK_FORWARD` and
`nft flush/delete chain ip6 filter NETAVARK_FORWARD`. Also: craft-dashboard has
`--requires=postgres`, so containers must be removed in reverse dependency order
(craft-dashboard → caddy → postgres) before `podman network rm` will succeed.
See the restart procedure below.

**IPv6 requires ip6table_nat kernel module**: The kernel modules `ip6table_nat` and
`ip6table_filter` must be loaded for Netavark's ip6 NAT/DNAT rules to work. These are
persisted via `/etc/modules-load.d/ip6tables.conf`. Without them, IPv6 connections time
out even though conmon holds `[::]:443` — the DNAT target silently fails.

**Image names must be fully qualified**: `/etc/containers/registries.conf` has no
unqualified search registries. Always use `docker.io/library/caddy:2-alpine`, not
`caddy:2-alpine`.

## Useful Commands (run on VPS)

```bash
# Check container status
podman ps -a --format "{{.Names}} {{.Status}}"

# Follow logs
podman logs -f vps-infra_craft-dashboard_1

# Verify site is up (run this after every change or deployment)
# Use --resolve because connecting to the external IP from the VPS itself times out.
curl -s -o /dev/null -w "%{http_code}" \
  --resolve craft-dashboard.name:443:127.0.0.1 \
  https://craft-dashboard.name/
# Expected: 200

# Restart all services — remove in reverse dependency order, delete the
# stale NETAVARK_FORWARD chains (ip and ip6), then recreate network and start containers.
podman rm -f vps-infra_craft-dashboard_1 2>/dev/null || true
podman rm -f vps-infra_caddy_1 2>/dev/null || true
podman rm -f vps-infra_postgres_1 2>/dev/null || true
podman network rm vps-net 2>/dev/null || true
nft flush chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft flush chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
podman network create --ipv6 vps-net
cd /opt/vps-infra
podman-compose -f docker-compose.caddy.yml up -d
podman-compose -f docker-compose.craft-dashboard.yml up -d
SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -v ':' | head -1)
IPV6_SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep ':' | head -1)
nft insert rule ip filter NETAVARK_FORWARD ip daddr "$SUBNET" ct state new accept
nft insert rule ip6 filter NETAVARK_FORWARD ip6 daddr "$IPV6_SUBNET" ct state new accept
# Verify
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
```
