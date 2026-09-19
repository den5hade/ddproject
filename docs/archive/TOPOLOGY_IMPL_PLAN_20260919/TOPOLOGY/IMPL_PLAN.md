# RabbitMQ Topology Bootstrap — Implementation Plan

Implementation plan for fixing silent message loss in the dev document pipeline by
decoupling **queue declaration** from **queue processing**, reproducing the
"queue always exists" property of the planned main (marker-orchestrator)
architecture. Currently the ai-worker is the *only* thing that declares
`document.convert` — and it is opt-in (`compose-dev` does not start it). Any
`document.uploaded` / `document.converted` published while the ai-worker is off
is silently dropped by the topic exchange (no `mandatory`, unroutable messages
vanish).

Depth sources:
`docs/messaging/RABBITMQ.md`, `docs/services/MARKER_ORCHESTRATOR.md`,
`apps/ai-worker/README.md`, `apps/ai-worker/UPLOAD_FLOW.md`,
`packages/messaging/messaging/consumer.py`.

**Revision 1** — initial plan. Derived from the
`IMPL_PLAN_SCHEMA.md` structure and the
`DOC_PROC_DEV_FLOW_IMPL_PLAN.md` exemplar.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current (broken) flow:**

```
make compose-dev → account-api + rabbitmq (+ workers), ai-worker NOT started (profiles: ["ai-worker"])
user upload → account-api → publish document.uploaded → pdf.events (topic)
                                                              ↓
                                              ❌ no bound queue (queue declared
                                                 only by ai-worker's Consumer.start)
                                                              ↓
                                              topic exchange silently drops the message
                                                              ↓
make compose-ai-worker → document.convert declared + bound → waits forever
                       → document stuck in "processing"
```

**Target flow:**

```
make compose-dev → rabbit-setup (one-shot) declares document.convert + bindings + DLX/DLQ
user upload → account-api → publish document.uploaded → pdf.events
                                                              ↓
                                              document.convert (durable, always bound)
                                                              ↓
                       while ai-worker is off: message buffers in the queue
                                                              ↓
make compose-ai-worker → ai-worker drains the backlog
```

**Why this is the right shape:** the main architecture splits two roles —

| Role | Main architecture | Stub (today) |
|---|---|---|
| Holds queue topology (declaration) | marker-orchestrator (long-running, permanent) | **ai-worker** (ephemeral, opt-in) — the invert |
| Drains the queue (processing) | marker-worker (ephemeral, GPU) | ai-worker |
| Publishes events | account-api | account-api (unchanged) |

This plan introduces the **queue-holder role** as a one-shot `rabbit-setup`
service. When the orchestrator lands, it replaces the one-shot with a
long-running service that runs the same `bootstrap()` + monitors queue depth.
**Publishers, queue names, routing keys, DLX/DLQ names and message formats do
not change** — no rework on the main-architecture migration.

### Invariants (locked)

1. **`document.convert` is declared by `rabbit-setup`, before `account-api` starts** — uploads made while the ai-worker is off must buffer, never drop.
2. **Declaration args match `Consumer` byte-for-byte** — bootstrap must reuse `Consumer.start()`, not re-implement `declare_*`. Otherwise a later worker hit a `PRECONDITION_FAILED` (queue exists with different args).
3. **`ai-worker` stays opt-in** (`profiles: ["ai-worker"]`) — only the *declaration responsibility* moves to infra. Processing stays optional, like marker-worker.
4. **Bootstrapped topology is minimal** — only `document.convert` now; orchestrator/notification/other queues are added by the orchestrator later.
5. **Document status stays mutated only in `apps/account-api/app/services/documents.py`** — unchanged by this plan.
6. **Unroutable-return is a log, not an exception** — `mandatory=True` + return callback logs a warning; the upload API must not start failing on partially-started stacks.

