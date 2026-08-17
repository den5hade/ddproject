# Production

Main VPS deployment. Full topology in
[architecture/OVERVIEW.md](../architecture/OVERVIEW.md) and
[STRUCTURE.md](../../STRUCTURE.md).

## Main VPS (`infrastructure/main-vps/`)

`docker-compose.yml`: nginx, account-api, marker-orchestrator, ai-worker,
postgres, qdrant. Python images build from the **repo root** so they can
`COPY packages/`. Web assets are published to a `web-dist` volume served by
nginx.

## Rabbit VPS (`infrastructure/rabbitmq-vps/`)

RabbitMQ + management. Bind ports to the **tailnet interface IP** in
production; keep 15672 inside the mesh. Credentials in `.env.example`.

## Environment

- `.env.example` documents every variable.
- `RABBITMQ_URL` points at the Rabbit VPS tailnet IP.
- Hard requirements (see [security/AUTHENTICATION.md](../security/AUTHENTICATION.md)):
  - `JWT_SECRET_KEY` — random, rotated from the dev default.
  - `AUTH_HMAC_KEY` — required for refresh-token hashing.
  - `RABBITMQ_URL`, `REDIS_URL`.
  - `JWT_ACCESS_EXPIRE_MINUTES`, `JWT_REFRESH_EXPIRE_DAYS`.

## CI/CD

`.github/workflows/`:

| Workflow | Purpose |
|----------|---------|
| `test.yml` | uv pytest (Python) + `npm run build` (web) |
| `build.yml` | every Python app + web → container registry |
| `deploy-main.yml` | on main services/web/infra changes → SSH pull & restart on Main VPS |
| `deploy-marker.yml` | rebuild GPU image on `apps/marker-worker/**` or `packages/**` |

## TODO

- Backups/PITR policy (see [data/DATABASE.md](../data/DATABASE.md)).
- Monitoring/alerting wiring (metrics in [architecture/SCALING.md](../architecture/SCALING.md)).