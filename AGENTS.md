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

**Netavark "Chain already exists" (Podman 4.9.3 bug)**: When containers are removed
without the network being properly torn down, Netavark leaves stale iptables chains
in the kernel. The next `podman run` fails with "iptables: Chain already exists".
`podman network rm --force` does NOT work here because craft-dashboard uses
`--requires=postgres`, so Podman refuses to remove postgres while craft-dashboard
exists, even with `--force`. Remove containers in reverse dependency order first
(craft-dashboard, caddy, postgres), then `podman network rm vps-net` — Netavark
will cleanly tear down the chains. Never use `podman stop` + `podman start`.

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

# Restart all services — remove in reverse dependency order (craft-dashboard
# depends on postgres via --requires, so craft-dashboard must go first).
podman rm -f vps-infra_craft-dashboard_1 2>/dev/null || true
podman rm -f vps-infra_caddy_1 2>/dev/null || true
podman rm -f vps-infra_postgres_1 2>/dev/null || true
podman network rm vps-net 2>/dev/null || true
podman network create vps-net
cd /opt/vps-infra
podman-compose -f docker-compose.caddy.yml up -d
podman-compose -f docker-compose.craft-dashboard.yml up -d
SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}}{{end}}')
nft insert rule ip filter NETAVARK_FORWARD ip daddr "$SUBNET" ct state new accept
# Verify
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
```
