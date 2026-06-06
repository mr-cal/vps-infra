# VPS Infrastructure

Docker Compose setup for a Linode VPS running multiple websites behind Caddy.

## Architecture

```
Internet ──► Caddy (ports 80/443, auto-TLS)
               ├──► craft-dashboard:8000 (FastAPI/Gunicorn)
               ├──► /srv/egg-calculator (static file_server)
               └──► (more services as needed)
```

Services are split into separate Compose files joined by a shared Docker
network (`vps-net`), so each service can be updated and restarted
independently.

| Compose file | Services |
|---|---|
| `docker-compose.caddy.yml` | Caddy reverse proxy, static sites |
| `docker-compose.craft-dashboard.yml` | craft-dashboard app, PostgreSQL |

## Quick start

Run on the VPS:

```bash
# 1. Create the shared network
docker network create vps-net

# 2. Configure secrets
cp .env.example .env
# Edit .env with real values

# 3. Start services
docker compose -f docker-compose.caddy.yml up -d
docker compose -f docker-compose.craft-dashboard.yml up -d
```

## Adding a new service

1. Create `docker-compose.<name>.yml` with the service definition.
2. Join the `vps-net` network (see existing files for the pattern).
3. Add a route in `caddy/Caddyfile`.
4. Update `.github/workflows/deploy.yml` to include the new compose file.

## Backups

`backups/backup.sh` dumps the PostgreSQL database daily (via host crontab)
and retains backups for 14 days.

## Deployment

Pushing to `main` triggers `.github/workflows/deploy.yml`, which SSHs to the
VPS, pulls the latest code, and restarts services.
