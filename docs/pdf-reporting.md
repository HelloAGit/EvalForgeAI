# PDF reporting

Library: **ReportLab** (pure Python, BSD, already compatible with the slim Python image; it needs Pillow, which was already a dependency). WeasyPrint was rejected because it requires system Pango/Cairo libraries in the web image.

## Flow

1. `POST /api/v1/reports` validates the request, builds an **immutable report snapshot** (`report_snapshots`, update/delete blocked at ORM level) and stores a `report_definitions` row.
2. PDF generation runs as a background task: `render_pdf(snapshot.payload, template, …)` → file stored through `ArtifactStorage` (`ARTIFACT_DIR`, mount a persistent volume) → `generated_artifacts` row (size, SHA-256, snapshot hash).
3. The client polls `GET /reports/{id}` (`PENDING → GENERATING → COMPLETED | FAILED`).
4. `POST /reports/{id}/regenerate` re-renders from the **original** snapshot; figures never change.

PDF and video both read the same snapshot, so numbers always agree.

## Snapshot payload (schema_version `1.0`)

`snapshot_id`, project, scope (run ids, models, date range, requested metrics/charts), runs (with model, provider, suite, dataset version, status, timestamps), models, dataset versions, evaluation time range, catalogue version + metric definitions (method/version), metrics (value, unit, n, CI, status/N-A reason, per-model values), operational KPIs, quality index (components, missing, method), statistical results (Welch tests, baseline = first model; mean difference, CI, p-value, effect size, n; also persisted in `statistical_results`), chart datasets, failures (classification; individual cases only when `include_cases`), limitations, recommendations (rule-based, with evidence refs), evidence index, created-at. A canonical SHA-256 is stored with it. Building a snapshot for a scope with no data fails with HTTP 422 rather than producing an empty report.

## Templates (`template`)

* `executive` – summary, quality status, KPIs, model comparison, significant failures, operational risks, priorities/actions.
* `technical` – metadata, models, datasets, methodology, LLM/RAG/agent metrics, distributions, statistics, failure diagnostics, latency & cost, limitations, evidence references.
* `statistical` – research question, hypotheses, sampling, sample sizes, descriptive statistics, CIs, tests, effect sizes, comparisons, findings, limitations, deployment implications.

All: A4, cover page with report/snapshot ids and hashes, table of contents, headers/footers with page numbers, wrapped tables whose header row repeats across pages, vector charts (bars, lines, confidence intervals – print resolution by construction), `N/A` + reason for unsupported metrics, methodology appendix. Text is sanitised to the base-14 font Latin-1 range.

## API

`GET/POST /api/v1/reports`, `GET /reports/{id}`, `GET /reports/{id}/download` (`application/pdf`, `attachment`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`), `GET /reports/{id}/snapshot`, `POST /reports/{id}/regenerate`, `POST /reports/preview`. Only the owner (or an admin) can access; others get 404.

Request body: `title`, `template`, `project_id`, `run_ids`, `model_ids`, `date_from`, `date_to`, `metrics`, `charts` (`quality_trend`, `model_ranking`, `llm_performance`, `rag_quality`, `agent_outcomes`, `failure_classification`, `latency_percentiles`, `distributions`, `confidence_intervals`, `regression`, `usage`), `include_cases`.

## Frontend

`/reports` (Report Builder with preview, generate, status, PDF preview/download) and `/reports/library` (history, download, regenerate, "Generate video").

## Limitations

* Statistical tests are Welch t-tests on per-sample scores with the first model as baseline; no multiple-comparison correction. Interpret with the stated sample sizes.
* Chart images are vector drawings, not raster images, so "embedded images" are not present in the PDF.
* The PDF preview in the browser relies on the browser's built-in PDF viewer. The rendered PDF pages were verified by text/structure tests, not by visual inspection.
