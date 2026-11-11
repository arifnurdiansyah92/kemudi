# apps/orchestrator

Kemudi AI service. It turns a contract (SOW/SPK, PDF or DOCX) into a
baseline a PM approves. It then classifies requests against that baseline as
in baseline, Change Request candidates, or needing clarification, and replays
past requests to measure how well the classification holds up. See
`docs/superpowers/specs/2026-11-11-contract-baseline-cr-design.md`.

- **Model calls.** Every call goes through Hermes (`services/awak`, service
  `kemudi-hermes`) and is logged in `ai_calls`. PM decisions are logged in
  `decisions`. Both tables are append-only.
- **API.** The web UI reaches it at `/api/kemudi/*`. The gateway strips that
  prefix before passing requests on. Callers send their Kemudi token; project
  admins can change things, and members can only read.
- **Data.** Data lives in `data/` (SQLite and uploaded contracts). The folder
  is gitignored because contracts are confidential.

## Develop

```sh
cd apps/orchestrator
uv sync
uv run pytest
```

## CLI

```sh
uv run python -m kemudi_ai extract data/pilot/contract.pdf
uv run python -m kemudi_ai baseline <project-slug> data/pilot/contract.pdf --rate-card data/pilot/backtest.json
uv run python -m kemudi_ai approve <project-slug> --by "PM name"
uv run python -m kemudi_ai backtest <project-slug> data/pilot/backtest.json
```

## Configuration

These come from the environment, normally `infra/.env`:

| Variable | Default |
| --- | --- |
| `KEMUDI_HERMES_URL` | `http://localhost:8642/v1` |
| `KEMUDI_HERMES_API_KEY` | (none) |
| `KEMUDI_AI_MODEL` | `deepseek-flash` |
| `KEMUDI_AI_DB_URL` | `sqlite:///data/kemudi-ai.db` |
| `KEMUDI_TAIGA_API_URL` | `http://localhost:9100/api/v1` |
