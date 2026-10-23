# Dashboard & reporting audit (Phase 0)

Audit of `HelloAGit/EvalForgeAI` before the 3.0 work. It records what was found, what changed because of it, and what is still open.

## Architecture found

| Area | Finding (before 3.0) | Consequence for the design |
|---|---|---|
| Backend | FastAPI app in `backend/app` (`main.py`, `routers/`, `services/`, `models/`). Entry point `uvicorn app.main:app`. SQLAlchemy 2 models, tables created with `create_all`. | Extended in place; no new project. |
| Frontend | Minimal Next.js 14 app (one page, sidebar, metric cards). No `tsconfig`, layout, Tailwind/Next config. It fell back to **hard-coded fake numbers** when the API failed. | Frontend infrastructure was added; fake data removed (unsupported/unknown metrics show `N/A` + reason). |
| Evaluation engines | `services/llm_metrics.py`, `rag_metrics.py`, `agent_metrics.py`, `statistics.py` (Welch/CI helpers). They were not wired to persistence or to the dashboard. | Added `services/evaluation_runner.py` and ingestion (`services/ingest.py`) that persist per-sample observations. |
| Mubit | `services/mubit_client.py` + `/api/v1/mubit/status`. API key had a **default value committed in source**. | New `services/mubit_gateway.py` (Anthropic SDK against the Anthropic-compatible Mubit route, backend-only key, budgets/retries). |
| Dashboard API | `/api/v1/dashboard/summary` returned **demo data**. | Kept for compatibility, now computed from persisted results (`legacy_summary`). Versioned APIs added. |
| Database | SQLite by default, no migrations, no events/observations/aggregates, no report or video tables. | Alembic migrations added (`0001` baseline, `0002` 3.0 schema); legacy DBs are stamped, not recreated. |
| Auth | **None.** Every endpoint was public. | Bearer-token auth with `admin`/`user` roles and per-resource ownership (see `docs/security.md`). |
| Docker / CI | **No Dockerfiles, no `.github` workflows, no README**, although the compose file referenced `./backend/Dockerfile`. No GHCR publishing existed in the repository. | Created Dockerfiles, CI, and a GHCR publish workflow; see `docs/deployment.md`. "Preserve existing GHCR publishing" therefore could not be satisfied literally – nothing existed to preserve. |
| Tests | 4 pytest tests, all passing at baseline. | Extended (see PR description for the current count). |
| Queue | None. | Durable DB-backed jobs with leases (`worker.py`); no external broker needed. |

## Security findings (action needed by the owner)

1. **Live-looking API keys were committed** in `backend/app/config.py`, `.env.example` and `docker-compose.yml` (a Mubit key and an MLStatSoft key). They remain in git history. **Rotate both keys.** The 3.0 code removes every embedded secret; `.env.example` and compose now contain empty values only.
2. No authentication on any endpoint (fixed).
3. Permissive CORS (fixed: explicit `CORS_ORIGINS`).

## Limitations that remain

* Mubit's documentation site was not reachable from the build sandbox, so the Anthropic-compatible route (`https://api.mubit.ai/anthropic`) is configurable but **not verified against a live gateway**. All Claude behaviour is covered with mocked providers only.
* Only built-in evaluators produce observations for correctness (exact/numerical), recall/precision/NDCG@k, task completion and tool accuracy. Metrics such as factual precision, hallucination rate, instruction adherence, response consistency, faithfulness, answer relevancy and citation accuracy have **no built-in evaluator**: they appear only when results are ingested with those scores via the API, otherwise they are `N/A`.
* Authentication is a static token list (no SSO, no token rotation UI).
* SQLite is the default; PostgreSQL is recommended for multi-host deployments but is not exercised by the automated tests.
* Remotion was not adopted (see `docs/video-generation.md`).
