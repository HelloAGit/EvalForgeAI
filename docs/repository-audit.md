# Repository Audit

## Existing functionality
- FastAPI backend (`backend/app`): `/api/v1/health`, `/api/v1/mubit/status`, statistics router, `/api/v1/dashboard/summary` (returns static demo data).
- Services: LLM, RAG and agent metric helpers, a native statistical engine (SciPy), an MLStatSoft adapter stub, a Mubit client (Anthropic-compatible `/messages` call).
- SQLAlchemy models/database setup (SQLite default).
- Next.js dashboard page (single route `/`) with sidebar and metric cards.
- Pytest tests for statistics and metrics (4 passing at audit time).

## Missing functionality
- Pages linked from the sidebar (`/evaluations`, `/rag`, `/agents`, `/statistics`, `/experiments`, `/settings`) do not exist; no model comparison, history or dataset pages.
- Dashboard shows only a subset of the requested metrics; no charts or filters.
- Dashboard summary is demo-only; no evaluation run persistence or run endpoints.
- Mubit client has a connection test only (no retries, no token/latency capture, no run persistence).
- No exact-match / JSON-schema evaluators, Wilson/bootstrap CIs, McNemar test were verified/added in this change.

## Broken / missing build pieces (fixed in this change)
- Frontend lacked `tsconfig.json`, `next.config.js`, `app/layout.tsx`, Tailwind/PostCSS config, ESLint config and a lockfile; it could not build.
- `docker-compose.yml` referenced Dockerfiles that did not exist.
- No `.dockerignore`, Dockerfile, CI or publish workflow, README.

## Security concerns
- **Live-looking Mubit and MLStatSoft API keys were committed** in `backend/app/config.py`, `.env.example` and `docker-compose.yml` (and remain in git history). They have been removed from the tree, but **must be revoked/rotated** by the owner; history rewriting is out of scope.
- CORS allows all origins with credentials (`allow_origins=["*"]`); restrict before exposing publicly.
- Mubit status endpoint performs an outbound call per request when a key is set.
- Error text from upstream responses is returned to clients in `test_connection`.

## CI/CD gaps (addressed)
- Added `.github/workflows/ci.yml` and `publish-ghcr.yml`.

## Recommended corrections (remaining)
- Rotate leaked keys; consider history scrub.
- Implement remaining pages and metrics; add evaluators and persistence.
- Add retries/backoff and metadata capture to the Mubit client; restrict CORS.
