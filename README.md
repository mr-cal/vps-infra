# VPS Infrastructure

Podman Compose setup for a DigitalOcean VPS running multiple websites behind Caddy.

## Architecture

```
Internet ──► Caddy (ports 80/443, auto-TLS)
               ├──► craft-dashboard:8000 (FastAPI/Gunicorn)
               ├──► /srv/egg-calculator (static file_server, eggcalculator.com)
               ├──► /srv/pcbisolation (static file_server, pcbisolation.com)
               └──► vps-infra_remark42_1:8080 (comments.pcbisolation.com)
```

Services are split into separate Compose files joined by a shared podman
network (`vps-net`), so each service can be updated and restarted
independently.

| Compose file | Services |
|---|---|
| `docker-compose.caddy.yml` | Caddy reverse proxy, static sites (eggcalculator.com, pcbisolation.com) |
| `docker-compose.craft-dashboard.yml` | craft-dashboard app, PostgreSQL |
| `docker-compose.remark42.yml` | Remark42 self-hosted comments (comments.pcbisolation.com) |

## First-time VPS setup

The deploy workflow (`deploy.yml`) handles installing podman, cloning this
repo to `/opt/vps-infra`, creating the `vps-net` network, and starting all
services. The only manual steps are:

**1. Add GitHub Actions secrets** (repo Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `VPS_HOST` | VPS IP address |
| `VPS_USER` | SSH username |
| `VPS_SSH_KEY` | Private SSH key for the deploy user |
| `DB_PASSWORD` | Strong password for the PostgreSQL database |
| `REMARK_SECRET` | Random secret for Remark42 JWT signing (`openssl rand -hex 32`) |
| `AKISMET_KEY` | Akismet API key for comment spam filtering |
| `REMARK_ADMIN_PASSWD` | Remark42 admin password |
| `REMARK_ADMIN_EMAIL` | Remark42 admin email address |
| `RESEND_API_KEY` | Resend API key for Remark42 email notifications |

**Also add to `mr-cal/pcbisolation`** (Settings → Secrets and variables → Actions):

| Secret | Value | Required permissions |
|---|---|---|
| `VPSINFRA_PAT` | Fine-grained PAT scoped to `mr-cal/vps-infra` | Contents: Read and write |

The `VPSINFRA_PAT` is used by the pcbisolation CI to trigger a `repository_dispatch` event that redeploys this repo after the static site is updated. Create it at https://github.com/settings/personal-access-tokens/new with **Repository access → Only select repositories → mr-cal/vps-infra** and **Permissions → Repository permissions → Contents → Read and write**.

**2. Create the env file on the VPS:**

```bash
cp /opt/vps-infra/.env.example /opt/vps-infra/.env
chmod 600 /opt/vps-infra/.env
# Edit /opt/vps-infra/.env — paste the DB_PASSWORD value into DATABASE_URL,
# replacing <password>. Fill in the remaining tokens.
```

**3. Trigger the first deploy** by pushing to `main` or running the workflow
manually. The deploy creates a podman secret for the DB password so it never
appears in logs, then starts all services.

## Adding a new service

1. Create `docker-compose.<name>.yml` with the service definition.
2. Join the `vps-net` network (see existing files for the pattern).
3. Add a route in `caddy/Caddyfile`.
4. Add `podman pull` and `podman-compose -f docker-compose.<name>.yml up -d` lines to `deploy.yml`.
5. Push to `main` — the deploy workflow will start the new service.

## Rotating the DB password

If you change the `DB_PASSWORD` GitHub secret, the podman secret gets updated
on the next deploy but postgres won't accept the new password — it was set
when the data volume was first initialized and is stored there. You need to
wipe the volume and let postgres reinitialize.

⚠️ This destroys all data. On a live system, use `ALTER USER` instead (see below).

```bash
# On the VPS — remove containers in dependency order, then wipe the volume:
podman rm vps-infra_craft-dashboard_1
podman rm vps-infra_postgres_1
podman volume rm vps-infra_pgdata
```

Then retrigger the deploy. Postgres will initialize fresh with the new password.

To change the password without losing data:

```bash
podman exec -it vps-infra_postgres_1 psql -U craft_dashboard -c \
  "ALTER USER craft_dashboard WITH PASSWORD 'newpassword';"
```

Then update `DATABASE_URL` in `/opt/vps-infra/.env` to match.


On the VPS:

```bash
# Container status
podman ps -a

# Logs
podman logs vps-infra_caddy_1
podman logs vps-infra_postgres_1
podman logs vps-infra_craft-dashboard_1

# Follow logs live
podman logs -f vps-infra_caddy_1

# Network
podman network inspect vps-net
```

From another machine:

```bash
# Check DNS resolves
dig +short <domain>

# Check HTTP redirect and HTTPS
curl -I http://<domain>
curl -I https://<domain>

# Check a specific endpoint
curl https://<domain>/health
```

## Backups

`backups/backup.sh` dumps the PostgreSQL database daily (via host crontab)
and retains backups for 14 days.

## Deployment

Pushing to `main` triggers `.github/workflows/deploy.yml`, which SSHs to the
VPS, pulls the latest code, and restarts services.
