# Agent Notes — vps-infra

## Server

- **IP**: 167.99.14.211
- **OS**: Ubuntu 22.04
- **RAM**: 458MB + 1GB swap (`/swapfile`)
- **Disk**: 8.7GB total, ~3GB free
- **SSH**: `ssh root@167.99.14.211`
- **Hosting**: DigitalOcean — firewall managed via cloud console, not UFW

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
in `podman inspect` output or logs.

## Known Quirks

**podman-compose exit codes**: `podman-compose up -d` exits 0 even on failure. Use
`podman ps --filter status=running | grep -q <name>` to verify containers actually started.

**podman wait**: `podman wait --condition running` always exits 0. Don't use it to
check startup success.

**nftables forward rule**: A systemd service (`podman-forward-fix.service`) inserts a
missing nftables rule on boot that allows new inbound connections to reach containers.
Without it, external traffic to ports 80/443 is silently dropped even with the DO
firewall open. If containers are unreachable externally after a reboot, check
`systemctl status podman-forward-fix.service`.

**Image names must be fully qualified**: `/etc/containers/registries.conf` has no
unqualified search registries. Always use `docker.io/library/caddy:2-alpine`, not
`caddy:2-alpine`.

## Useful Commands (run on VPS)

```bash
# Check container status
podman ps -a --format "{{.Names}} {{.Status}}"

# Follow logs
podman logs -f vps-infra_craft-dashboard_1

# Check memory
free -m

# Restart a service
cd /opt/vps-infra
podman-compose -f docker-compose.craft-dashboard.yml up -d
```
