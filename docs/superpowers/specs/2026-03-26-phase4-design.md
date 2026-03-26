# Phase 4 Design: LLM Generator (Claude API)

**Date**: 2026-03-26
**Status**: Approved
**Scope**: `backend/core/llm_generator.py`, `backend/api/generate.py`, `backend/schemas/alpha.py`, `backend/services/diversity_filter.py`, tests

---

## 1. Goals

- Implement `LLMGenerator` that calls the Claude API to produce novel WQ Fast Expression alphas
- Wire `DiversityFilter` into both the mutate and LLM generation flows
- Enforce a daily call-rate cap (`LLM_MAX_CALLS_PER_DAY`, default 20)

**Phase 4 KPI**: Given a populated pool of 10+ alphas, the LLM generator produces syntactically valid candidates with at least 50% surviving diversity filtering.

---

## 2. `DiversityFilter` extension — `backend/services/diversity_filter.py`

Add a `filter_batch()` method that pre-evaluates the pool once and reuses results across all candidates (avoids re-evaluating pool members per-candidate).

```python
def filter_batch(
    self,
    candidates: list[AlphaCandidate],
    pool: list[AlphaCandidate],
    evaluator: AlphaEvaluator,
    panel: pd.DataFrame,
) -> list[tuple[AlphaCandidate, bool, float]]:
    """
    Returns list of (candidate, should_submit, max_corr).
    - should_submit=True + max_corr=nan → filter_skipped=True
    - should_submit=True + max_corr=0.0 → empty pool or all pool evaluations failed
    - should_submit=False + max_corr>threshold → rejected by diversity
    Pre-evaluates all pool members once for efficiency.
    """
```

**Logic**:
1. Pre-evaluate all pool members; store `{member_id: dropna'd Series}` for those ≥ 10 values
2. For each candidate: evaluate → compute correlations against pre-evaluated pool values → same decision logic as `should_submit()`
3. Same NaN-handling and min-10-points guards as `should_submit()`

---

## 3. `LLMGenerator` — `backend/core/llm_generator.py`

### 3.1 PoolContext

```python
@dataclass
class PoolContext:
    top_alphas: list[dict]   # Top 10 by fitness: {expression, sharpe, fitness, returns, turnover}
    total_pool_size: int
```

### 3.2 LLMGenerator class

```python
class LLMGenerator:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or get_settings().CLAUDE_MODEL

    def generate(
        self,
        pool_context: PoolContext,
        theme: str | None = None,
        n: int = 10,
    ) -> list[AlphaCandidate]:
        """
        Call Claude API once and parse the response into AlphaCandidates.
        Malformed JSON entries or entries with missing `expression` are silently dropped.
        Returns list of raw AlphaCandidates (not yet validated or diversity-filtered).
        """

    def _build_system_prompt(self) -> str: ...
    def _build_user_prompt(self, pool_context: PoolContext, theme: str | None, n: int) -> str: ...
    def _parse_response(self, raw: str) -> list[dict]: ...
    def _dict_to_candidate(self, d: dict, default_settings: dict) -> AlphaCandidate | None: ...
```

### 3.3 System Prompt (static)

```
You are a quantitative finance researcher specializing in formulaic alpha expressions
for the WorldQuant BRAIN platform (IQC competition, USA TOP3000 equity universe).

## WQ Fast Expression Syntax

Expressions operate on cross-sectional stock panels. Available data fields:
  close, open, high, low, volume  — daily OHLCV
  returns                          — daily return (close/prev_close - 1)
  adv{N}                           — avg daily dollar volume, e.g. adv20
  cap                              — market capitalization
  vwap                             — volume-weighted average price

Cross-sectional functions (operate across all stocks each day):
  rank(x)                          — percentile rank [0, 1]
  zscore(x)                        — z-score across stocks
  scale(x)                         — normalize: sum(abs(x)) = 1
  IndNeutralize(x, IndClass.X)     — neutralize by sector/industry/subindustry

Time-series functions (operate over time per stock, n = lookback window):
  ts_mean(x, n)    ts_std(x, n)    ts_delta(x, n)    ts_rank(x, n)
  ts_corr(x, y, n) ts_max(x, n)   ts_min(x, n)      ts_median(x, n)
  ts_argmax(x, n)  ts_argmin(x, n)

Math: log(x), abs(x), sign(x), and arithmetic +, -, *, /

## Output Format

Return ONLY a JSON array. Each element must have:
  "expression"    : string   — WQ Fast Expression (required)
  "neutralization": string   — "none"|"market"|"sector"|"industry"|"subindustry" (optional)
  "decay"         : integer  — 0 to 20 (optional)
  "rationale"     : string   — one-sentence alpha hypothesis (required)

Example:
[
  {
    "expression": "-rank(ts_delta(close, 5))",
    "neutralization": "subindustry",
    "decay": 4,
    "rationale": "Short-term mean reversion: stocks that fell most in 5 days tend to bounce."
  }
]

CRITICAL: Respond with ONLY the JSON array — no explanation, no markdown, no preamble.
```

