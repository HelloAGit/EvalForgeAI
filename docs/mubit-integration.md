# Mubit / Claude integration

Claude is reached **through the Mubit gateway** using the official `anthropic` Python SDK with a custom `base_url` (Mubit's Anthropic-compatible route). Code: `backend/app/services/mubit_gateway.py`; narrative logic: `backend/app/services/narrative.py`.

> **Verification status:** the Mubit documentation (https://docs.mubit.ai/guides/connect-anthropic) could not be reached from the build environment, so the route and model identifier are configurable defaults and have **not been exercised against a live gateway**. Automated tests use a mocked SDK/gateway only. Check the Mubit guide and adjust `MUBIT_ANTHROPIC_BASE_URL` / `MUBIT_ANTHROPIC_MODEL` if they differ.

## Configuration (backend environment only)

| Variable | Default | Meaning |
|---|---|---|
| `MUBIT_API_KEY` | empty | Credential. Never sent to the browser, logged, or written to reports. Empty = Claude disabled (rule-based storyboards are used). |
| `MUBIT_ANTHROPIC_BASE_URL` | `https://api.mubit.ai/anthropic` | Gateway base URL |
| `MUBIT_ANTHROPIC_MODEL` | `claude-haiku-4-5` | Model id |
| `MUBIT_MAX_TOKENS` | 4096 | Output-token cap per call (requests above are clamped) |
| `MUBIT_MAX_INPUT_CHARS` | 60000 | Input budget; oversized snapshots are trimmed (never altered) or refused |
| `MUBIT_MAX_RETRIES` / `MUBIT_TIMEOUT_SECONDS` | 2 / 60 | Retries (429/5xx/network only, exponential backoff) |
| `MUBIT_MIN_INTERVAL_SECONDS` / `MUBIT_MAX_CALLS_PER_HOUR` | 1 / 30 | Rate limits (process-wide) |

One Claude call is made per video job.

## Storyboard schema

Pydantic `Storyboard` (`narrative.py`): `title`, `executive_narrative`, `key_findings[{text, evidence_refs}]`, `chart_explanations[{chart_id, text}]`, `failure_analysis`, `statistical_interpretation`, `recommendations[{text, priority, evidence_refs}]`, `scenes[{id, type, title, on_screen_text[], narration, duration_seconds, metric_refs[], evidence_refs[]}]`, `total_duration_seconds`. Scene types: `title, kpis, llm, rag, agent, failures, stats, recommendations, closing`. Field lengths, scene count (≤ 14) and durations (2–60 s) are enforced. JSON is accepted bare or in a code fence; anything else is rejected.

## Grounding validation (deterministic, no model involved)

* Every number in prose (narration, on-screen text, findings…) must match a number in the snapshot – raw, rounded (0–4 d.p.) or ×100 as a percentage – or a derived count (runs, models…). Unmatched numbers → `unsupported_number` flag (error).
* Every `metric_refs` / `evidence_refs` entry must exist in the snapshot `evidence_index` (`unknown_reference`).
* "Significant" wording is flagged unless a statistically significant result exists (`unsupported_significance`); causal wording is flagged as a warning; unknown chart ids are flagged.
* If more than half the numeric claims are unsupported (≥ 4 checked) the whole response is **rejected** and the rule-based storyboard is used.
* Flags are shown in the review UI; approving a storyboard with error/warning flags requires `acknowledge_flags` (explicit user decision). Edited storyboards are re-validated and approval is reset.
* **Claude cannot change canonical numbers**: the renderer draws KPIs and charts from the snapshot, never from storyboard text.

Matching is by value, not by meaning: a prose number may coincidentally equal an unrelated snapshot value and pass. Human review remains part of the workflow.

## Fallback

Not configured, budget exceeded, gateway error, or malformed/rejected output → a deterministic template storyboard built only from snapshot values, labelled `storyboard_source: "template"` with an informational flag.