---

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | `messaging/topology.py` — single source of truth for consumer queues | [x] |
| 2 | ai-worker config reads queue/routing defaults from `topology` | [x] |
| 3 | `messaging/bootstrap.py` — declare-only bootstrap reusing `Consumer` | [x] |
| 4 | Publisher safety net: `confirm_delivery()` + `mandatory=True` + return log | [x] |
| 5 | Compose: `rabbit-setup` one-shot + `account-api` dependency + RabbitMQ volume | [x] |
| 6 | Tests (`packages/messaging/tests/`) + `make test` coverage | [x] |
| 7 | Docs: ai-worker README, UPLOAD_FLOW §9 | [x] |

---

## 2. Completed phases

### Phase 1 — `messaging/topology.py` [x]

New `packages/messaging/messaging/topology.py`: frozen `ConsumerBinding(queue,
routing_keys)`, constants `DOCUMENT_CONVERT_QUEUE` /
`DOCUMENT_CONVERT_ROUTING_KEYS`, and `CONSUMER_QUEUES` (one entry).

Files: `packages/messaging/messaging/topology.py`.

### Phase 2 — ai-worker config consumes topology defaults [x]

`apps/ai-worker/app/config.py` imports `DOCUMENT_CONVERT_QUEUE` /
`DOCUMENT_CONVERT_ROUTING_KEYS` from `messaging.topology` and uses them as the
`ai_worker_queue` / `ai_worker_routing_keys` defaults (env overrides unchanged).

Files: `apps/ai-worker/app/config.py`.

### Phase 3 — `messaging/bootstrap.py` declare-only bootstrap [x]

`bootstrap(dsn)` loops `CONSUMER_QUEUES`, creating a `Consumer` per spec,
`await start()` (full declaration incl. DLX/DLQ) then `close()`.
`_dsn_from_env()` resolves `RABBITMQ_URL` → `HOST/PORT/USER/PASSWORD/VHOST`
fallback; `main()` runs it.

**Deviation:** `bootstrap`/`main` are **not** re-exported from
`messaging/__init__.py`. Re-exporting the function `bootstrap` shadowed the
submodule `messaging.bootstrap` (so `from messaging import bootstrap` yielded the
function, not the module). The entrypoint is `python -m messaging.bootstrap`, so
no re-export is needed; `CONSUMER_QUEUES` / `ConsumerBinding` are exported.

Files: `packages/messaging/messaging/bootstrap.py`,
`packages/messaging/messaging/__init__.py`.

### Phase 4 — publisher safety net [x]

`connect_publisher` enables `channel.confirm_delivery()`, registers
`_on_return` (WARNING `unroutable_message routing_key=… type=…`), and passes the
channel to `Publisher`. `Publisher.publish` uses `mandatory=True`. Unroutable
messages are logged, not raised.

Files: `packages/messaging/messaging/publisher.py`.

### Phase 5 — compose `rabbit-setup` + volume [x]

`infrastructure/development/docker-compose.yml`: new one-shot `rabbit-setup`
(reuses `apps/account-api/Dockerfile`, runs
`/app/.venv/bin/python -m messaging.bootstrap`, `depends_on` rabbitmq healthy,
`restart: "no"`); `account-api.depends_on` += `rabbit-setup:
service_completed_successfully`; `rabbitmq` + top-level `rabbitmq_data` volume.

Files: `infrastructure/development/docker-compose.yml`.

### Phase 6 — tests + coverage [x]

`packages/messaging/tests/test_topology.py` (spec validity) and
`test_bootstrap.py` (fake `Consumer` records start/close; `_dsn_from_env`
resolution). Added `[dependency-groups] dev` to
`packages/messaging/pyproject.toml`; `make test` now runs
`packages/messaging/tests`.

Files: `packages/messaging/tests/test_topology.py`,
`packages/messaging/tests/test_bootstrap.py`,
`packages/messaging/pyproject.toml`, `Makefile`.

### Phase 7 — documentation [x]

`apps/ai-worker/README.md` and `apps/ai-worker/UPLOAD_FLOW.md` §9 now state the
topology is declared by `rabbit-setup`, the ai-worker is not the queue-holder,
and describe the marker-orchestrator migration path.

