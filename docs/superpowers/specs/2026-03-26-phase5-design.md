# Phase 5 Design: GP Searcher

**Date**: 2026-03-26
**Status**: Approved
**Scope**: `backend/core/gp_searcher.py`, `backend/api/generate.py`, `backend/schemas/alpha.py`, tests

---

## 1. Goals

- Use gplearn symbolic regression to search the WQ expression space
- Fitness function: IC (Information Coefficient) = Spearman correlation of program output vs next-day returns on proxy data
- CPU-only; long run (~20–30 min production; fast in tests via mocking)
- `POST /generate/gp` returns immediately; GP executes as a background task
- Results validated + diversity-filtered before saving

**Phase 5 KPI**: GP run completes and produces at least 5 candidates with IC > 0.01 that pass expression validation.

---

## 2. GPSearcher — `backend/core/gp_searcher.py`

### 2.1 Pre-computed Features

The dataset is built by evaluating these WQ expressions on the proxy panel using `AlphaEvaluator`. Each evaluated Series (indexed by `(date, ticker)`) becomes one column of the feature matrix X.

```python
FEATURE_EXPRESSIONS: list[tuple[str, str]] = [
    ("X0",  "close"),
    ("X1",  "open"),
    ("X2",  "high"),
    ("X3",  "low"),
    ("X4",  "volume"),
    ("X5",  "returns"),
    ("X6",  "ts_mean(close, 5)"),
    ("X7",  "ts_mean(close, 10)"),
    ("X8",  "ts_mean(close, 20)"),
    ("X9",  "ts_std(close, 5)"),
    ("X10", "ts_std(close, 20)"),
    ("X11", "ts_delta(close, 1)"),
    ("X12", "ts_delta(close, 5)"),
    ("X13", "ts_mean(volume, 5)"),
    ("X14", "ts_mean(volume, 20)"),
]
```

### 2.2 Dataset Construction

```python
def _build_dataset(
    self, panel: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """
    Returns (X, y, feature_wq_names).
    X: (n_samples, n_features) float32 array
    y: (n_samples,) float32 array — next-day return
    feature_wq_names: WQ expression for each column (for expression translation)
    Rows with NaN in X or y are dropped. ValueError if < 100 valid rows.
    """
```

**Steps**:
1. Evaluate each feature expression via `AlphaEvaluator.evaluate(expr, panel)`. If any evaluation fails with `UnsupportedOperatorError`, skip that feature.
2. Compute target y: `panel["close"].groupby(level="ticker").pct_change().groupby(level="ticker").shift(-1)` (next-day return).
3. Subsample dates for speed: take the last `min(N_MAX_DATES, len(dates))` dates, then every `DATE_STEP`-th. Constants: `N_MAX_DATES = 252`, `DATE_STEP = 5`.
4. Stack features as a DataFrame, align with y on same (date, ticker) index.
5. Drop rows where any column or y is NaN or infinite.
6. Return `(X.values.astype("float32"), y.values.astype("float32"), feature_wq_names)`.

Constants:
```python
N_MAX_DATES = 252  # use at most 252 dates
DATE_STEP = 5      # take every 5th date for speed
MIN_VALID_ROWS = 100
```

### 2.3 Custom IC Fitness

```python
from gplearn.fitness import make_fitness
from scipy.stats import spearmanr

def _ic_metric(y: np.ndarray, y_pred: np.ndarray, w: np.ndarray) -> float:
    if np.std(y_pred) < 1e-8:
        return 0.0
    corr, _ = spearmanr(y_pred, y)
    return float(abs(corr))

IC_FITNESS = make_fitness(function=_ic_metric, greater_is_better=True)
```

### 2.4 GPSearcher Class

```python
class GPSearcher:
    def run(
        self,
        panel: pd.DataFrame,
        n_results: int = 10,
        population_size: int = 500,
        generations: int = 20,
    ) -> list[AlphaCandidate]:
        """
        Run symbolic regression on proxy panel.
        Returns up to n_results AlphaCandidates (raw — not yet validated or diversity-filtered).
        """
```

