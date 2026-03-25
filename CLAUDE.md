# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Alpha Miner** is a quantitative finance research tool for discovering and optimizing alpha expressions for the WorldQuant BRAIN platform (IQC 2026 competition). It is a solo developer project in early development — the architecture and spec are documented, but source code is largely unimplemented.

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.11, FastAPI + Uvicorn |
| Database | SQLite + SQLAlchemy + Alembic |
| Alpha Generation | TemplateMutator (rule-based), gplearn (genetic programming), Claude API (LLM) |
| Market Data | yfinance (S&P 500 proxy, 2-year rolling window) |
| Frontend | Vue3 + Vite + Pinia + TypeScript |

> Use Python 3.11 specifically — not 3.13. gplearn/sklearn ecosystem compatibility requires it.

## Commands

### Backend (managed by uv)
```bash
uv sync                                    # Install / update all dependencies
uv run alembic upgrade head               # Initialize DB schema
uv run python scripts/seed_alpha101.py    # One-time: load Alpha101 seed pool
uv run python scripts/update_proxy_data.py  # Refresh S&P 500 proxy price data
uv run uvicorn backend.main:app --reload --port 8000  # Start API server
# API docs at http://localhost:8000/docs

# Run tests
uv run pytest
```

### Frontend
```bash
cd frontend
npm install       # first time only
npm run dev       # Dashboard at http://localhost:5173
npm run build     # Production build
```

### Environment
Copy `.env.example` to `.env` and fill in:
- `CLAUDE_API_KEY` — Anthropic API key
- `WQ_MODE` — `manual` (export JSON/CSV for copy-paste) or `auto` (unofficial WQ API)
- `DATABASE_URL` — defaults to `sqlite:///./alpha_miner.db`

## Architecture

```
Vue3 Frontend  ──REST──►  FastAPI Backend  ──►  SQLite DB
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
         Alpha Engine    Diversity Filter   WQ Interface
         ┌──────────┐    (Spearman corr,   (ManualQueue or
         │ Mutator  │     threshold 0.7)    AutoAPIClient)
         │ GP Search│
         │ LLM Gen  │
         └──────────┘
              │
         Proxy Data (yfinance S&P 500)
```

### Key Components

**Alpha Engine** (`backend/core/`)
- `mutator.py` — `TemplateMutator`: rule-based mutations on Alpha101 seeds. Varies lookback windows (5/10/20/40/60), swaps operators (`ts_mean` ↔ `ts_median/max/min`, `rank` ↔ `zscore`), wraps with rank/zscore.
- `gp_searcher.py` — Genetic programming symbolic regression via gplearn. CPU-only, ~20–30 min per run.
- `llm_generator.py` — Claude API integration for novel alpha generation (capped at `LLM_MAX_CALLS_PER_DAY`).
- `expression_validator.py` — Validates syntax against WQ Fast Expression operator whitelist.
- `seed_pool.py` — Hardcoded Alpha101 definitions (101 canonical proven alphas).

**Diversity Filter** (`backend/services/`)
- Computes Spearman rank correlation between candidate and existing pool members using local proxy data.
- Rejects candidates with correlation > `DIVERSITY_THRESHOLD` (default 0.7).

**WQ Brain Interface** (`backend/services/wq_interface.py`)
- Abstract base with two implementations: `ManualQueueClient` (export for human copy-paste into WQ Brain UI) and `AutoAPIClient` (unofficial API, fragile).
- WQ Brain is the single source of truth for backtesting — no local backtester exists.

**Database** (`backend/models/`, `backend/database.py`)
- Tables: `alphas`, `simulations`, `pool_correlations`, `proxy_prices`, `runs`
- Alembic manages migrations.

**Frontend** (`frontend/src/`)
- Pages: Dashboard, Alphas, Generate, Queue, Pool, Settings
- Key components: `PoolHealthCard`, `CorrelationHeatmap`, `AlphaTable`, `SubmissionQueue`, `GenerationPanel`, `FitnessHistogram`
- Pinia stores for pool, queue, and generation state; 30s polling for queue updates.

## Alpha Lifecycle

```
GENERATED → VALIDATED → DIVERSITY_PASSED → PENDING → SUBMITTED → COMPLETED
```

## Key Design Decisions

- **No local backtester** — WQ Brain is the oracle; local proxy data is only used for diversity filtering (IC estimation).
- **Manual-first submission** — `WQ_MODE=manual` is the default; auto mode uses an unofficial API and may break.
- **CPU-only GP** — No GPU required; GP runs are long (~30 min) and should be treated as background tasks.
- **Phase-gated development** — See `docs/spec.md` for the 6-phase plan and DB schema/API reference.