Files: `apps/ai-worker/README.md`, `apps/ai-worker/UPLOAD_FLOW.md`.

#### Implementation Status (all phases)

- **Tests.** `packages/messaging/tests`: 10 passed
  (`uv run --no-sync pytest tests/ -q` from `packages/messaging`). Regression:
  ai-worker 40 passed, objectstorage-worker 6 passed, notification-worker 11
  passed, account-api `test_document_events.py` 16 passed.
- **Lint.** `uvx ruff check packages/messaging apps/ai-worker/app/config.py`
  clean. Repo-wide `uvx ruff check apps packages tests` reports only 4
  **pre-existing** errors in `packages/storage/` (untouched here).
- **Lock.** `uv.lock` regenerated (`uv lock`) for the new `pdf-messaging` dev
  group.
- **Not yet exercised:** the live `make compose-dev` E2E (Phase 5 acceptance) —
  requires Docker and is left for manual verification:
  `make compose-dev` → check `document.convert` in the management UI at
  `:15672` → upload without ai-worker → `make compose-ai-worker` → status
  `completed`.

---

## 3. Phase details (all implemented)

### Phase 1 — `messaging/topology.py` single source of truth [x]

New `packages/messaging/messaging/topology.py`. A declarative, frozen
`ConsumerBinding(queue, routing_keys)` list consumed by both the bootstrap and
(after refactor) the workers.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ConsumerBinding:
    queue: str
    routing_keys: list[str]

DOCUMENT_CONVERT_QUEUE = "document.convert"
DOCUMENT_CONVERT_ROUTING_KEYS = ["document.uploaded", "document.converted"]

CONSUMER_QUEUES: list[ConsumerBinding] = [
    ConsumerBinding(DOCUMENT_CONVERT_QUEUE, DOCUMENT_CONVERT_ROUTING_KEYS),
]
```

**Accept:** `CONSUMER_QUEUES` holds exactly the ai-worker spec; importable from
`messaging.topology`.

### Phase 2 — ai-worker config consumes topology defaults [x]

`apps/ai-worker/app/config.py`: replace the hard-coded defaults
`ai_worker_queue = "document.convert"` and
`ai_worker_routing_keys = "document.uploaded,document.converted"` with the
constants from `messaging.topology` (`DOCUMENT_CONVERT_QUEUE`,
`",".join(DOCUMENT_CONVERT_ROUTING_KEYS)`). Env overrides (`AI_WORKER_QUEUE`,
`AI_WORKER_ROUTING_KEYS`) still win.

**Accept:** changing a value in `topology.py` no longer requires touching ai-worker config; unit tests still green.

### Phase 3 — `messaging/bootstrap.py` declare-only bootstrap [x]

New `packages/messaging/messaging/bootstrap.py`:

```python
async def bootstrap(dsn: str) -> None:
    for spec in CONSUMER_QUEUES:
        consumer = Consumer(dsn=dsn, queue_name=spec.queue, routing_keys=spec.routing_keys)
        await consumer.start()   # exchange + DLX fanout + DLQ + queue + bindings
        await consumer.close()

def main() -> None:              # DSN: RABBITMQ_URL → fallback HOST/PORT/USER/PASSWORD/VHOST
    asyncio.run(bootstrap(dsn))
