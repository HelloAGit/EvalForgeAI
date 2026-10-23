# Live analytics dashboard

All figures are computed from persisted evaluation data (`evaluation_results`, `metric_observations`, `evaluation_runs`). Nothing is simulated. When data is missing a KPI shows **N/A with a reason**.

## Metric catalogue

`backend/app/services/metrics_catalog.py` defines the KPI catalogue (24 requested KPIs plus supporting entries): key, name, category (llm/rag/agent/operations), unit, direction (higher/lower is better), definition, calculation, evaluator/method + version, aliases (e.g. `numerical_accuracy` → LLM correctness), and Quality-Index weight. Ratio metrics are stored in 0–1.

Status per metric: `ok`, `na` (no observations / not produced by any evaluator / fewer than `MIN_OBSERVATIONS`, default 3). Statistical confidence intervals use the normal approximation over per-sample scores (shown only when n ≥ `MIN_OBSERVATIONS`).

## Overall AI Quality Index (0–100)

Weighted mean of available quality metrics (`lower_better` metrics are inverted):

* default weights are in the catalogue (sum 1.0) and can be overridden with `QUALITY_INDEX_WEIGHTS_JSON`;
* **missing metrics are excluded and the remaining weights re-normalised**;
* if the available weight is below `QI_MIN_COVERAGE` (default 0.5) the index is **N/A** with the coverage and the list of missing metrics;
* bands (Good ≥ 80, Needs attention 60–80, Critical < 60) are presentation only.

## APIs (all authenticated, base `/api/v1/dashboard`)

| Endpoint | Purpose |
|---|---|
| `GET /overview` | Full state: KPIs, Quality Index, charts, alerts, `last_event_id`, filters echo. Cached by (filters, last event id). |
| `GET /metrics`, `GET /metrics/{key}` | Metric list; drill-down (definition, calculation, unit, n, CI, trend, failed cases, evidence refs, models, datasets, method + version). |
| `GET /trends?metric=` | Time series per model. |
| `GET /alerts` | Regression alerts (latest vs previous run, drop ≥ `REGRESSION_DROP_THRESHOLD`). |
| `GET /compare` | Side-by-side models or runs with deltas. |
| `GET /events` | Change events: JSON (`after`) or SSE (`stream=true`). |
| `GET/PUT /preferences` | Per-user saved layout/filters. |
| `GET /summary` | Legacy 2.0 shape, now real data. |

Filters (query): `project_id`, `provider`, `model_id`, `suite`, `dataset_version`, `run_id`, `date_from`, `date_to`, `category`, `status`.

Ingestion that feeds the dashboard: `POST /api/v1/projects`, `/datasets`, `/evaluations/runs`, `/evaluations/runs/{id}/results`, `/evaluations/runs/{id}/complete`.

## Live updates

1. The client fetches `/overview` (full state) and remembers `last_event_id`.
2. Writes (ingest, run completion) append a row to `evaluation_events` (DB-backed event channel). The id is the SSE `id`.
3. The client opens `GET /events?stream=true&after=<id>` using `fetch` streaming (so the `Authorization` header can be sent – `EventSource` cannot). Each event triggers one debounced re-fetch of `/overview`; the server caches overview results per last-event-id, so idle periods cost one indexed `id > ?` query per `SSE_POLL_SECONDS`.
4. Dedupe: events with `id <= last_event_id` are ignored. A gap larger than `SSE_MAX_CATCHUP_EVENTS`, a cursor ahead of the server, or reconnection triggers a `resync` frame / full refetch.
5. Reconnect with exponential backoff (capped, reset on success). After repeated failures the client **falls back to polling** `/events?after=` and keeps retrying the stream.
6. The stream ends with a `reconnect` frame after `SSE_MAX_DURATION_SECONDS`; heartbeats every `SSE_HEARTBEAT_SECONDS`. A silent connection past the stale threshold is dropped and re-established.
7. UI: last-updated timestamp, **stale-data indicator**, pause/resume (resume = full resync), and all timers/fetches are aborted on unmount.

Implemented in `frontend/lib/liveConnection.ts` (17 vitest tests with fake fetch/timers) and `backend/app/services/events.py`.

## Scheduled evaluations (optional)

`/api/v1/schedules` (admin-only writes): kinds `daily`, `weekly`, `dataset_trigger`, `regression` (triggered with a release tag via `POST /{id}/trigger`). Executed by the worker (`python -m app.worker`) – durable DB state, not browser timers. Protections: compare-and-set slot claim (no duplicate runs from several workers), overlap guard (no new run while one is active), `SCHEDULER_MAX_RUNS_PER_DAY` cap, idempotency keys, no catch-up storm after downtime, new schedules are created **disabled**. Built-in runner scope: LLM numerical accuracy, RAG retrieval metrics, agent task completion.

## Status

Implemented: everything above. Not implemented: user-defined custom KPI formulas in the UI (weights are configurable via env), Postgres `LISTEN/NOTIFY` (events are polled from the DB).