### 3.4 User Prompt (dynamic)

```
## Current Alpha Pool

Pool size: {total_pool_size} alphas with completed simulations.

Top alphas by Fitness:
{top_alphas_formatted}

(Higher Fitness = better. Fitness = sqrt(|Returns| / max(Turnover, 0.125)) * Sharpe)

## Task

Generate {n} alpha expressions that are:
1. Syntactically valid WQ Fast Expressions
2. Conceptually different from the alphas listed above (avoid similar logic)
{theme_line}

Prefer subindustry neutralization and low-turnover signals (Fitness > 1.0 target).
```

Where `{theme_line}` is either empty or `3. Focus on this theme: {theme}`.

`{top_alphas_formatted}`: one line per alpha:
```
- expression="{expr}"  sharpe={sharpe:.2f}  fitness={fitness:.2f}  returns={returns:.3f}  turnover={turnover:.3f}
```
If pool is empty: use `(pool is empty — generate diverse foundational alphas)`

### 3.5 Response parsing (`_parse_response`)

1. Try `json.loads(raw)` directly
2. If that fails: extract the first `[...]` block via regex `r'\[.*\]'` with `re.DOTALL` and try again
3. If still fails: log warning, return `[]`
4. For each entry: must be a `dict` with non-empty `"expression"` key; others dropped silently

### 3.6 Candidate construction (`_dict_to_candidate`)

For each valid parsed dict:
- `expression` = `d["expression"].strip()`
- `neutralization` = `d.get("neutralization", "subindustry").lower()` — validated to one of allowed values; falls back to `"subindustry"` if invalid
- `decay` = `max(0, min(20, int(d.get("decay", 0))))` — clamped; defaults to 0
- `rationale` = `d.get("rationale", None)`
- All other settings use IQC defaults: `region="USA"`, `universe="TOP3000"`, `delay=1`, `truncation=0.08`, `pasteurization="off"`, `nan_handling="off"`
- `source = AlphaSource.LLM`
- `id` = SHA256 hash of `(expression, config)` — same as existing convention
- Returns `None` if any construction error

---

## 4. API Endpoints — `backend/api/generate.py`

### 4.1 New schemas in `backend/schemas/alpha.py`

```python
class LLMRequest(BaseModel):
    theme: str | None = None
    n: int = 10

class LLMResponse(BaseModel):
    run_id: int
    candidates_generated: int          # raw from LLM (post-parse, pre-validation)
    candidates_passed_validation: int   # after ExpressionValidator
    candidates_passed_diversity: int    # after DiversityFilter (excluding filter_skipped)
    candidates_skipped_filter: int      # filter_skipped=True (unevaluable, still saved)
    candidates_rejected_diversity: int  # rejected — not saved
    candidates: list[AlphaRead]         # all saved candidates
```

### 4.2 `POST /generate/llm` (replaces stub)

```
POST /api/generate/llm
Body: LLMRequest
Returns: LLMResponse (201)
Errors: 503 if CLAUDE_API_KEY not configured, 429 if daily limit exceeded
```

**Flow**:
1. Check `settings.CLAUDE_API_KEY` — 503 if empty
2. Count today's LLM runs: `db.query(Run).filter(Run.mode=="llm", Run.started_at >= today_utc).count()` — 429 if >= `LLM_MAX_CALLS_PER_DAY`
3. `started_at = datetime.now(timezone.utc)`
4. Build `PoolContext` from DB (top 10 completed by fitness)
5. `generator = LLMGenerator(api_key=settings.CLAUDE_API_KEY)`
6. `raw_candidates = generator.generate(pool_context, theme=body.theme, n=body.n)`
7. Validate each: `_validator.validate(c.expression)` — drop invalids
8. Run diversity filter: load panel + pool alphas → `DiversityFilter(threshold).filter_batch(valid_candidates, pool, evaluator, panel)` — if panel empty, all pass with `filter_skipped=True`
9. Categorise results:
   - `should_submit=True, max_corr=nan` → save with `filter_skipped=True`
   - `should_submit=True, max_corr!=nan` → save with `filter_skipped=False`
   - `should_submit=False` → do NOT save (rejected)