**`run()` implementation**:
1. `X, y, feature_names = self._build_dataset(panel)` — raises `ValueError` if insufficient data
2. Fit `SymbolicRegressor`:
```python
from gplearn.genetic import SymbolicRegressor
est = SymbolicRegressor(
    population_size=population_size,
    generations=generations,
    tournament_size=20,
    p_crossover=0.7,
    p_subtree_mutation=0.1,
    p_hoist_mutation=0.05,
    p_point_mutation=0.1,
    max_samples=0.9,
    parsimony_coefficient=0.001,
    metric=IC_FITNESS,
    function_set=("add", "sub", "mul", "div", "log", "abs", "neg"),
    n_jobs=1,  # single-threaded; outer parallelism at process level
    random_state=42,
    verbose=0,
)
est.fit(X, y)
```
3. Extract top-N programs from `est._programs[-1]` (final generation):
   - Filter: `p is not None and hasattr(p, "fitness_") and p.fitness_ is not None`
   - Sort by `p.fitness_` descending
   - Deduplicate by `str(p)`
   - Take top `n_results`
4. For each program: convert to WQ expression via `self._to_wq_expression(str(p), feature_names)`
5. Build `AlphaCandidate.create(expression=wq_expr, source=AlphaSource.GP, rationale=f"GP IC={p.fitness_:.4f} gen={generations}")`
6. Return list (skip candidates where `_to_wq_expression` returns None)

### 2.5 Expression Converter

```python
def _to_wq_expression(self, program_str: str, feature_names: list[str]) -> str | None:
    """
    Convert a gplearn program string like:
      add(sub(X3, 0.456), mul(X2, neg(X1)))
    to a WQ Fast Expression string like:
      ((low - 0.456) + (high * (-open)))
    Returns None on parse failure.
    """
```

**Grammar** of gplearn output:
```
node  := func_call | 'X' INT | FLOAT | NEG_FLOAT
func_call := NAME '(' node (',' node)* ')'
```

**Conversion rules**:
- `Xi` → `feature_names[i]` (the WQ expression for feature i)
- number literal → pass through as string
- `add(a, b)` → `(a + b)`
- `sub(a, b)` → `(a - b)`
- `mul(a, b)` → `(a * b)`
- `div(a, b)` → `(a / b)`
- `neg(a)` → `(-a)` — wraps in parens only if `a` contains operators
- `log(a)` → `log(a)`
- `abs(a)` → `abs(a)`

Implementation: a recursive descent parser on the program string:
1. `_parse_node(s, pos)` → `(wq_string, new_pos)`
2. Handles: identifier (X\d+, or float number), function call `name(...)`, negative number
3. `_split_args_from(s, pos_after_lparen)` → list of arg strings

Return `None` if any parse error occurs (try/except the whole thing).

---

## 3. API — `POST /generate/gp`

### 3.1 New Schemas in `backend/schemas/alpha.py`

```python
class GPRequest(BaseModel):
    n_results: int = 10
    population_size: int | None = None   # None → use settings.GP_POPULATION_SIZE
    generations: int | None = None       # None → use settings.GP_GENERATIONS

class GPResponse(BaseModel):
    run_id: int
    status: str   # "running"
    message: str
```

### 3.2 Endpoint

```
POST /api/generate/gp
Body: GPRequest
Returns: GPResponse — 202 Accepted (task started)
Errors: 503 if proxy panel is empty
```

**Sync part** (before returning):
1. Load panel: `panel = _proxy_mgr.get_panel(db)` → 503 if empty
2. Get settings for defaults
3. Create `Run(mode="gp", gp_generations=generations, candidates_gen=0, candidates_pass=0, started_at=now)` and commit
4. `background_tasks.add_task(_run_gp_background, run_id, panel, n_results, pop_size, gens, _gp_db_factory)`
5. Return `GPResponse(run_id=run.id, status="running", message="...")`

