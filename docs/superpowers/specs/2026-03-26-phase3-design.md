# Phase 3 Design: Diversity Filter & Local Proxy Data

**Date**: 2026-03-26
**Status**: Draft
**Scope**: `backend/services/proxy_data.py`, `backend/services/diversity_filter.py`, `backend/api/pool.py`, `backend/schemas/pool.py`, tests

---

## 1. Goals

Implement the diversity filtering layer so alphas generated in Phase 1/2 can be:
- Evaluated locally on S&P 500 proxy data (yfinance, 2y OHLCV)
- Compared against the existing alpha pool via Spearman rank correlation
- Rejected if max correlation > `DIVERSITY_THRESHOLD` (default 0.7)
- Pool health tracked via `/api/pool/*` endpoints

**Phase 3 KPI**: Candidates structurally similar to existing pool members are automatically rejected before entering the submission queue, with correlation scores logged.

---

## 2. ProxyDataManager — `backend/services/proxy_data.py`

### 2.1 Interface

```python
class ProxyDataManager:
    SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    DEFAULT_PERIOD = "2y"

    def update(self, db: Session, max_tickers: int | None = None) -> int:
        """Fetch S&P 500 constituent list, download OHLCV via yfinance, upsert into DB.
        max_tickers defaults to settings.PROXY_DATA_TICKERS.
        Returns total rows upserted."""

    def get_panel(self, db: Session) -> pd.DataFrame:
        """Read all proxy_prices rows from DB.
        Returns DataFrame with MultiIndex (date, ticker), columns (open, high, low, close, volume).
        Returns empty DataFrame (same column structure) when no data exists."""
```

### 2.2 `update()` flow

1. `pd.read_html(SP500_URL)[0]` — parse Wikipedia S&P 500 table, extract `Symbol` column
2. Clean tickers: replace `.` with `-` (yfinance convention), sort alphabetically, slice to `max_tickers`
3. `yf.download(tickers, period="2y", auto_adjust=True, progress=False)` — multi-ticker download
4. Flatten the resulting MultiIndex columns `(field, ticker)` → iterate rows
5. For each `(ticker, date)` pair: upsert `ProxyPrice` row (INSERT OR REPLACE in SQLite)
6. Commit once after all inserts; return row count

**Error handling**: if yfinance raises, log and re-raise. Individual ticker failures are non-fatal — skip that ticker.

### 2.3 `get_panel()` flow

1. Query all `ProxyPrice` rows from DB
2. If empty: return `pd.DataFrame(columns=["open","high","low","close","volume"])` with named MultiIndex `["date","ticker"]`
3. Build DataFrame with columns from ORM attributes; set index to `(date, ticker)`
4. Name index levels: `index.names = ["date", "ticker"]`
5. Sort by date then ticker

---

## 3. AlphaEvaluator & DiversityFilter — `backend/services/diversity_filter.py`

### 3.1 Custom Exception

```python
class UnsupportedOperatorError(Exception):
    """Raised when an expression uses a field or function not locally evaluable."""
```

### 3.2 AlphaEvaluator

Evaluates WQ Fast Expressions on a local proxy panel using a recursive descent parser.

**Supported base fields** (resolved from `panel` columns):

| Field | Source |
|-------|--------|
| `open` | `panel["open"]` |
| `high` | `panel["high"]` |
| `low` | `panel["low"]` |
| `close` | `panel["close"]` |
| `volume` | `panel["volume"]` |
| `returns` | `panel["close"].groupby(level="ticker").pct_change()` |

Any other identifier → raise `UnsupportedOperatorError(f"Unknown field: {name}")`.

**Supported functions**:

| Function | Signature | Implementation |
|----------|-----------|----------------|
| `rank` | `rank(x)` | `x.groupby(level="date").rank(pct=True)` |
| `zscore` | `zscore(x)` | `(x - mean) / std` grouped by date (add 1e-8 to avoid div/0) |
| `scale` | `scale(x)` | `x / sum(abs(x))` grouped by date (add 1e-8) |
| `log` | `log(x)` | `np.log(np.abs(x) + 1e-8)` |
| `abs` | `abs(x)` | `x.abs()` |
| `sign` | `sign(x)` | `np.sign(x)` |
| `ts_mean` | `ts_mean(x, n)` | Rolling mean by ticker, window n, `min_periods=1` |
| `ts_std` | `ts_std(x, n)` | Rolling std by ticker, window n, `min_periods=2` |
| `ts_delta` | `ts_delta(x, n)` | `x - ts_delay(x, n)` |
| `ts_delay` | `ts_delay(x, n)` | `x.shift(n)` by ticker |
| `ts_rank` | `ts_rank(x, n)` | Rolling percentile rank by ticker, window n, `min_periods=1` |
| `ts_max` | `ts_max(x, n)` | Rolling max by ticker, window n, `min_periods=1` |
| `ts_min` | `ts_min(x, n)` | Rolling min by ticker, window n, `min_periods=1` |
| `ts_sum` | `ts_sum(x, n)` | Rolling sum by ticker, window n, `min_periods=1` |

