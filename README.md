# VPS Infrastructure

Podman Compose setup for a Linode VPS running multiple websites behind Caddy.

## Architecture

```
Internet ──► Caddy (ports 80/443, auto-TLS)
               ├──► craft-dashboard:8000 (FastAPI/Gunicorn)
               ├──► /srv/egg-calculator (static file_server)
               └──► (more services as needed)
```

Services are split into separate Compose files joined by a shared podman
network (`vps-net`), so each service can be updated and restarted
independently.

| Compose file | Services |
|---|---|
| `docker-compose.caddy.yml` | Caddy reverse proxy, static sites |
| `docker-compose.craft-dashboard.yml` | craft-dashboard app, PostgreSQL |

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

**2. Trigger the first deploy** by pushing to `main` or running the workflow
manually. It will fail on craft-dashboard because `/opt/vps-infra/.env`
doesn't exist yet — that's expected.

**3. Create the env file on the VPS:**

```bash
cp /opt/vps-infra/.env.example /opt/vps-infra/.env
# Edit /opt/vps-infra/.env with real values
```

**4. Re-run the deploy workflow.** All services should come up cleanly.

## Adding a new service

1. Create `docker-compose.<name>.yml` with the service definition.
2. Join the `vps-net` network (see existing files for the pattern).
3. Add a route in `caddy/Caddyfile`.
4. Add `podman pull` and `podman-compose -f docker-compose.<name>.yml up -d` lines to `deploy.yml`.
5. Push to `main` — the deploy workflow will start the new service.

## Debugging

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
