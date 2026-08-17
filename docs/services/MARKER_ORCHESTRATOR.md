# Marker Orchestrator

Permanent service on the Main VPS that decides **when the GPU VPS must exist**.
This is the economic core of the platform: GPU time costs money, so the
orchestrator keeps the node down unless there is real work.

## Responsibilities

- Monitor RabbitMQ `document.convert` queue depth.
- Track the marker-worker heartbeat.
- Call the provider API (`apps/marker-orchestrator/app/provider/provider.py`)
  to start/stop the GPU VPS.
- Persist decision state (`apps/marker-orchestrator/app/state/repository.py`).

## Policy

```text
Queue depth >= 20
        │
        ▼
Request GPU start
        │
        ▼
Wait for heartbeat
        │
        ▼
Worker processes queue
        │
        ▼
Queue empty
        │
        ▼
Idle timeout
        │
        ▼
Stop GPU VPS
```

Policy lives in `apps/marker-orchestrator/app/scaling/policy.py`.

## Configuration (operational parameters, not business rules)

```env
MARKER_SCALE_UP_THRESHOLD=20
MARKER_IDLE_TIMEOUT_SECONDS=600
MARKER_START_TIMEOUT_SECONDS=600
MARKER_HEALTHCHECK_INTERVAL_SECONDS=15
MARKER_MAX_WORKERS=1
```

The threshold `20` is an operational parameter, tunable in production. Do not
hard-code it.

## Future: estimated-work scheduling

Instead of a bare queue-threshold, weigh queue size against estimated processing
time and GPU startup time:

```text
estimated_work_seconds = queue_size × avg_doc_seconds
START GPU  if  estimated_work_seconds > threshold
```

For MVP `queue >= 20` is acceptable.