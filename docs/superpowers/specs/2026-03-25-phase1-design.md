# Phase 1 Design: Core Infrastructure & Alpha Seed Pool

**Date**: 2026-03-25
**Status**: Approved
**Scope**: Backend infrastructure only; no frontend (Phase 6)

---

## 1. Goals

Deliver a working FastAPI backend that can:
1. Load a representative Alpha101 seed pool (~25 alphas)
2. Mutate seeds via `TemplateMutator`
3. Validate generated expressions via `ExpressionValidator`
4. Persist alphas to SQLite and expose them via REST API

**KPI**: `POST /api/generate/mutate` returns a JSON list of mutation candidates that have passed validation and been stored in the DB.

---

## 2. Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Alpha101 seed pool size | ~25 representative formulas | Covers major strategy types; avoids 101-formula upfront cost |
| Implementation approach | Full spec structure from day one | Eliminates Phase 2–6 refactoring; clean insertion points |
| Python version | 3.12 (uv resolved) | Within `>=3.11,<3.13` constraint; gplearn 0.4.3 compatible |
| DB migrations | Alembic | Already in stack; standard SQLAlchemy migration tool |

---

## 3. Directory Structure

```
backend/
├── main.py                      # FastAPI app, mounts routers
├── config.py                    # pydantic-settings Settings class
├── database.py                  # SQLAlchemy engine + get_db session factory
├── models/
│   ├── __init__.py
│   ├── alpha.py                 # Alpha ORM model
│   ├── simulation.py            # Simulation ORM model
│   └── correlation.py           # PoolCorrelation ORM model
├── schemas/
│   ├── __init__.py
│   ├── alpha.py                 # AlphaCreate, AlphaRead Pydantic schemas
│   └── simulation.py            # SimulationRead schema
├── api/
│   ├── __init__.py
│   ├── alphas.py                # GET/POST/DELETE /api/alphas
│   ├── generate.py              # POST /api/generate/mutate (Phase 1 active)
│   ├── submit.py                # Stub (Phase 2)
│   └── pool.py                  # Stub (Phase 3+)
├── core/
│   ├── __init__.py
│   ├── models.py                # AlphaCandidate dataclass, AlphaSource enum
│   ├── seed_pool.py             # ~25 Alpha101 definitions
│   ├── expression_validator.py  # ExpressionValidator
│   ├── mutator.py               # TemplateMutator
│   ├── gp_searcher.py           # Stub (Phase 5)
│   └── llm_generator.py         # Stub (Phase 4)
└── services/
    ├── __init__.py
    ├── diversity_filter.py      # Stub (Phase 3)
    ├── proxy_data.py            # Stub (Phase 3)
    └── wq_interface.py          # Stub (Phase 2)

db/
└── migrations/                  # Alembic env + version scripts

scripts/
└── seed_alpha101.py             # One-time: load seed pool into DB
```

---

## 4. Data Model

### `AlphaCandidate` (dataclass, `backend/core/models.py`)

```python
@dataclass
class AlphaCandidate:
    id: str                    # SHA256(expression + canonical config JSON)
    expression: str
    universe: str              # default "TOP3000"
    region: str                # default "USA"
    delay: int                 # 0 or 1
    decay: int                 # 0–32
    neutralization: str        # "none"|"market"|"sector"|"industry"|"subindustry"
    truncation: float          # 0.01–0.1
    pasteurization: str        # "on"|"off"
    nan_handling: str          # "on"|"off"
    source: AlphaSource        # SEED|MUTATION|GP|LLM|MANUAL
    parent_id: str | None
    rationale: str | None
    created_at: datetime
```

ID is deterministic: `SHA256(expression + sorted config fields)`. Duplicate expressions with identical config produce the same ID and are naturally deduplicated.

### `AlphaSource` (enum)

```python
class AlphaSource(str, Enum):
    SEED = "seed"
    MUTATION = "mutation"
    GP = "gp"
    LLM = "llm"
    MANUAL = "manual"
```

---

## 5. Seed Pool (`backend/core/seed_pool.py`)

~25 Alpha101 formulas selected to cover distinct strategy families:

| Category | Count | Examples |
|----------|-------|---------|
| Price momentum | 6 | Alpha#1, #2, #12 |
| Mean reversion | 5 | Alpha#3, #7 |
| Volume-price divergence | 5 | Alpha#6, #31 |
| Volatility | 4 | Alpha#19, #20 |
| Correlation-based | 5 | Alpha#9, #17 |

Each seed is a hardcoded `AlphaCandidate` with `source=AlphaSource.SEED`.

Default config for all seeds: `universe=TOP3000, region=USA, delay=1, decay=0, neutralization=subindustry, truncation=0.08, pasteurization=off, nan_handling=off`.

---

## 6. Expression Validator (`backend/core/expression_validator.py`)

