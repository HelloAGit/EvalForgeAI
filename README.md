# EvalForgeAI

Mubit-powered AI testing, LLM evaluation, RAG quality analytics, agent diagnostics, and statistical intelligence platform.

## Deployed App

https://pixel-perfect-picture-369.lovable.app/

## Overview

EvalForgeAI is a full-stack platform for evaluating and improving AI systems. It combines experiment execution, quality analytics, and diagnostic tooling so teams can continuously measure and impro[...]

Core goals:
- Evaluate LLM output quality and consistency
- Measure RAG retrieval and grounding performance
- Diagnose agent/tool-calling behavior and failure modes
- Support statistically meaningful comparison across runs

## Core Capabilities

- **LLM Evaluation**
  - Run evaluation suites against prompts/datasets
  - Track quality metrics across model versions

- **RAG Quality Analytics**
  - Analyze retrieval relevance and answer grounding
  - Compare quality across retrieval or prompting strategies

- **Agent Diagnostics**
  - Inspect multi-step agent execution behavior
  - Identify weak points in tool usage and orchestration

- **Statistical Intelligence**
  - Summarize performance trends
  - Compare experiments with stronger statistical confidence

- **Mubit-Powered Model Access**
  - Integrates with Mubit Anthropic-compatible APIs

## Tech Stack

From repository language composition:
- **Python** (62.7%) — backend/services/evaluation logic
- **TypeScript** (35.1%) — frontend/dashboard UX
- **Makefile** (2.2%) — automation and developer workflows

## Configuration

This project uses environment variables for runtime configuration.

### `.env.example`

```dotenv
APP_ENV=development
DATABASE_URL=sqlite:///./evalforge.db

MUBIT_API_KEY=<your_mubit_api_key>
MUBIT_ANTHROPIC_BASE_URL=https://api.mubit.ai/anthropic
MUBIT_ANTHROPIC_MODEL=claude-haiku-4-5

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

MLSTATSOFT_ENABLED=false
MLSTATSOFT_API_KEY=<your_mlstatsoft_api_key>
```

> Security note: never commit real API keys or secrets to source control. Use local `.env` files, CI secrets, or a secret manager.

## Quick Start

> The exact commands can vary by project layout and package manager. Use these as a baseline.

1. **Clone**

   ```bash
   git clone https://github.com/HelloAGit/EvalForgeAI.git
   cd EvalForgeAI
   ```

2. **Create local environment file**

   ```bash
   cp .env.example .env
   ```

   Then set real API keys in `.env`.

3. **Backend setup (Python)**

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Frontend setup (TypeScript)**

   ```bash
   npm install
   npm run dev
   ```

5. **Run backend API (example)**

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. **Optional Make targets**

   ```bash
   make help
   ```

## Typical Workflow

1. Define evaluation scenarios and datasets
2. Run model/agent evaluations
3. Inspect quality metrics and diagnostic traces
4. Compare runs and identify regressions
5. Iterate on prompts, retrieval settings, tools, or agent policies

## Suggested Project Areas

Depending on your current structure, common areas include:
- `backend/` for API/services/evaluation logic
- `frontend/` for UI and dashboards
- `evaluations/` for test suites, datasets, and scoring configs
- `analytics/` for metrics/statistics modules

## Development Notes

- Keep `.env.example` free of real credentials
- Add/maintain tests around evaluation and scoring logic
- Prefer reproducible experiment configs and versioned datasets
- Use separate credentials for dev/staging/production

## Roadmap Ideas

- Automated quality regression alerts
- Built-in evaluator templates for common use cases
- Dataset/version lineage tracking
- CI/CD-integrated evaluation gates

## Contributing

Contributions are welcome. A recommended process:
1. Create a feature branch
2. Make focused, tested changes
3. Open a pull request with clear context and screenshots/logs (if relevant)

## License

Add your license here (e.g., MIT, Apache-2.0, Proprietary).
