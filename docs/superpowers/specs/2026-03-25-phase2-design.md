# Phase 2 Design: WQ Brain Interface & Manual Queue

**Date**: 2026-03-25
**Status**: Approved
**Scope**: `backend/services/wq_interface.py`, `backend/api/submit.py`, `backend/schemas/simulation.py`, `backend/config.py`, tests

---

## 1. Goals

Implement the WQ Brain submission layer so alphas generated in Phase 1 can be:
- Exported for manual copy-paste into WQ Brain UI (`ManualQueueClient`)
- Auto-submitted via the unofficial WQ Brain API (`AutoAPIClient`)
- Result data imported back into the DB and visible via API

**Phase 2 KPI**: User can export a batch of pending alphas, submit them to WQ Brain (manually or automatically), paste/receive results back, and query the updated simulation records.

---

## 2. Service Layer — `backend/services/wq_interface.py`

### 2.1 Abstract Base

`db: Session` is passed as a method argument to match the existing FastAPI dependency pattern (`Depends(get_db)`) throughout the codebase.

`SimulationRead` (the existing Pydantic schema) is the return type — no separate `SimulationResult` type is introduced.

```python
class WQBrainInterface(ABC):
    @abstractmethod
    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        """Create Simulation DB row and initiate submission. Returns str(simulation.id)."""

    @abstractmethod
    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        """Retrieve result for a simulation by its DB id."""
```

### 2.2 ManualQueueClient

- `submit(alpha, db)` — inserts `Simulation(status="pending", submitted_at=now)`, returns `str(simulation.id)`
- `get_result(simulation_id, db)` — reads Simulation row from DB; returns `None` if not found
- `export_pending(db, format="json")` — queries `status="pending"`, returns list of dicts (JSON) or CSV string:

```json
{
  "alpha_id": "a3f9...",
  "expression": "-rank(ts_delta(close, 5))",
  "settings": {
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 4,
    "neutralization": "Subindustry",
    "truncation": 0.08,
    "pasteurization": "Off",
    "nan_handling": "Off"
  }
}
```

For CSV export, each settings field becomes a column alongside `alpha_id` and `expression`.

**Who creates the pending rows?** The `POST /generate/mutate` endpoint (Phase 1) saves alpha rows but does not create simulation rows. The `POST /api/submit/auto/{alpha_id}` endpoint creates a simulation row by calling `submit()`. For the manual flow, `POST /api/submit/queue` (enqueue) is responsible — see Section 3.

### 2.3 AutoAPIClient

Uses `httpx.AsyncClient`. Credentials loaded from `config.py` at construction time.

**WQ Brain API endpoints used**:

| Action | Method | URL |
|--------|--------|-----|
| Login | POST | `https://api.worldquantbrain.com/authentication` |
| Submit simulation | POST | `https://api.worldquantbrain.com/simulations` |
| Poll status | GET | `{Location header from submit response}` |
| Fetch metrics | GET | `https://api.worldquantbrain.com/alphas/{alpha_link}` |

**Auth flow**:
1. `POST /authentication` with HTTP Basic (email, password from config)
2. If response contains `inquiryId`: raise `BiometricAuthRequired(url)` — caller returns HTTP 503 with the biometric URL
3. On success: session cookies stored in `httpx.AsyncClient`; re-login on 401

**`submit()` flow** (async, non-blocking — uses `await asyncio.sleep()` in the polling loop):
1. `await _login()` if not already authenticated
2. `POST /simulations` with body (all settings taken from `alpha`):
   ```json
   {
     "type": "REGULAR",
     "settings": {
       "instrumentType": "EQUITY",
       "region": "<alpha.region>",
       "universe": "<alpha.universe>",
       "delay": "<alpha.delay>",
       "decay": "<alpha.decay>",
       "neutralization": "<alpha.neutralization.upper()>",
       "truncation": "<alpha.truncation>",
       "pasteurization": "<alpha.pasteurization.upper()>",
       "nanHandling": "<alpha.nan_handling.upper()>",
       "language": "FASTEXPR",
       "visualization": false
     },
     "regular": "<alpha.expression>"
   }
   ```
3. Extract `location_url` from `Location` response header. Store the full URL in `wq_sim_id` (the DB field stores the full polling URL verbatim, which the poll step uses directly).
4. Insert `Simulation(status="submitted", wq_sim_id=location_url, submitted_at=now)` into DB
5. Poll `GET {location_url}` every `WQ_POLL_INTERVAL_SEC` seconds (non-blocking: `await asyncio.sleep()`):
   - `status == "DONE"` → proceed to step 6
   - `status in ("ERROR", "CANCELLED", "FAILED")` → raise `SimulationFailed(status)` → set DB row to `status="failed"`, return
   - Elapsed > `WQ_POLL_TIMEOUT_SEC` → raise `SimulationTimeout` → leave DB row as `status="submitted"`, return
6. `GET /alphas/{alpha_link}` to extract Sharpe, fitness, returns, turnover, passed
7. Update Simulation row: `status="completed"`, populate metrics, `completed_at=now`
8. Return `str(simulation.id)`