```python
@dataclass
class ValidationResult:
    valid: bool
    reason: str | None   # None if valid

class ExpressionValidator:
    def validate(self, expression: str) -> ValidationResult: ...
```

Four checks (all must pass):

1. **Balanced parentheses** — stack-based parse; catches mismatched `()`
2. **Operator whitelist** — tokenise by `word(` pattern; reject unknown function names against `ALLOWED_OPERATORS` set
3. **Numeric argument ranges** — regex extracts integer args; reject window < 1 or > 252
4. **Python keyword blacklist** — reject `import`, `eval`, `exec`, `__`, etc.

Invalid expressions are logged at WARNING level and silently discarded — they never raise exceptions to callers.

`ALLOWED_OPERATORS` mirrors the WQ Fast Expression operator list: `ts_mean`, `ts_std`, `ts_delta`, `ts_rank`, `ts_corr`, `ts_covariance`, `ts_max`, `ts_min`, `ts_median`, `rank`, `zscore`, `scale`, `log`, `abs`, `sign`, `IndNeutralize`, `adv`, `cap`, `returns`, `open`, `high`, `low`, `close`, `volume`, `vwap`.

---

## 7. TemplateMutator (`backend/core/mutator.py`)

```python
class TemplateMutator:
    LOOKBACK_VARIANTS = [5, 10, 20, 40, 60]
    OPERATOR_SWAPS = {
        "ts_mean":  ["ts_median", "ts_max", "ts_min", "ts_std"],
        "rank":     ["zscore", "scale"],
        "ts_corr":  ["ts_covariance"],
    }
    CONFIG_VARIANTS = {
        "neutralization": ["market", "sector", "subindustry"],
        "decay": [0, 4, 8],
        "truncation": [0.05, 0.08, 0.10],
    }

    def mutate_lookback(self, alpha: AlphaCandidate) -> list[AlphaCandidate]: ...
    def mutate_operator(self, alpha: AlphaCandidate) -> list[AlphaCandidate]: ...
    def mutate_rank_wrap(self, alpha: AlphaCandidate) -> list[AlphaCandidate]: ...
    def mutate_config(self, alpha: AlphaCandidate) -> list[AlphaCandidate]: ...
    def mutate_all(self, alpha: AlphaCandidate) -> list[AlphaCandidate]: ...
```

- `mutate_lookback`: regex-replaces all numeric window args (e.g. `ts_mean(x, 5)` → variants with 10, 20, 40, 60)
- `mutate_operator`: string-replaces operator names per `OPERATOR_SWAPS`
- `mutate_rank_wrap`: wraps entire expression with `rank(...)` or `zscore(...)`
- `mutate_config`: varies `neutralization`, `decay`, `truncation` while keeping expression identical
- `mutate_all`: calls all four, runs each result through `ExpressionValidator`, deduplicates by `id`

All mutations set `source=AlphaSource.MUTATION` and `parent_id=alpha.id`.

---

## 8. Database

Full schema from spec §8 is created in Phase 1 (all 5 tables), so later phases don't require schema changes. Phase 1 actively uses `alphas` and `runs`; other tables exist but are empty.

Alembic initial migration creates all tables and indexes.

`scripts/seed_alpha101.py` loads the hardcoded seed pool into the `alphas` table (idempotent via `INSERT OR IGNORE`).

---

## 9. API Endpoints (Phase 1 active)

### `GET /api/alphas`
Query params: `source` (filter), `limit` (default 100), `offset` (default 0)
Returns: `list[AlphaRead]`

### `GET /api/alphas/{id}`
Returns: `AlphaRead` or 404

### `POST /api/alphas`
Body: `AlphaCreate`
Returns: `AlphaRead` (201)

### `DELETE /api/alphas/{id}`
Returns: 204

### `POST /api/generate/mutate`
Body: `{ "alpha_id": str | null, "strategies": ["lookback","operator","rank_wrap","config"] }`
- If `alpha_id` is null: mutate all seeds
- If `alpha_id` is provided: mutate that specific alpha
- Runs validator on each candidate; discards invalid
- Persists passing candidates to `alphas` table (skips duplicates)
- Logs a `runs` entry
Returns: `{ "run_id": int, "generated": int, "passed": int, "candidates": list[AlphaRead] }`

### Stubs (return 501 Not Implemented)
`POST /api/generate/llm`, `POST /api/generate/gp`, all `/api/submit/*`, all `/api/pool/*`

---

## 10. Error Handling

- DB session errors: FastAPI exception handler returns 500
- Invalid `alpha_id` in mutate request: 404
- Expression validator failures: logged, not raised; reflected in `generated` vs `passed` counts
- Duplicate alpha IDs on insert: silently skipped (idempotent)

---

## 11. Out of Scope (Phase 1)

- Diversity filtering (Phase 3)
- Any frontend (Phase 6)
- LLM / GP generation (Phase 4/5)
- WQ Brain interface (Phase 2)
- `proxy_prices` table population