```

Reusing `Consumer.start()` (consumer.py:36-58) guarantees the bootstrap declares
exactly what the live worker declares — including
`x-dead-letter-exchange: <queue>_dlx`, the `<queue>_dlq` queue and its binding by
**construction**, not by duplication. Export `bootstrap`/`main` from
`messaging/__init__.py`.

**Accept:** `python -m messaging.bootstrap` against a live broker creates
`document.convert` + bindings and exits; a subsequent `Consumer.start()` by the
ai-worker succeeds (no `PRECONDITION_FAILED`).

### Phase 4 — publisher safety net (`mandatory=True`, confirms, return log) [x]

`packages/messaging/messaging/publisher.py`:

- `connect_publisher`: `await channel.confirm_delivery()`; register
  `channel.add_on_return_callback(...)` logging
  `unroutable_message routing_key=%s type=%s` at WARNING.
- `Publisher` gains the channel; `publish(..., mandatory=True)`.
- Behavior: unroutable messages are **logged, not raised** — the upload API keeps
  working even when a queue has no binding.

**Accept:** publishing to a routing key with no bound queue writes a WARNING and
the caller sees success; broker-dispatched messages are publisher-confirmed.

### Phase 5 — compose: `rabbit-setup` + account-api dependency + RabbitMQ volume [x]

`infrastructure/development/docker-compose.yml`:

- New one-shot service `rabbit-setup` (pattern of `db-migrate`):
  - `build`: context `../..`, dockerfile `apps/account-api/Dockerfile` (its venv
    `/app/.venv` already includes editable `pdf-messaging` — proven by `db-migrate`);
  - `working_dir: /app`, `command: ["/app/.venv/bin/python", "-m", "messaging.bootstrap"]`;
  - `environment`: `RABBITMQ_URL: amqp://${RABBITMQ_USER:-pdf}:${RABBITMQ_PASSWORD:-pdf123}@rabbitmq:5672/`;
  - `env_file: .env`; `depends_on: rabbitmq: service_healthy`; `restart: "no"`;
  - no `profiles` key → runs as part of `compose-dev`.
- `account-api.depends_on` += `rabbit-setup: condition: service_completed_successfully`.
- `rabbitmq` gets a persistent volume: `rabbitmq_data:/var/lib/rabbitmq`, declared
  under top-level `volumes:`. (Durable queue + binding survive `compose down/up`;
  `down -v` wipes them, which is correct.) A fresh named volume replaces the old
  anonymous one — previous broker state is intentionally not migrated.
- `ai-worker` remains behind `profiles: ["ai-worker"]` — unchanged.

**Accept:** `make compose-dev` gives a broker where `document.convert` +
bindings and `document.convert_dlx`/`document.convert_dlq` exist *before*
`account-api` is up (verify in the management UI at `:15672`); uploading without
the ai-worker leaves the document at `processing`, and `make compose-ai-worker`
afterwards drains the job to `completed`.

### Phase 6 — tests + coverage [x]

New `packages/messaging/tests/` (unit, no broker):

- `test_topology.py` — `CONSUMER_QUEUES` validity: unique queue names, non-empty
  `routing_keys`, constants match the ai-worker spec.
- `test_bootstrap.py` — fake `Consumer` records `start()`/`close()` per spec;
  DSN resolution from env (`RABBITMQ_URL`, and the host/port/user/password/vhost
  fallback) via `monkeypatch.setenv`.

`Makefile test`: `pytest apps tests packages/messaging/tests` (currently
`packages` is covered by `ruff` in `lint`, but not by `pytest`).

**Accept:** `cd packages/messaging && uv run pytest tests/ -q` green;
`make test` picks the new suite.

### Phase 7 — documentation [x]

- `apps/ai-worker/README.md` (Run / How it works) — add: `document.convert`
  topology is declared by `rabbit-setup` (a `compose-dev` one-shot), the ai-worker
  is **not** the queue-holder; it stays opt-in.
- `apps/ai-worker/UPLOAD_FLOW.md` §9 — containerized dev mode: same note; state
  the migration path: the one-shot is replaced by the long-running
  marker-orchestrator running the same `bootstrap()` + depth monitoring, with no
  change to publishers / queue names / routing keys / message formats.

**Accept:** no doc claims the ai-worker "declares the queue"; both docs list the
`rabbit-setup` service and its role.

---

## 4. Locked design reference