**Error mapping**:
| Exception | HTTP Status | DB row state |
|-----------|------------|-------------|
| `BiometricAuthRequired` | 503 | no row created |
| `SimulationTimeout` | 504 | `status="submitted"` |
| `SimulationFailed` | 502 | `status="failed"` |
| Non-2xx from WQ Brain (submit) | 502 | `status="failed"` |

---

## 3. API Endpoints — `backend/api/submit.py`

### `POST /api/submit/queue` (enqueue for manual)
- Body: `{ "alpha_id": "..." }`
- Looks up Alpha; 404 if not found
- Calls `ManualQueueClient.submit(alpha, db)` to create a `Simulation(status="pending")` row
- Returns: `SimulationRead`
- Edge case: if a `pending` row already exists for this alpha, return 409 Conflict

### `GET /api/submit/queue`
- Query param: `status: str | None` (filter by `pending|submitted|completed|failed`)
- Returns: `list[SimulationRead]`

### `GET /api/submit/export`
- Query param: `format: str = "json"` (`"json"` or `"csv"`)
- Calls `ManualQueueClient.export_pending(db, format)`
- JSON response: `list[dict]` (WQ Brain UI format); returns empty list if no pending alphas
- CSV response: `text/csv` with headers; returns empty CSV with header row if no pending alphas

### `POST /api/submit/result`
- Body: `ResultImportRequest`
- Lookup: if `simulation_id` provided → look up by id; else find most recent `status="pending"` row for `alpha_id`
- 404 if no matching row found
- 409 if the matched row is already `status="completed"` (idempotency guard)
- Updates: `status="completed"`, populates metrics, `completed_at=now`
- Returns: `SimulationRead`

### `POST /api/submit/auto/{alpha_id}`
- `async def` route — non-blocking poll via `await asyncio.sleep()`
- Looks up Alpha by id; 404 if not found
- 409 if a `status="submitted"` row already exists for this alpha (prevents duplicate in-flight submissions)
- Calls `AutoAPIClient.submit(alpha, db)` — awaits completion
- Returns: `SimulationRead`

---

## 4. Schemas — `backend/schemas/simulation.py`

Add `ResultImportRequest`:

```python
class ResultImportRequest(BaseModel):
    alpha_id: str
    simulation_id: int | None = None   # Optional: target a specific simulation row
    sharpe: float
    fitness: float
    returns: float
    turnover: float
    passed: bool
    notes: str | None = None
```

`SimulationRead` (existing) is reused as response model throughout.

---

## 5. Config — `backend/config.py` and `.env.example`

Add to `Settings`:

```python
WQ_EMAIL: str = ""
WQ_PASSWORD: str = ""
WQ_POLL_INTERVAL_SEC: float = 5.0
WQ_POLL_TIMEOUT_SEC: float = 300.0
```

Add to `.env.example` (with sensitivity comment):
```
# WQ Brain credentials — do NOT commit to version control
WQ_EMAIL=your@email.com
WQ_PASSWORD=yourpassword
```

---

## 6. Tests

### `tests/services/test_wq_interface.py`

**ManualQueueClient**:
- `submit()` creates a `Simulation` row with `status="pending"`
- `submit()` for an alpha that already has a pending row raises an appropriate error
- `export_pending()` returns correctly shaped JSON dicts
- `export_pending(format="csv")` returns CSV string with correct columns
- `export_pending()` returns empty list/CSV when no pending alphas exist
- `get_result()` reads populated simulation row; returns `None` for unknown id

**AutoAPIClient** (mock `httpx.AsyncClient`):
- Successful login sets session cookies
- `BiometricAuthRequired` raised when `inquiryId` in login response
- `submit()` calls correct endpoints in order with per-alpha settings in body
- `wq_sim_id` stores the full Location URL verbatim
- Polling loop terminates when status is `"DONE"`
- `SimulationFailed` raised when WQ Brain returns `"ERROR"` or `"CANCELLED"` status
- `SimulationTimeout` raised when poll exceeds timeout; DB row remains `"submitted"`
- Non-2xx submit response sets DB row to `"failed"`

### `tests/api/test_submit.py`
- `POST /queue` creates a pending simulation row
- `POST /queue` for alpha that already has pending row returns 409
- `GET /queue` returns all simulations
- `GET /queue?status=pending` filters correctly
- `GET /export` returns JSON in WQ Brain format
- `GET /export` returns empty list when no pending alphas
- `GET /export?format=csv` returns `text/csv`
- `POST /result` updates simulation row to `completed`
- `POST /result` with `simulation_id` targets specific row
- `POST /result` with unknown `alpha_id` returns 404
- `POST /result` called twice on same row returns 409
- `POST /auto/{id}` with mocked `AutoAPIClient` returns `SimulationRead`
- `POST /auto/{id}` when `"submitted"` row already exists returns 409

---

## 7. Files Changed / Created

| File | Action |
|------|--------|
| `backend/services/wq_interface.py` | Implement (replace stub) |
| `backend/api/submit.py` | Implement (replace stub) |
| `backend/schemas/simulation.py` | Add `ResultImportRequest` |
| `backend/config.py` | Add 4 WQ config fields |
| `.env.example` | Add `WQ_EMAIL`, `WQ_PASSWORD` |
| `tests/services/__init__.py` | Create (new test package) |
| `tests/services/test_wq_interface.py` | Create |
| `tests/api/test_submit.py` | Create |