10. Skip saving if already in DB (same id)
11. Persist `Run(mode="llm", llm_theme=body.theme, candidates_gen=len(raw), candidates_pass=len(saved), started_at=..., finished_at=now)`
12. Return `LLMResponse`

**Pool alphas for diversity** = all alphas with at least one `completed` simulation.

### 4.3 Diversity filter in `POST /generate/mutate` (update existing)

Add after the existing validation step:

```python
# Diversity filtering (Phase 4)
panel = _proxy_mgr.get_panel(db)
pool_alphas = _get_pool_alphas(db)  # alphas with completed simulation
if not panel.empty and pool_alphas:
    filter_results = DiversityFilter(settings.DIVERSITY_THRESHOLD).filter_batch(
        all_candidates, pool_alphas, _evaluator, panel
    )
    # Separate accepted (should_submit=True) from rejected
    all_candidates = [c for c, ok, _ in filter_results if ok]
    for c, ok, corr in filter_results:
        if ok and not np.isnan(corr):
            c.filter_skipped = (corr == 0.0 and not pool_alphas)  # False normally
        if ok and np.isnan(corr):
            c.filter_skipped = True
else:
    # No panel data — mark all filter_skipped
    for c in all_candidates:
        c.filter_skipped = True
```

Actually, the simpler way: update `filter_skipped` field on the candidate BEFORE saving, based on the filter result.

---

## 5. Helper — `_get_pool_alphas(db)`

Module-level helper in `generate.py`:
```python
def _get_pool_alphas(db: Session) -> list[AlphaCandidate]:
    """Return all alphas that have at least one completed simulation."""
    from backend.models.simulation import Simulation
    alpha_ids = {s.alpha_id for s in db.query(Simulation).filter(Simulation.status == "completed").all()}
    alphas = [db.get(Alpha, aid) for aid in alpha_ids]
    return [_alpha_orm_to_candidate(a) for a in alphas if a]
```

---

## 6. Tests

### `tests/core/test_llm_generator.py`

Mock `anthropic.Anthropic` throughout.

- `generate()` calls `messages.create` once with correct model + prompts
- `generate()` returns correct number of `AlphaCandidate` objects from well-formed response
- `_parse_response()` handles valid JSON array string
- `_parse_response()` extracts JSON from markdown code block
- `_parse_response()` returns `[]` for completely malformed response
- `_parse_response()` drops entries missing `"expression"` key
- `_dict_to_candidate()` clamps `decay` to [0, 20]
- `_dict_to_candidate()` falls back to `"subindustry"` for invalid neutralization value
- `generate()` with empty pool produces correct user prompt (mentions "pool is empty")

### `tests/api/test_generate_llm.py`

Mock `LLMGenerator.generate` for all tests.

- `POST /generate/llm` with missing/empty `CLAUDE_API_KEY` returns 503
- `POST /generate/llm` when daily limit reached returns 429
- `POST /generate/llm` with valid setup returns 201 and `LLMResponse`
- `run_id` in response corresponds to a `Run` with `mode="llm"`
- `candidates` contains `AlphaRead` objects with `source="llm"`
- Rejected candidates (mock returns high-correlation alpha) not in response
- `filter_skipped=True` candidates are saved and included in response
- Second call on same day increments run count (still under limit)
- Calling after limit is reached returns 429

### `tests/services/test_diversity_filter.py` (extend existing)

- `filter_batch()` with empty pool returns all `(cand, True, 0.0)`
- `filter_batch()` with unevaluable candidate returns `(cand, True, nan)`
- `filter_batch()` correctly rejects high-correlation candidate
- `filter_batch()` pre-evaluates pool only once (can verify by counting calls if needed)

---

## 7. Files Changed / Created

| File | Action |
|------|--------|
| `backend/core/llm_generator.py` | Implement |
| `backend/api/generate.py` | Add LLM endpoint + diversity filter integration in mutate |
| `backend/schemas/alpha.py` | Add `LLMRequest`, `LLMResponse` |
| `backend/services/diversity_filter.py` | Add `filter_batch()` to `DiversityFilter` |
| `tests/core/__init__.py` | Create (new test package) |
| `tests/core/test_llm_generator.py` | Create |
| `tests/api/test_generate_llm.py` | Create |