Any unknown function name → raise `UnsupportedOperatorError(f"Unknown function: {name}")`.

**Expression grammar** (recursive descent):

```
expr     := term (('+' | '-') term)*
term     := factor (('*' | '/') factor)*
factor   := '-' factor | primary
primary  := NUMBER | IDENT | call | '(' expr ')'
call     := IDENT '(' arglist ')'
arglist  := expr (',' expr)*
NUMBER   := [0-9]+(\.[0-9]*)?
IDENT    := [a-zA-Z_][a-zA-Z0-9_]*
```

Numeric literals (NUMBER) resolve to Python `float`. Arithmetic on `(Series, float)` pairs uses pandas broadcasting. All intermediate results are `pd.Series` with the same `(date, ticker)` MultiIndex.

**Interface**:

```python
class AlphaEvaluator:
    def evaluate(self, expression: str, panel: pd.DataFrame) -> pd.Series:
        """
        Evaluate a WQ Fast Expression on the proxy panel.
        Returns a Series indexed by (date, ticker).
        Raises UnsupportedOperatorError if the expression uses unsupported fields/functions.
        Raises ValueError on parse errors.
        """
```

Implementation: a private `_Parser` class (or functions) with `_tokenize()`, `_parse_expr()`, `_parse_term()`, `_parse_factor()`, `_parse_primary()`. The evaluator instantiates `_Parser(tokens, panel)` and calls `parse_expr()`.

### 3.3 DiversityFilter

```python
class DiversityFilter:
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def should_submit(
        self,
        candidate: AlphaCandidate,
        pool: list[AlphaCandidate],
        evaluator: AlphaEvaluator,
        panel: pd.DataFrame,
    ) -> tuple[bool, float]:
        """
        Returns (should_submit, max_correlation).
        - If candidate cannot be evaluated: returns (True, nan) — caller sets filter_skipped=True
        - If pool is empty or all pool members fail evaluation: returns (True, 0.0)
        - Otherwise: returns (max_corr <= threshold, max_corr)
        """
```

**Logic**:

1. Try `evaluator.evaluate(candidate.expression, panel)` → `cand_vals`
2. On `UnsupportedOperatorError`: return `(True, float("nan"))`
3. Drop NaN from `cand_vals`; if fewer than 10 valid values: return `(True, float("nan"))`
4. For each pool member:
   a. Try `evaluator.evaluate(pool_member.expression, panel)` → `pool_vals`; on error: skip
   b. Align `cand_vals` and `pool_vals` on common index; drop NaN pairs
   c. If fewer than 10 common valid values: skip
   d. `corr, _ = spearmanr(cand_vals_aligned.values, pool_vals_aligned.values)`
   e. Append `abs(corr)` to correlations list
5. If `correlations` is empty: return `(True, 0.0)`
6. `max_corr = max(correlations)`
7. Return `(max_corr <= self.threshold, max_corr)`

---

## 4. Pool API — `backend/api/pool.py`

### 4.1 Schemas — `backend/schemas/pool.py`

```python
class PoolStatus(BaseModel):
    pool_size: int          # distinct alphas with ≥1 completed simulation
    avg_sharpe: float | None
    avg_fitness: float | None
    max_correlation: float | None  # from pool_correlations table; None if no pairs
    min_correlation: float | None

class CorrelationEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    alpha_a: str
    alpha_b: str
    correlation: float
    computed_at: datetime

class TopAlphaEntry(BaseModel):
    id: str
    expression: str
    source: str
    sharpe: float | None
    fitness: float | None
    returns: float | None
    turnover: float | None
    passed: bool | None

class RecomputeResult(BaseModel):
    pairs_computed: int
    skipped: int
```

### 4.2 `GET /api/pool/status`

- Query all `Simulation` rows with `status="completed"`
- `pool_size` = count of distinct `alpha_id`
- `avg_sharpe` = `mean(sharpe)` over all completed rows (None if empty)
- `avg_fitness` = `mean(fitness)` over all completed rows (None if empty)
- Query `pool_correlations` → `max_correlation`, `min_correlation` (None if no rows)
- Returns `PoolStatus`

### 4.3 `GET /api/pool/correlations`

- Query all `PoolCorrelation` rows, ordered by `correlation DESC`
- Returns `list[CorrelationEntry]`

### 4.4 `GET /api/pool/top`

