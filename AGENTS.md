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

**nftables forward rule**: A systemd service (`podman-forward-fix.service`) inserts a
missing nftables rule on boot that allows new inbound connections to reach containers.
Without it, external traffic to ports 80/443 is silently dropped even with the DO
firewall open. If containers are unreachable externally after a reboot, check
`systemctl status podman-forward-fix.service`. The deploy script also inserts this
rule after starting containers.

**podman stop/start doesn't work**: Due to a Netavark bug in Podman 4.9.3, using
`podman stop` + `podman start` on containers that share the vps-net network results
in "iptables: Chain already exists" errors. If containers crash or are killed without
the network being properly torn down, stale iptables chains persist in the kernel.
Always use the full restart procedure in "Useful Commands" below: flush nftables
tables, remove containers, remove+recreate network, podman-compose up.

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
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
# Expected: 200

# Restart all services (use this, not podman stop/start — see Known Quirks)
podman rm -f vps-infra_caddy_1 vps-infra_postgres_1 vps-infra_craft-dashboard_1 2>/dev/null || true
# Flush stale Netavark iptables chains (required if containers crashed or were killed)
nft flush table ip filter 2>/dev/null || true
nft flush table ip nat 2>/dev/null || true
podman network rm vps-net 2>/dev/null || true
podman network create vps-net
cd /opt/vps-infra
podman-compose -f docker-compose.caddy.yml up -d
podman-compose -f docker-compose.craft-dashboard.yml up -d
nft insert rule ip filter NETAVARK_FORWARD ip daddr 10.89.0.0/24 ct state new accept
# Verify
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
```
