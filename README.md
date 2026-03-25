# 🧠 Alpha Miner

> A modular alpha mining system for WorldQuant BRAIN — combining rule-based mutation, genetic programming, and LLM-driven generation to build a high-diversity alpha pool for the IQC competition.

---

## 📌 What Is This?

Alpha Miner is a full-stack research tool that automates the discovery, filtering, and tracking of **formulaic alpha expressions** compatible with the [WorldQuant BRAIN](https://www.worldquant.com/brain/) platform.

Instead of manually crafting alpha signals one by one, Alpha Miner:
1. 🌱 Starts from a seed pool of 101 proven alphas
2. 🔀 Mutates and evolves new candidates via rule-based templates and genetic programming
3. 🤖 Uses Claude API to generate novel ideas guided by your current pool's gaps
4. 🔍 Filters candidates for **diversity** before submission (low pairwise correlation = better IQC score)
5. 📊 Tracks all WQ Brain backtest results in a local database with a visual dashboard

---

## 🎯 Goals

| Priority | Goal |
|----------|------|
| 🥇 Primary | Maximize IQC competition score via a large, diverse alpha pool |
| 🥈 Secondary | Portfolio artifact demonstrating full-stack + AI integration |
| 🥉 Tertiary | Reproducible research workflow for iterative alpha discovery |

---

## 🗺️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Vue3 + Vite  (Frontend)                    │
│  Dashboard │ Alpha Editor │ Queue Manager │ Pool Analytics  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────┐
│                      FastAPI  (Backend)                      │
│        /alphas  /generate  /submit  /pool  /filter          │
└──────┬─────────────────┬──────────────────┬─────────────────┘
       │                 │                  │
  ┌────▼─────┐    ┌──────▼──────┐   ┌──────▼──────────────┐
  │  Alpha   │    │  Diversity  │   │   WQ Brain          │
  │  Engine  │    │   Filter    │   │   Interface         │
  │          │    │  (Spearman) │   │ Manual / Auto       │
  │ Mutator  │    └──────┬──────┘   └─────────────────────┘
  │ GP Search│           │
  │ LLM Gen  │    ┌──────▼──────┐
  └────┬─────┘    │ Proxy Data  │
       │          │ (yfinance   │
       │          │  S&P 500)   │
       │          └─────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                       SQLite  (Local DB)                     │
│      alphas │ simulations │ pool_correlations │ runs        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Project Structure

```
alpha-miner/
│
├── 📄 README.md
├── 📄 .env.example
├── 📄 .gitignore
├── 📄 requirements.txt
│
├── 📁 docs/
│   └── spec.md                  # Full Software Design Document
│
├── 📁 backend/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Pydantic settings
│   ├── database.py              # SQLAlchemy engine + session
│   │
│   ├── 📁 models/               # ORM models (SQLAlchemy)
│   │   ├── alpha.py
│   │   ├── simulation.py
│   │   └── correlation.py
│   │
│   ├── 📁 schemas/              # Pydantic request/response models
│   │   ├── alpha.py
│   │   └── simulation.py
│   │
│   ├── 📁 api/                  # FastAPI routers
│   │   ├── alphas.py
│   │   ├── generate.py
│   │   ├── submit.py
│   │   └── pool.py
│   │
│   ├── 📁 core/                 # Alpha generation engines
│   │   ├── seed_pool.py         # Alpha101 hardcoded definitions
│   │   ├── mutator.py           # TemplateMutator
│   │   ├── gp_searcher.py       # Genetic programming search
│   │   ├── llm_generator.py     # Claude API integration
│   │   └── expression_validator.py
│   │
│   ├── 📁 services/             # Business logic layer
│   │   ├── diversity_filter.py  # Correlation-based filtering
│   │   ├── proxy_data.py        # yfinance data manager
│   │   └── wq_interface.py      # WQ Brain client abstraction
│   │
│   └── 📁 db/
│       └── migrations/          # Alembic migration scripts
│
├── 📁 frontend/
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   └── 📁 src/
│       ├── main.ts
│       ├── App.vue
│       ├── 📁 pages/
│       │   ├── Dashboard.vue
│       │   ├── Alphas.vue
│       │   ├── Generate.vue
│       │   ├── Queue.vue
│       │   ├── Pool.vue
│       │   └── Settings.vue
│       ├── 📁 components/
│       │   ├── PoolHealthCard.vue
│       │   ├── CorrelationHeatmap.vue
│       │   ├── AlphaTable.vue
│       │   ├── SubmissionQueue.vue
│       │   ├── GenerationPanel.vue
│       │   └── FitnessHistogram.vue
│       └── 📁 stores/           # Pinia state management
│           ├── pool.ts
│           ├── queue.ts
│           └── generation.ts
│
└── 📁 scripts/
    ├── seed_alpha101.py         # One-time seed pool initialization
    └── update_proxy_data.py     # Manual proxy data refresh
```

---

## ⚙️ Tech Stack

| Layer | Technology | Reason |
|-------|------------|--------|
| **Backend** | Python 3.11 + FastAPI | Async-native, auto OpenAPI docs |
| **Database** | SQLite + SQLAlchemy | Zero-infra, sufficient for solo research |
| **Alpha Generation** | gplearn (Genetic Programming) | CPU-only, no GPU needed |
| **LLM Integration** | Claude API (claude-sonnet-4-6) | Best-in-class reasoning for financial expression generation |
| **Proxy Data** | yfinance + pandas | Free, covers S&P 500 for IC estimation |
| **Frontend** | Vue3 + Vite + Pinia | Fast dev, reactive state, component composition |
| **Visualisation** | Chart.js / D3.js | Correlation heatmap, Fitness histogram |
| **Backtesting** | WorldQuant BRAIN (external) | The only backtest that counts for IQC |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11
- Node.js 18+
- A WorldQuant BRAIN account
- A Claude API key

### 1. Clone & install backend

```bash
git clone https://github.com/yourname/alpha-miner.git
cd alpha-miner

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   CLAUDE_API_KEY=...
#   WQ_MODE=manual    # start with manual; switch to auto later
```

### 3. Initialise the database

```bash
cd backend
alembic upgrade head
python ../scripts/seed_alpha101.py
```

### 4. Download proxy data

```bash
python ../scripts/update_proxy_data.py
# Downloads 2 years of OHLCV for S&P 500 constituents (~15 min first run)
```

### 5. Start the backend

```bash
uvicorn main:app --reload --port 8000
# API docs available at http://localhost:8000/docs
```

### 6. Start the frontend

```bash
cd ../frontend
npm install
npm run dev
# Dashboard at http://localhost:5173
```

---

## 🔄 Workflow

### Daily Research Loop

```
1. 🌅 Morning: run update_proxy_data.py to refresh prices
2. 🔀 Generate: pick a mode (Mutation / GP / LLM) from the dashboard
3. 🔍 Review: inspect candidates in the Alpha Table, discard obvious noise
4. 📤 Export: download the pending queue as JSON
5. 🧪 Submit: paste each alpha into WQ Brain and run simulations
6. 📥 Import: paste Sharpe/Fitness results back into the dashboard
7. 📊 Analyse: check pool correlation matrix; identify gaps for next run
```

### Alpha Lifecycle

```
GENERATED → [Validator] → [Diversity Filter] → PENDING → SUBMITTED → COMPLETED
                ↓                   ↓
            DISCARDED           DISCARDED
          (syntax error)    (too correlated)
```

---

## 📊 Key Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **Pool Size** | Number of passed alphas | 50+ for IQC |
| **Avg Fitness** | `sqrt(abs(R)/max(TO,0.125)) × Sharpe` | > 1.0 |
| **Avg Pairwise Correlation** | Diversity health | < 0.4 |
| **Pass Rate** | Candidates surviving both filters | Monitor trend |
| **IC (local proxy)** | Spearman corr on yfinance data | > 0.02 |

---

## ⚠️ Important Limitations

**WQ Brain as oracle**: All meaningful backtesting happens on WQ Brain. The local proxy data (yfinance, S&P 500) is used only for diversity filtering — it is not a substitute for WQ Brain simulation results. Always treat WQ Brain as the ground truth.

**Unofficial API**: The auto-submission mode uses an unofficial WQ Brain API based on session cookies. It can break at any time if WQ changes their frontend. The manual queue mode is always the stable fallback.

**No alpha decay modelling**: This system optimises for IQC submission performance. It does not model or predict how quickly alphas will decay over time in live trading.

**Hardware constraint**: Genetic programming runs on CPU only. Expect ~20–30 minutes per GP run on a modern laptop. Run overnight when possible.

---

## 📅 Development Roadmap

| Month | Phase | Deliverable |
|-------|-------|-------------|
| Month 1 | Phases 1–2 | Seed pool + mutation + manual WQ queue |
| Month 2 | Phases 3–4 | Diversity filter + LLM generator |
| Month 2–3 | Phase 5 | GP searcher |
| Month 3 | Phase 6 | Vue3 dashboard + IQC submission sprint |

See [`docs/spec.md`](docs/spec.md) for the complete Software Design Document with detailed module specifications, sequence diagrams, and database schema.

---

## 📄 License

MIT — see `LICENSE`.

---

> **Built for WorldQuant IQC 2026** · Solo developer project · Python 3.11 + Vue3 + Claude API
