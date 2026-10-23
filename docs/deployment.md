# Deployment

## Images (GHCR)

| Image | Dockerfile target | Contents |
|---|---|---|
| `ghcr.io/helloagit/evalforgeai` | `backend` → `web` | FastAPI API, migrations, PDF generation. No FFmpeg. |
| `ghcr.io/helloagit/evalforgeai-worker` | `backend` → `worker` | Same code + FFmpeg (`imageio-ffmpeg`) + fonts; runs `python -m app.worker` (scheduler, queued evaluation runs, video jobs). |
| `ghcr.io/helloagit/evalforgeai-frontend` | `frontend` | Next.js standalone server. |

`.github/workflows/docker-publish.yml` publishes all three to GHCR on pushes to `main` and `v*.*.*` tags (tags: branch, semver, `latest`, sha). `.github/workflows/ci.yml` runs backend tests, frontend lint/test/build and builds all images (no push) on PRs. Note: the repository had no Docker/publish workflows before 3.0 – these are new.

A separate worker image keeps heavy video rendering out of the API process and the public image lean; the web image still renders PDFs (background task, small).

## Local (Docker Compose)

```bash
cp .env.example .env
# set EVALFORGE_API_KEYS=mytoken:me:admin  (use a long random token)
docker compose up --build
```

* API `http://localhost:${BACKEND_PORT:-8000}`, UI `http://localhost:${FRONTEND_PORT:-3000}`. Open the UI and paste the token when prompted.
* Services: `backend`, `worker`, `frontend`; volume `evalforge-data` mounted at `/data` (SQLite DB + `artifacts/`).
* Health checks, `stop_grace_period` (40 s/60 s), non-root, `no-new-privileges`, dropped capabilities, `mem_limit`/`cpus` (worker: `WORKER_MEM_LIMIT`, `WORKER_CPUS`).
* `NEXT_PUBLIC_API_BASE_URL` is a **build-time** variable of the frontend image (default `http://localhost:8000`).

### What was verified

On the build machine the `web` and `worker` images were built with Docker, started, reached `healthy`, ran as uid 10001, applied the migrations on an empty volume and exited with code 0 on SIGTERM; `docker compose config` validated. The frontend image also built successfully. A full `docker compose up` of all three services together was not run.

## Without Docker

```bash
cd backend && pip install -r requirements-dev.txt
EVALFORGE_API_KEYS=dev:me:admin APP_ENV=development uvicorn app.main:app --reload
python -m app.worker            # second terminal (or set WORKER_INLINE=true in development)
cd frontend && npm install && npm run dev
```

## Cloud guidance

* Run `web` and `worker` as separate services/deployments; scale workers independently (render is CPU-bound; give it ≥ 2 vCPU/2 GB).
* Use **PostgreSQL** (`DATABASE_URL=postgresql+psycopg://…`, add a driver to the image) – SQLite on a shared volume works for a single host only. Postgres was not exercised by the test-suite.
* `ARTIFACT_DIR` must be a persistent volume shared by web and worker (EFS/Azure Files/PVC, ReadWriteMany). An object-store backend can implement the small `ArtifactStorage` interface (`put_bytes`, `put_file`, `path`, `exists`, `delete`) – not provided.
* Terminate TLS in front; restrict `CORS_ORIGINS`; inject secrets from the platform secret store.
* Migrations run on start (`AUTO_MIGRATE=true`); set it to `false` on all but one instance if you run many replicas.

## Environment reference

See `.env.example`, `backend/app/config.py` (all settings are environment variables), and the per-feature docs.
