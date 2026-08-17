# Scaling

How the platform scales — and in particular how the expensive GPU worker is
turned on and off.

## What scales

- **account-api / ai-worker / orchestrator** — run 24/7 on the Main VPS.
- **marker-worker (GPU)** — ephemeral; started and stopped by the orchestrator.
  This is the main cost lever.

## GPU lifecycle

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
Idle timeout (10 min)
        │
        ▼
Stop GPU VPS
```

## Configuration (operational parameters, not business rules)

```env
MARKER_SCALE_UP_THRESHOLD=20
MARKER_IDLE_TIMEOUT_SECONDS=600
MARKER_START_TIMEOUT_SECONDS=600
MARKER_HEALTHCHECK_INTERVAL_SECONDS=15
MARKER_MAX_WORKERS=1
```

`20` is an **operational parameter**, not a business rule — it must be tunable
via config, never hard-coded.

## Beyond a plain threshold

For MVP `queue >= 20` is fine. Later, consider scheduling on estimated work:

```text
queue_size
+ estimated_processing_time
+ GPU_startup_time
```

Example: 10 documents × 2 min = 20 min of work; GPU startup = 5 min — it may be
cheaper to start the GPU at 10 documents than at 20. Future policy:

```text
estimated_work_seconds > threshold  →  START GPU
```

## Metrics that drive scaling decisions

```text
marker_queue_size
marker_processing_seconds
marker_startup_seconds
marker_idle_seconds
document_pipeline_latency
llm_requests_total / llm_tokens_total
```

These matter because GPU cost is proportional to uptime — measure idle and
startup time to tune the threshold.
