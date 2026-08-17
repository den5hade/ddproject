# GPU Worker (Marker VPS)

The ephemeral GPU node running `marker-worker`. Started/stopped by the
orchestrator to control cost.

## Infrastructure (`infrastructure/marker-vps/`)

- `docker-compose.yml`: only `marker-worker` (with NVIDIA device reservation).
- `systemd/marker-worker.service`: oneshot unit to start/stop the node.
- `scripts/startup.sh`: boot sequence — docker login, tailscale join, pull
  image, compose up.
- `scripts/shutdown.sh`: compose down (callable by the orchestrator to save
  money).

## Key property

The GPU VPS needs **no repo access at all** — it only pulls
`registry/…/marker-worker:tag`. This is what makes it replaceable and
powerable-on/off freely.

## Lifecycle

```text
Queue depth >= MARKER_SCALE_UP_THRESHOLD  →  orchestrator requests GPU start
Wait for heartbeat                        →  worker pulls image, joins mesh
Worker processes queue
Queue empty                               →  idle timeout
Stop GPU VPS
```

Config in [architecture/SCALING.md](../architecture/SCALING.md).

## Hardening notes

- GPU instance must be **stateless** — no local DB, no local files
  (see [services/MARKER_WORKER.md](../services/MARKER_WORKER.md)).
- Tailscale join happens at boot so the changing public IP never matters.
- Image is signed/pinned; registry access only, no source access.