- Topic exchange: `pdf.events` (durable) — `packages/messaging/messaging/publisher.py:6`.
- Consumer declaration (bootstrap mirrors this by reusing `Consumer`):
  - queue `document.convert`, durable, `arguments={"x-dead-letter-exchange": "document.convert_dlx"}`;
  - `document.convert_dlx` fanout + `document.convert_dlq` durable queue + binding;
  - bindings `document.uploaded`, `document.converted` — consumer.py:41-55.
- ai-worker defaults (env-overridable): `ai_worker_queue`, `ai_worker_routing_keys`
  — `apps/ai-worker/app/config.py:23-24`.
- Document status transitions — `apps/account-api/app/services/documents.py`
  (`on_document_stored` → `PROCESSING` + publish `document.uploaded`, :488-504).
- Compose `db-migrate` precedent for a one-shot Python service — docker-compose.yml:44-58.

---

## 5. Tests

| Phase | Suite / area | Command |
|---|---|---|
| 1–3, 6 | `packages/messaging/tests/` (topology spec, bootstrap declare) | `cd packages/messaging && uv run pytest tests/ -q` |
| 4 | publisher unit coverage if added | same suite |
| 6 | full repo | `make test` |
| 3, 5 | integration on compose broker (manual) | `make compose-dev`; management UI `:15672`; `make compose-ai-worker-logs` |
| All | lint + format | `uvx ruff check apps packages tests`; `cd packages/messaging && uv run ruff format --check .` |

## 6. Implementation order

1. Phase 1 — `messaging/topology.py`. [x]
2. Phase 2 — ai-worker config consumes topology defaults. [x]
3. Phase 3 — `messaging/bootstrap.py`. [x]
4. Phase 4 — publisher safety net. [x]
5. Phase 5 — compose `rabbit-setup` + volume. [x]
6. Phase 6 — tests + `make test`. [x]
7. Phase 7 — documentation. [x]

Each phase: implement → update this status → pause for confirmation. No
automatic chaining.

## 7. Notes & conventions

### Gotchas (verified empirically)

- Topic exchanges **silently drop unroutable messages** when `mandatory=False`
  (the default here); without the bootstrap, `document.uploaded` vanishes if
  `document.convert` has never been declared+bound (ai-worker never started).
- `compose-dev` does not start `ai-worker` (docker-compose.yml:119,
  `profiles: ["ai-worker"]`); it is the *only* live consumer of `document.convert`
  today (`marker-orchestrator`/`marker-worker` are 0-byte scaffolding).
- compose `rabbitmq` has **no persistent volume** today — durable queues/bindings
  are lost on container recreation; Phase 5 fixes this.
- aio_pika: `channel.confirm_delivery()` enables publisher confirms;
  `mandatory=True` + `add_on_return_callback` routes returned messages to the
  callback instead of raising `DeliveryError`.
- Reuse `Consumer.start()` in bootstrap rather than writing `declare_*` calls, or
  a later worker's `Consumer.start()` on an already-existing queue with different
  args fails with `PRECONDITION_FAILED` (406).

### Open decisions (defaults chosen)

- **mandatory behavior:** log-only (WARNING), do not fail the upload — chosen:
  safe for partially-started dev stacks. Revisit if silent loss resurfaces.
- **Topology scope:** declare only `document.convert` now — chosen; other
  consumer queues (objectstorage/notification/document_events) are declared by
  their always-running compose services today and belong to the orchestrator later.
- **`rabbit-setup` image:** reuse `apps/account-api/Dockerfile` (proven venv has
  `pdf-messaging`), not a new Dockerfile — chosen.

### Risks (mitigations in place)

- **Bootstrap/worker drift** → bootstrap reuses `Consumer.start()`; topology
  constants feed ai-worker config (single source of truth).
- **Fresh named volume drops prior broker state** → intentional; bootstrap
  re-declares idempotently on every `compose-dev`.
- **Predeclared queue conflicts with future orchestrator** → none: orchestrator
  replaces the one-shot with a long-running service running the same bootstrap
  against the same names.

---
Conventions: `docs/development/CONTRIBUTING.md`; plan format
`docs/development/IMPL_PLAN_SCHEMA.md`.