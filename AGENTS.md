# vps-infra

## Server

- IP: 167.99.14.211 (IPv4), 2604:a880:400:d1:0:4:8a34:b001 (IPv6)
- SSH: `ssh root@167.99.14.211`
- OS: Ubuntu 24.04
- RAM: 458MB + 1GB swap (`/swapfile`)
- Disk: 10GB
- Hosting: DigitalOcean — firewall managed via cloud console, not UFW

## Architecture

Two podman-compose stacks sharing a `vps-net` bridge network:

- `docker-compose.caddy.yml` — Caddy reverse proxy, handles TLS automatically
- `docker-compose.craft-dashboard.yml` — FastAPI app + PostgreSQL (pgvector)
- `docker-compose.remark42.yml` — Remark42 self-hosted comment system

Sites served:

- `craft-dashboard.name` — reverse proxy to the FastAPI app
- `eggcalculator.com` — static site from the `static-sites/egg-calculator` git submodule
- `pcbisolation.com` — Hugo static site from `static-sites/pcbisolation` git submodule (built from `mr-cal/pcbisolation` `main`, published to `gh-pages`)
- `comments.pcbisolation.com` — Remark42 self-hosted comment system (`docker-compose.remark42.yml`), data persisted in `remark42_data` volume; admin UI at `/web`

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

**Remark42 data volume**: The rendered compose file is at `/tmp/docker-compose.remark42.rendered.yml`
(written by the deploy script). Because podman-compose 1.0.6 derives the project name from
the compose file's directory, this creates the volume `tmp_remark42_data` (project=`tmp`).
This is the production data volume. Do not confuse it with `vps-infra_remark42_data` (unused).

**Remark42 NOTIFY_TYPE**: When disabling notifications, set `NOTIFY_TYPE=none` not `NOTIFY_TYPE=`
(empty string). Remark42 rejects empty strings; valid values are `none`, `telegram`, `email`, `slack`.

**Restarting a single container without removing the network** (e.g., Remark42 restart to
change env vars): You cannot simply `podman rm -f` + re-run because Netavark will hit
"Chain already exists". Instead: flush+delete the nft chains (this briefly interrupts
existing container networking), then use `podman start` on the pre-created container:
```bash
# Edit /tmp/docker-compose.remark42.no-notify.yml with the desired env, then:
podman rm -f vps-infra_remark42_1
cd /opt/vps-infra
podman-compose -f /tmp/docker-compose.remark42.no-notify.yml up -d 2>/dev/null || true
# Container will be in "Created" state. Fix nft:
nft flush chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft flush chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
podman start vps-infra_remark42_1
sleep 5
# Re-add nft rules:
SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -v ':' | head -1)
IPV6_SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep ':' | head -1)
nft insert rule ip filter NETAVARK_FORWARD ip daddr "$SUBNET" ct state new accept 2>/dev/null || true
nft insert rule ip6 filter NETAVARK_FORWARD ip6 daddr "$IPV6_SUBNET" ct state new accept 2>/dev/null || true
```

 (`podman-forward-fix.service`) inserts
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
curl -s -o /dev/null -w "%{http_code}" \
  --resolve eggcalculator.com:443:127.0.0.1 \
  https://eggcalculator.com/
# Expected: 200

# Restart all services — remove in reverse dependency order, delete the
# stale NETAVARK_FORWARD chains (ip and ip6), then recreate network and start containers.
podman rm -f vps-infra_craft-dashboard_1 2>/dev/null || true
podman rm -f vps-infra_remark42_1 2>/dev/null || true
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
podman-compose -f /tmp/docker-compose.remark42.rendered.yml up -d
SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -v ':' | head -1)
IPV6_SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep ':' | head -1)
nft insert rule ip filter NETAVARK_FORWARD ip daddr "$SUBNET" ct state new accept
nft insert rule ip6 filter NETAVARK_FORWARD ip6 daddr "$IPV6_SUBNET" ct state new accept
# Verify
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
curl -s -o /dev/null -w "%{http_code}" https://eggcalculator.com/
```