- Query param: `n: int = 10`
- Get all completed simulations ordered by `fitness DESC NULLSLAST`
- Deduplicate by `alpha_id` (keep first = highest fitness per alpha), stop at `n` unique alphas
- For each: lookup `Alpha` row; build `TopAlphaEntry` merging alpha + simulation fields
- Returns `list[TopAlphaEntry]`

### 4.5 `POST /api/pool/recompute`

- Get all alphas with at least one `completed` simulation
- `panel = ProxyDataManager().get_panel(db)`
- If panel is empty: return `RecomputeResult(pairs_computed=0, skipped=len(alphas))`
- Evaluate each alpha: `evaluator.evaluate(alpha.expression, panel)` → Series
  - On `UnsupportedOperatorError`: skip; increment `skipped`
  - Drop NaN from Series; store `{alpha_id: values}`
- Compute all valid pairs `(alpha_a_id, alpha_b_id)` where `alpha_a_id < alpha_b_id`:
  - Align on common index, compute `spearmanr`
  - Upsert `PoolCorrelation(alpha_a=..., alpha_b=..., correlation=..., computed_at=now)`
- `db.commit()`
- Returns `RecomputeResult(pairs_computed=int, skipped=int)`

---

## 5. Integration with Generate Endpoint

The `POST /api/generate/mutate` endpoint (Phase 1) already saves alphas with `filter_skipped=False` by default. Phase 3 adds a diversity check **inside the mutate flow**:

After mutation + validation, for each candidate:
1. Construct `AlphaEvaluator`, call `DiversityFilter(threshold).should_submit(candidate, pool, evaluator, panel)`
2. If `(False, corr)`: discard candidate; log correlation
3. If `(True, nan)`: keep candidate; set `alpha.filter_skipped = True`
4. If `(True, corr)`: keep candidate; `alpha.filter_skipped = False`

**Note**: This integration is **not** implemented in Phase 3 — it is deferred to when Phase 4 generation is wired up. Phase 3 only delivers the services and pool API. The integration will happen in Phase 4.

---

## 6. Tests

### `tests/services/test_proxy_data.py`

- `update()` with mocked `pd.read_html` and `yf.download` stores rows in DB
- `update()` returns correct row count
- `update()` is idempotent (calling twice doesn't duplicate rows)
- `get_panel()` returns DataFrame with correct MultiIndex and columns
- `get_panel()` returns empty DataFrame (correct schema) when DB has no rows

### `tests/services/test_diversity_filter.py`

**AlphaEvaluator**:
- `evaluate("close", panel)` returns `panel["close"]`
- `evaluate("rank(close)", panel)` returns cross-sectional rank values in [0, 1]
- `evaluate("ts_mean(close, 5)", panel)` returns correct rolling mean
- `evaluate("ts_delta(close, 5)", panel)` equals `close - ts_delay(close, 5)`
- `evaluate("close - open", panel)` returns correct arithmetic
- `evaluate("-rank(close)", panel)` handles unary minus
- `evaluate("rank(close) * 2.0", panel)` handles scalar multiplication
- `evaluate("rank(ts_mean(close, 5))", panel)` handles nested calls
- `evaluate("adv5", panel)` raises `UnsupportedOperatorError`
- `evaluate("unknown_func(close)", panel)` raises `UnsupportedOperatorError`

**DiversityFilter**:
- `should_submit` with unevaluable candidate returns `(True, nan)`
- `should_submit` with empty pool returns `(True, 0.0)`
- `should_submit` returns `(False, corr)` when candidate and pool member are identical expression (corr ≈ 1.0 > 0.7)
- `should_submit` returns `(True, corr)` when correlation < threshold
- Pool member that fails evaluation is skipped (not counted)

### `tests/api/test_pool.py`

- `GET /pool/status` returns `pool_size=0` with all None when no completed simulations
- `GET /pool/status` returns correct stats after adding completed simulations
- `GET /pool/correlations` returns empty list when no correlations
- `GET /pool/correlations` returns stored correlations
- `GET /pool/top` returns empty list when no completed simulations
- `GET /pool/top` returns top N by fitness, correct order
- `GET /pool/top?n=2` returns at most 2 entries
- `POST /pool/recompute` returns `{pairs_computed: 0, skipped: N}` when panel empty
- `POST /pool/recompute` stores correlation rows and returns correct pair count (mocked evaluator)

---

## 7. Files Changed / Created

| File | Action |
|------|--------|
| `backend/services/proxy_data.py` | Implement |
| `backend/services/diversity_filter.py` | Implement (`UnsupportedOperatorError`, `AlphaEvaluator`, `DiversityFilter`) |
| `backend/api/pool.py` | Implement |
| `backend/schemas/pool.py` | Create |
| `tests/services/test_proxy_data.py` | Create |
| `tests/services/test_diversity_filter.py` | Create |
| `tests/api/test_pool.py` | Create |
