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
- `flashcandy.us` — static site from the `static-sites/flashcandy` git submodule (migrated from cPanel; DNS not yet cut over — see `mr-cal/flashcandy/plans/`)
- `comments.pcbisolation.com` — Remark42 self-hosted comment system (`docker-compose.remark42.yml`), data persisted in `remark42_data` volume; admin UI at `/web`

Both stacks use project name `vps-infra` (inferred from `/opt/vps-infra`). Never use
`--remove-orphans` — it will remove containers from the other stack.

## Deployment

Push to `main` triggers `.github/workflows/deploy.yml` via `appleboy/ssh-action`.

Required GitHub Actions secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `DB_PASSWORD`.

The DB password is passed as a podman secret (not an env var) so it doesn't appear
in `podman inspect` output or logs or in CI logs.

## Pre-commit and CI
This repo has a CI pipeline and pre-commit hooks. **All linters must pass before committing and before deploying.**

**Before committing:**
```bash
make test        # runs all pre-commit hooks (CI parity)
# or individually:
make shellcheck  # lint shell scripts
make yamllint    # lint YAML configs
make gitleaks    # scan for secrets
make format      # auto-format shell scripts (shfmt)
```

**Before deploying:**
- Push to `main` triggers `.github/workflows/deploy.yml` automatically.
- **Wait for CI to succeed on `main`** before assuming the deploy is safe. A failed CI means the commit has linting or security issues.
- The CI runs `shellcheck`, `yamllint`, `gitleaks`, and `pre-commit` (which includes `shellcheck`, `shfmt`, `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `detect-private-key`, `gitleaks`, and `cron-syntax`).
- If CI fails, fix the reported issues locally (`make lint` will show what's wrong) and push again.
- Use `make setup` to install pre-commit hooks locally so they run automatically on `git commit`.

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

**Host outbound IPv6 HTTPS hijacked by our own OUTPUT DNAT rule (fixed)**: All host-level
outbound HTTPS/HTTP connections over IPv6 — `curl -6 https://<anything>`, `snap install`,
`apt`, GitHub API calls — used to fail immediately after ClientHello with
`tlsv1 alert internal error`, regardless of destination (Google, Cloudflare, Fastly,
kernel.org, etc.). This was misdiagnosed once as a datacenter/DigitalOcean IPv6 network
problem; it was not. The real cause: the `vps-infra-ipv6-dnat` rule added to the `OUTPUT`
chain of `ip6tables -t nat` (in `deploy.yml` and `systemd/vps-infra-startup.sh`) matched
`--dport 443`/`80` with **no destination filter** (`::/0`), intended only to let the
deploy script's own health check hairpin back to Caddy via the droplet's public IPv6
address. Because it had no `-d` restriction, it silently DNATed *every* outbound IPv6
connection on those ports — including to unrelated external hosts — into the Caddy
container, which doesn't recognize SNI for external domains and kills the handshake.
Worse, the cleanup loop used `ip6tables -D <chain> ... -j DNAT` (no `--to-destination`),
which never matched existing rules once Caddy's container IP changed on redeploy, so
~126+ stale duplicate rules silently accumulated over time. Fix: the `OUTPUT` rule is
now scoped with `-d "$PUBLIC_IPV6"` (the droplet's own public IPv6 address only), so it
only affects hairpin traffic to the host's own address; `PREROUTING` (genuinely inbound
traffic) is left unscoped since only packets truly addressed to this host reach it
anyway. Stale-rule cleanup now deletes by line number (`ip6tables -t nat -L "$CHAIN"
--line-numbers -n | awk '/vps-infra-ipv6-dnat/{print $1; exit}'`) instead of by rule
spec, so it reliably removes old entries regardless of a changed DNAT target. If
outbound IPv6 HTTPS ever breaks again, check `ip6tables -t nat -L OUTPUT -n` for
unscoped (`::/0` destination) or duplicated `vps-infra-ipv6-dnat` rules before assuming
a network-layer problem.

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
podman rm -f vps-infra_llm-evaluate_1 2>/dev/null || true
podman network rm vps-net 2>/dev/null || true
nft flush chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip filter NETAVARK_FORWARD 2>/dev/null || true
nft flush chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
nft delete chain ip6 filter NETAVARK_FORWARD 2>/dev/null || true
podman network create --ipv6 vps-net
cd /opt/vps-infra
podman-compose -f docker-compose.caddy.yml up -d
podman-compose -f docker-compose.craft-dashboard.yml up -d
podman-compose -f docker-compose.llm-evaluate.yml up -d
podman-compose -f /tmp/docker-compose.remark42.rendered.yml up -d
SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -v ':' | head -1)
IPV6_SUBNET=$(podman network inspect vps-net --format '{{range .Subnets}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep ':' | head -1)
nft insert rule ip filter NETAVARK_FORWARD ip daddr "$SUBNET" ct state new accept
nft insert rule ip6 filter NETAVARK_FORWARD ip6 daddr "$IPV6_SUBNET" ct state new accept
# Verify
curl -s -o /dev/null -w "%{http_code}" https://craft-dashboard.name/
curl -s -o /dev/null -w "%{http_code}" https://eggcalculator.com/
```