### 3.3 `_gp_db_factory` module-level variable

```python
# In generate.py — overrideable in tests
from backend.database import get_engine
from sqlalchemy.orm import sessionmaker

def _default_db_factory():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

_gp_db_factory = _default_db_factory
```

### 3.4 `_run_gp_background` function

```python
def _run_gp_background(run_id, panel, n_results, pop_size, gens, db_factory):
    db = db_factory()
    try:
        searcher = GPSearcher()
        try:
            raw = searcher.run(panel, n_results, pop_size, gens)
        except Exception:
            raw = []

        valid = [c for c in raw if _validator.validate(c.expression).valid]
        accepted, _, _ = _apply_diversity(valid, db, get_settings())

        saved = []
        for c in accepted:
            if db.get(Alpha, c.id) is None:
                orm = _candidate_to_orm(c)
                db.add(orm)
                saved.append(orm)

        run = db.get(Run, run_id)
        if run:
            run.candidates_gen = len(raw)
            run.candidates_pass = len(saved)
            run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        try:
            run = db.get(Run, run_id)
            if run and run.finished_at is None:
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
```

---

## 4. Tests

### `tests/core/test_gp_searcher.py`

Mock `gplearn.genetic.SymbolicRegressor` throughout.

- `_build_dataset()` returns correct shapes given a synthetic panel
- `_build_dataset()` raises `ValueError` when panel has insufficient data
- `_to_wq_expression()` converts `add(X0, X1)` → `(close + open)`
- `_to_wq_expression()` converts `neg(X5)` → `(-returns)`
- `_to_wq_expression()` converts `log(X6)` → `log(ts_mean(close, 5))`
- `_to_wq_expression()` handles numeric literals: `mul(X0, 0.123)` → `(close * 0.123)`
- `_to_wq_expression()` handles deeply nested: `add(mul(X0, X1), neg(X2))` → `((close * open) + (-high))`
- `_to_wq_expression()` returns None for malformed strings
- `run()` with mocked `SymbolicRegressor` returns `AlphaCandidate` list
- `run()` deduplicates programs with identical string representations

### `tests/api/test_generate_gp.py`

In each test:
- Insert proxy price rows in test DB (so panel is non-empty)
- Patch `backend.api.generate.GPSearcher` to mock `run()` returning fake candidates
- Patch `backend.api.generate._gp_db_factory` to return sessions from the test engine

Tests:
- `POST /generate/gp` returns 503 when panel empty (no proxy data in test DB)
- `POST /generate/gp` returns 202 with run_id
- After background task runs (TestClient runs BackgroundTasks sync): Run row has `finished_at` set
- Saved GP candidates appear in `GET /api/alphas` with `source="gp"`
- `GET /generate/runs` shows `mode="gp"` run
- `POST /generate/gp` with `n_results=5` passes correct arg to GPSearcher.run

---

## 5. Files Changed / Created

| File | Action |
|------|--------|
| `backend/core/gp_searcher.py` | Implement |
| `backend/api/generate.py` | Add `POST /generate/gp`, `_run_gp_background`, `_gp_db_factory`, schemas |
| `backend/schemas/alpha.py` | Add `GPRequest`, `GPResponse` |
| `tests/core/test_gp_searcher.py` | Create |
| `tests/api/test_generate_gp.py` | Create |

**Do not touch**: `backend/services/diversity_filter.py`, `backend/services/proxy_data.py`, Phase 1–4 tests.

---

## 6. Known Limitations

| Limitation | Mitigation |
|------------|------------|
| Proxy data ≠ WQ data | IC is a filter only; not a selection criterion |
| Global rank (not per-date) in gplearn | Pre-normalize features; approximation acceptable |
| Data subsampled for speed | Production runs use full data overnight |
| `est._programs` is internal gplearn API | Tested with gplearn 0.4.2; may need version pin |
