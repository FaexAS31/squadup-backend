# Infrastructure

Docker Compose setup for SquadUp. Runs the backend, frontend, database, and monitoring stack together.

## Services

| Service | Port | Description |
|---------|------|-------------|
| Backend (Daphne) | 8000 | Django ASGI server |
| PostgreSQL 16 | 5432 | Main database |
| Redis 7 | 6379 | Channel layer for WebSockets |
| Nginx | 80 / 443 | Reverse proxy |
| Prometheus | 9090 | Metrics collection |
| Loki | 3100 | Log aggregation |
| Grafana | 3000 | Dashboards |
| pgAdmin | 5050 | Database admin (optional, `tools` profile) |

## Running locally

```bash
# Copy and fill in the env file (see .env.example in the repo root)
cp ../.env.example .env

# Start all services
docker compose up -d

# Check status
docker compose ps
```

Certbot (SSL) only runs when `COMPOSE_PROFILES=ssl` is set in the env file. For local development you can skip it.

## Nginx

`nginx/default.conf` is the production config with SSL. Replace `yourdomain.com` with your actual domain before deploying. `nginx/staging.conf` is the same but for a staging environment running on a different port.

## Monitoring

Grafana datasources and dashboards are auto-provisioned from `grafana/provisioning/` on startup. No manual setup needed after `docker compose up`.

