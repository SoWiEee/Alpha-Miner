# Phase 2: WQ Brain Interface & Manual Queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the WQ Brain submission layer — export pending alphas, auto-submit via unofficial API, and import results back into the DB.

**Architecture:** `WQBrainInterface` (ABC) with two concrete implementations: `ManualQueueClient` (DB-only queue) and `AutoAPIClient` (async httpx, blocking poll). Five submit endpoints replace the Phase 1 stub. All simulation state lives in the `simulations` DB table.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, httpx (async), pytest-asyncio, SQLite in-memory for tests.

**Spec:** `docs/superpowers/specs/2026-03-25-phase2-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add `asyncio_mode = "auto"` for async tests |
| `backend/config.py` | Modify | Add `WQ_EMAIL`, `WQ_PASSWORD`, `WQ_POLL_INTERVAL_SEC`, `WQ_POLL_TIMEOUT_SEC` |
| `.env.example` | Modify | Add WQ credential fields with security comment |
| `backend/schemas/simulation.py` | Modify | Add `ResultImportRequest`, `EnqueueRequest` |
| `backend/services/wq_interface.py` | Implement | `WQBrainInterface` ABC, exceptions, `ManualQueueClient`, `AutoAPIClient` |
| `backend/api/submit.py` | Implement | 5 endpoints: POST /queue, GET /queue, GET /export, POST /result, POST /auto/{id} |
| `tests/services/__init__.py` | Create | Empty init for test package |
| `tests/services/test_wq_interface.py` | Create | Unit tests for ManualQueueClient and AutoAPIClient (mocked httpx) |
| `tests/api/test_submit.py` | Create | Integration tests for all 5 submit endpoints |

---

## Task 1: Groundwork — config, .env.example, pytest asyncio

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add asyncio_mode to pyproject.toml**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Add WQ fields to config.py**

In `backend/config.py`, add four fields after `WQ_REQUEST_INTERVAL_SEC`:

```python
WQ_EMAIL: str = ""
WQ_PASSWORD: str = ""
WQ_POLL_INTERVAL_SEC: float = 5.0
WQ_POLL_TIMEOUT_SEC: float = 300.0
```

- [ ] **Step 3: Update .env.example**

Add to the `WQ Brain` section in `.env.example`:

```
# WQ Brain credentials — do NOT commit to version control
WQ_EMAIL=your@email.com
WQ_PASSWORD=yourpassword
WQ_POLL_INTERVAL_SEC=5.0
WQ_POLL_TIMEOUT_SEC=300.0
```

- [ ] **Step 4: Verify config loads**

```bash
uv run python -c "from backend.config import get_settings; s = get_settings(); print(s.WQ_EMAIL, s.WQ_POLL_INTERVAL_SEC)"
```

Expected output: ` 5.0` (empty email, float value)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml backend/config.py .env.example
git commit -m "feat: add WQ credential config fields and pytest asyncio mode"
```

---

## Task 2: Schemas — ResultImportRequest and EnqueueRequest

**Files:**
- Modify: `backend/schemas/simulation.py`
- Test: `tests/schemas/test_schemas.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/schemas/test_schemas.py`:

```python
from backend.schemas.simulation import ResultImportRequest, EnqueueRequest


def test_result_import_request_full():
    r = ResultImportRequest(
        alpha_id="abc123",
        sharpe=1.43,
        fitness=1.12,
        returns=0.087,
        turnover=0.61,
        passed=True,
    )
    assert r.alpha_id == "abc123"
    assert r.simulation_id is None
    assert r.notes is None


def test_result_import_request_with_simulation_id():
    r = ResultImportRequest(
        alpha_id="abc123",
        simulation_id=42,
        sharpe=1.43,
        fitness=1.12,
        returns=0.087,
        turnover=0.61,
        passed=True,
        notes="test note",
    )
    assert r.simulation_id == 42
    assert r.notes == "test note"


def test_enqueue_request():
    r = EnqueueRequest(alpha_id="abc123")
    assert r.alpha_id == "abc123"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/schemas/test_schemas.py::test_result_import_request_full -v
```

Expected: `FAILED` — `ImportError: cannot import name 'ResultImportRequest'`

- [ ] **Step 3: Add schemas to simulation.py**

Append to `backend/schemas/simulation.py`:

```python
class EnqueueRequest(BaseModel):
    alpha_id: str


class ResultImportRequest(BaseModel):
    alpha_id: str
    simulation_id: int | None = None
    sharpe: float
    fitness: float
    returns: float
    turnover: float
    passed: bool
    notes: str | None = None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/schemas/test_schemas.py -v
```

Expected: all pass (including previously passing tests)

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/simulation.py tests/schemas/test_schemas.py
git commit -m "feat: add ResultImportRequest and EnqueueRequest schemas"
```

---

## Task 3: Exceptions + WQBrainInterface ABC

**Files:**
- Implement: `backend/services/wq_interface.py`

No tests needed for the ABC itself — it is untestable by design (abstract). Exceptions are tested implicitly through the concrete classes.

- [ ] **Step 1: Write the base structure**

Replace `backend/services/wq_interface.py` with:

```python
"""WQ Brain submission interface — Manual and Auto implementations."""
from __future__ import annotations

import asyncio
import csv
import io
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from backend.core.models import AlphaCandidate
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.schemas.simulation import SimulationRead

# ── WQ Brain API constants ───────────────────────────────────────────────────

WQ_AUTH_URL = "https://api.worldquantbrain.com/authentication"
WQ_SIMULATIONS_URL = "https://api.worldquantbrain.com/simulations"
WQ_ALPHAS_URL = "https://api.worldquantbrain.com/alphas/{alpha_id}"

WQ_DONE_STATUSES = {"DONE"}
WQ_FAILED_STATUSES = {"ERROR", "CANCELLED", "FAILED"}


# ── Custom exceptions ────────────────────────────────────────────────────────

class BiometricAuthRequired(Exception):
    """Raised when WQ Brain requires biometric (2FA) authentication."""
    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Biometric authentication required. Complete it at: {url}")


class SimulationTimeout(Exception):
    """Raised when a simulation does not complete within the poll timeout."""


class SimulationFailed(Exception):
    """Raised when WQ Brain returns a terminal failure status."""
    def __init__(self, wq_status: str) -> None:
        self.wq_status = wq_status
        super().__init__(f"WQ Brain simulation failed with status: {wq_status}")


# ── Abstract interface ───────────────────────────────────────────────────────

class WQBrainInterface(ABC):
    @abstractmethod
    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        """Create Simulation DB row and initiate submission. Returns str(simulation.id)."""

    @abstractmethod
    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        """Retrieve result for a simulation by its DB id. Returns None if not found."""
```

- [ ] **Step 2: Verify import works**

```bash
uv run python -c "from backend.services.wq_interface import WQBrainInterface, BiometricAuthRequired, SimulationTimeout, SimulationFailed; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/wq_interface.py
git commit -m "feat: add WQBrainInterface ABC and custom exceptions"
```

---

## Task 4: ManualQueueClient (TDD)

**Files:**
- Create: `tests/services/__init__.py`
- Create: `tests/services/test_wq_interface.py`
- Modify: `backend/services/wq_interface.py`

- [ ] **Step 1: Create test package**

Create `tests/services/__init__.py` as an empty file.

- [ ] **Step 2: Write failing tests for ManualQueueClient**

Create `tests/services/test_wq_interface.py`:

```python
"""Tests for WQBrainInterface concrete implementations."""
import pytest
from backend.core.models import AlphaCandidate, AlphaSource
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.services.wq_interface import ManualQueueClient


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_alpha_orm(db, expression="-rank(ts_delta(close,5))") -> Alpha:
    """Insert a minimal Alpha row and return the ORM object."""
    from backend.core.models import compute_alpha_id
    alpha_id = compute_alpha_id(expression, "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    orm = Alpha(
        id=alpha_id, expression=expression, universe="TOP3000", region="USA",
        delay=1, decay=0, neutralization="subindustry", truncation=0.08,
        pasteurization="off", nan_handling="off", source="seed",
        parent_id=None, rationale=None, filter_skipped=False,
    )
    db.add(orm)
    db.commit()
    db.refresh(orm)
    return orm


def _orm_to_candidate(orm: Alpha) -> AlphaCandidate:
    return AlphaCandidate(
        id=orm.id, expression=orm.expression, universe=orm.universe,
        region=orm.region, delay=orm.delay, decay=orm.decay,
        neutralization=orm.neutralization, truncation=orm.truncation,
        pasteurization=orm.pasteurization, nan_handling=orm.nan_handling,
        source=AlphaSource(orm.source), parent_id=orm.parent_id,
        rationale=orm.rationale, created_at=orm.created_at,
        filter_skipped=orm.filter_skipped,
    )


# ── ManualQueueClient ─────────────────────────────────────────────────────────

class TestManualQueueClient:
    def setup_method(self):
        self.client = ManualQueueClient()

    async def test_submit_creates_pending_simulation(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        sim_id = await self.client.submit(alpha, test_db)
        sim = test_db.get(Simulation, int(sim_id))
        assert sim is not None
        assert sim.alpha_id == alpha.id
        assert sim.status == "pending"
        assert sim.submitted_at is not None

    async def test_submit_returns_string_id(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        result = await self.client.submit(alpha, test_db)
        assert isinstance(result, str)
        assert int(result) > 0  # valid integer as string

    async def test_submit_duplicate_pending_raises(self, test_db):
        orm = _make_alpha_orm(test_db, expression="-rank(ts_mean(close,5))")
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)  # first submit — creates pending row
        with pytest.raises(ValueError, match="pending simulation"):
            await self.client.submit(alpha, test_db)  # second — should raise

    async def test_get_result_returns_simulation_read(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        sim_id = await self.client.submit(alpha, test_db)
        result = await self.client.get_result(sim_id, test_db)
        assert result is not None
        assert result.alpha_id == alpha.id
        assert result.status == "pending"

    async def test_get_result_returns_none_for_unknown_id(self, test_db):
        result = await self.client.get_result("99999", test_db)
        assert result is None

    async def test_export_pending_json_format(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)
        rows = self.client.export_pending(test_db, format="json")
        assert len(rows) == 1
        row = rows[0]
        assert row["alpha_id"] == alpha.id
        assert row["expression"] == alpha.expression
        assert "settings" in row
        s = row["settings"]
        assert s["region"] == "USA"
        assert s["universe"] == "TOP3000"
        assert s["delay"] == 1
        assert s["decay"] == 0

    async def test_export_pending_csv_format(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)
        csv_text = self.client.export_pending(test_db, format="csv")
        assert isinstance(csv_text, str)
        lines = csv_text.strip().splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert "alpha_id" in lines[0]
        assert "expression" in lines[0]

    async def test_export_pending_empty_json(self, test_db):
        rows = self.client.export_pending(test_db, format="json")
        assert rows == []

    async def test_export_pending_empty_csv(self, test_db):
        csv_text = self.client.export_pending(test_db, format="csv")
        assert isinstance(csv_text, str)
        lines = [l for l in csv_text.strip().splitlines() if l]
        assert len(lines) == 1  # header only
        assert "alpha_id" in lines[0]
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/services/test_wq_interface.py::TestManualQueueClient -v
```

Expected: `ERROR` — `ImportError: cannot import name 'ManualQueueClient'`

- [ ] **Step 4: Implement ManualQueueClient**

Append to `backend/services/wq_interface.py`:

```python
# ── ManualQueueClient ────────────────────────────────────────────────────────

class ManualQueueClient(WQBrainInterface):
    """Queue-only client: creates pending Simulation rows; results imported manually."""

    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        existing = (
            db.query(Simulation)
            .filter(Simulation.alpha_id == alpha.id, Simulation.status == "pending")
            .first()
        )
        if existing:
            raise ValueError(f"A pending simulation already exists for alpha {alpha.id}")
        sim = Simulation(
            alpha_id=alpha.id,
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(sim)
        db.commit()
        db.refresh(sim)
        return str(sim.id)

    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        sim = db.get(Simulation, int(simulation_id))
        if sim is None:
            return None
        return SimulationRead.model_validate(sim)

    def export_pending(self, db: Session, format: str = "json") -> list[dict] | str:
        """Export pending alphas formatted for WQ Brain UI fields."""
        sims = db.query(Simulation).filter(Simulation.status == "pending").all()
        rows: list[dict] = []
        for sim in sims:
            alpha = db.get(Alpha, sim.alpha_id)
            if alpha is None:
                continue
            rows.append({
                "alpha_id": alpha.id,
                "expression": alpha.expression,
                "settings": {
                    "region": alpha.region,
                    "universe": alpha.universe,
                    "delay": alpha.delay,
                    "decay": alpha.decay,
                    "neutralization": alpha.neutralization.capitalize(),
                    "truncation": alpha.truncation,
                    "pasteurization": alpha.pasteurization.capitalize(),
                    "nan_handling": alpha.nan_handling.capitalize(),
                },
            })

        if format == "csv":
            output = io.StringIO()
            fieldnames = ["alpha_id", "expression", "region", "universe",
                          "delay", "decay", "neutralization", "truncation",
                          "pasteurization", "nan_handling"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "alpha_id": row["alpha_id"],
                    "expression": row["expression"],
                    **row["settings"],
                })
            return output.getvalue()

        return rows
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/services/test_wq_interface.py::TestManualQueueClient -v
```

Expected: all 9 tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/wq_interface.py tests/services/__init__.py tests/services/test_wq_interface.py
git commit -m "feat: implement ManualQueueClient with TDD"
```

---

## Task 5: AutoAPIClient (TDD)

**Files:**
- Modify: `tests/services/test_wq_interface.py` (append new test class)
- Modify: `backend/services/wq_interface.py` (append AutoAPIClient)

- [ ] **Step 1: Write failing tests for AutoAPIClient**

Append to `tests/services/test_wq_interface.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.wq_interface import AutoAPIClient, BiometricAuthRequired, SimulationFailed, SimulationTimeout


def _make_httpx_response(status_code: int, json_data: dict, headers: dict = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    resp.is_success = 200 <= status_code < 300
    return resp


LOCATION_URL = "https://api.worldquantbrain.com/simulations/sim-abc123"
ALPHA_URL = "https://api.worldquantbrain.com/alphas/alpha-xyz"

METRICS_RESPONSE = {
    "is": {
        "sharpe": 1.43,
        "fitness": 1.12,
        "returns": 0.087,
        "turnover": 0.61,
        "checks": [{"type": "SELF_CORRELATION", "result": "PASS"}],
    }
}


def _make_auto_client() -> AutoAPIClient:
    return AutoAPIClient(
        email="test@example.com",
        password="secret",
        poll_interval=0.01,   # fast for tests
        poll_timeout=1.0,
    )


class TestAutoAPIClient:
    async def test_login_success_sets_authenticated(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        poll_resp = _make_httpx_response(200, {"status": "DONE", "alpha": ALPHA_URL})
        metrics_resp = _make_httpx_response(200, METRICS_RESPONSE)

        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_resp]
            mock_instance.get.side_effect = [poll_resp, metrics_resp]

            sim_id = await client.submit(alpha, test_db)

        sim = test_db.get(Simulation, int(sim_id))
        assert sim.status == "completed"

    async def test_biometric_auth_raises(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {
            "inquiryId": "inq-123",
            "message": "https://platform.worldquantbrain.com/?inquiryId=inq-123",
        })

        orm = _make_alpha_orm(test_db, expression="-rank(ts_delta(open,5))")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.return_value = login_resp

            with pytest.raises(BiometricAuthRequired) as exc:
                await client.submit(alpha, test_db)

        assert "inq-123" in exc.value.url

    async def test_submit_body_uses_alpha_settings(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        poll_resp = _make_httpx_response(200, {"status": "DONE", "alpha": ALPHA_URL})
        metrics_resp = _make_httpx_response(200, METRICS_RESPONSE)

        # Alpha with non-default settings
        orm = _make_alpha_orm(test_db, expression="rank(ts_mean(close,20))")
        # Manually set decay
        orm.decay = 4
        orm.neutralization = "market"
        test_db.commit()
        alpha = _orm_to_candidate(orm)

        captured_body = {}

        async def capture_post(url, **kwargs):
            if url == "https://api.worldquantbrain.com/simulations":
                captured_body.update(kwargs.get("json", {}))
                return submit_resp
            return login_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = capture_post
            mock_instance.get.side_effect = [poll_resp, metrics_resp]

            await client.submit(alpha, test_db)

        assert captured_body["settings"]["decay"] == 4
        assert captured_body["settings"]["neutralization"] == "MARKET"
        assert captured_body["regular"] == "rank(ts_mean(close,20))"
        assert captured_body["settings"]["language"] == "FASTEXPR"

    async def test_wq_sim_id_stores_full_location_url(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        poll_resp = _make_httpx_response(200, {"status": "DONE", "alpha": ALPHA_URL})
        metrics_resp = _make_httpx_response(200, METRICS_RESPONSE)

        orm = _make_alpha_orm(test_db, expression="-zscore(ts_mean(volume,10))")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_resp]
            mock_instance.get.side_effect = [poll_resp, metrics_resp]

            sim_id = await client.submit(alpha, test_db)

        sim = test_db.get(Simulation, int(sim_id))
        assert sim.wq_sim_id == LOCATION_URL

    async def test_polling_terminates_on_done(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        # First poll returns RUNNING, second returns DONE
        poll_running = _make_httpx_response(200, {"status": "RUNNING"})
        poll_done = _make_httpx_response(200, {"status": "DONE", "alpha": ALPHA_URL})
        metrics_resp = _make_httpx_response(200, METRICS_RESPONSE)

        orm = _make_alpha_orm(test_db, expression="rank(close/open)")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_resp]
            mock_instance.get.side_effect = [poll_running, poll_done, metrics_resp]

            sim_id = await client.submit(alpha, test_db)

        sim = test_db.get(Simulation, int(sim_id))
        assert sim.status == "completed"
        assert sim.sharpe == pytest.approx(1.43)
        assert sim.fitness == pytest.approx(1.12)

    @pytest.mark.parametrize("wq_status", ["ERROR", "CANCELLED", "FAILED"])
    async def test_terminal_failure_status_raises_simulation_failed(self, test_db, wq_status):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        poll_resp = _make_httpx_response(200, {"status": wq_status})

        orm = _make_alpha_orm(test_db, expression=f"rank(ts_delta(close,3))-{wq_status.lower()}")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_resp]
            mock_instance.get.return_value = poll_resp

            with pytest.raises(SimulationFailed) as exc:
                await client.submit(alpha, test_db)

        assert exc.value.wq_status == wq_status
        # DB row should be marked failed
        sim = test_db.query(Simulation).filter(Simulation.alpha_id == alpha.id).first()
        assert sim.status == "failed"

    async def test_simulation_timeout_raises(self, test_db):
        # poll_timeout=1.0, poll_interval=0.01 → ~100 polls before timeout
        # Make all polls return RUNNING
        client = AutoAPIClient(
            email="test@example.com",
            password="secret",
            poll_interval=0.01,
            poll_timeout=0.05,  # extremely short timeout for test
        )
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_resp = _make_httpx_response(201, {}, headers={"Location": LOCATION_URL})
        poll_running = _make_httpx_response(200, {"status": "RUNNING"})

        orm = _make_alpha_orm(test_db, expression="-rank(close-open)")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_resp]
            mock_instance.get.return_value = poll_running

            with pytest.raises(SimulationTimeout):
                await client.submit(alpha, test_db)

        # DB row remains "submitted" (not failed)
        sim = test_db.query(Simulation).filter(Simulation.alpha_id == alpha.id).first()
        assert sim.status == "submitted"

    async def test_non_2xx_submit_sets_failed_row(self, test_db):
        client = _make_auto_client()
        login_resp = _make_httpx_response(200, {"message": "OK"})
        submit_error = _make_httpx_response(400, {"error": "bad request"})

        orm = _make_alpha_orm(test_db, expression="rank(ts_std(close,5))")
        alpha = _orm_to_candidate(orm)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post.side_effect = [login_resp, submit_error]

            with pytest.raises(Exception):
                await client.submit(alpha, test_db)

        sim = test_db.query(Simulation).filter(Simulation.alpha_id == alpha.id).first()
        assert sim.status == "failed"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/services/test_wq_interface.py::TestAutoAPIClient -v
```

Expected: `ERROR` — `ImportError: cannot import name 'AutoAPIClient'`

- [ ] **Step 3: Implement AutoAPIClient**

Append to `backend/services/wq_interface.py`:

```python
# ── AutoAPIClient ────────────────────────────────────────────────────────────

class AutoAPIClient(WQBrainInterface):
    """Submits alphas to WQ Brain via the unofficial API; blocks until complete."""

    def __init__(
        self,
        email: str,
        password: str,
        poll_interval: float = 5.0,
        poll_timeout: float = 300.0,
    ) -> None:
        self._email = email
        self._password = password
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:  # noqa: C901
        async with httpx.AsyncClient() as client:
            # 1. Authenticate
            await self._login(client)

            # 2. Submit simulation
            body = {
                "type": "REGULAR",
                "settings": {
                    "instrumentType": "EQUITY",
                    "region": alpha.region,
                    "universe": alpha.universe,
                    "delay": alpha.delay,
                    "decay": alpha.decay,
                    "neutralization": alpha.neutralization.upper(),
                    "truncation": alpha.truncation,
                    "pasteurization": alpha.pasteurization.upper(),
                    "nanHandling": alpha.nan_handling.upper(),
                    "language": "FASTEXPR",
                    "visualization": False,
                },
                "regular": alpha.expression,
            }
            resp = await client.post(WQ_SIMULATIONS_URL, json=body)

            if not resp.is_success:
                sim = Simulation(
                    alpha_id=alpha.id,
                    status="failed",
                    submitted_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(sim)
                db.commit()
                raise RuntimeError(f"WQ Brain submit failed: HTTP {resp.status_code}")

            location_url: str = resp.headers.get("Location", "")

            # 3. Create simulation row
            sim = Simulation(
                alpha_id=alpha.id,
                status="submitted",
                wq_sim_id=location_url,
                submitted_at=datetime.now(timezone.utc),
            )
            db.add(sim)
            db.commit()
            db.refresh(sim)

            # 4. Poll until done or timeout
            elapsed = 0.0
            poll_data: dict = {}
            while elapsed < self._poll_timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                poll_resp = await client.get(location_url)
                poll_data = poll_resp.json()
                status = poll_data.get("status", "")
                if status in WQ_DONE_STATUSES:
                    break
                if status in WQ_FAILED_STATUSES:
                    sim.status = "failed"
                    sim.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    raise SimulationFailed(status)
            else:
                raise SimulationTimeout(
                    f"Simulation did not complete within {self._poll_timeout}s"
                )

            # 5. Fetch metrics
            alpha_link: str = poll_data.get("alpha", "")
            if not alpha_link.startswith("http"):
                alpha_link = WQ_ALPHAS_URL.format(alpha_id=alpha_link)
            metrics_resp = await client.get(alpha_link)
            metrics = metrics_resp.json()

            is_data: dict = metrics.get("is", {})
            checks = is_data.get("checks", [])
            passed: bool | None = None
            if checks:
                passed = all(c.get("result") == "PASS" for c in checks)

            # 6. Update simulation row
            sim.status = "completed"
            sim.sharpe = is_data.get("sharpe")
            sim.fitness = is_data.get("fitness")
            sim.returns = is_data.get("returns")
            sim.turnover = is_data.get("turnover")
            sim.passed = passed
            sim.completed_at = datetime.now(timezone.utc)
            db.commit()

            return str(sim.id)

    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        sim = db.get(Simulation, int(simulation_id))
        if sim is None:
            return None
        return SimulationRead.model_validate(sim)

    @staticmethod
    async def _login(client: httpx.AsyncClient) -> None:
        """Authenticate with WQ Brain. Raises BiometricAuthRequired if 2FA needed."""
        # Note: credentials are passed via the client's auth parameter at call site.
        # This method is called from submit() which has access to self._email/_password.
        # We restructure to pass auth here for testability.
        raise NotImplementedError("Use _login_with_credentials instead")

    async def _login_with_credentials(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(WQ_AUTH_URL, auth=(self._email, self._password))
        data = resp.json() if resp.content else {}
        if "inquiryId" in data:
            url = data.get("message") or f"https://platform.worldquantbrain.com/?inquiryId={data['inquiryId']}"
            raise BiometricAuthRequired(url)
```

Wait — the `_login` method above has a design flaw. Let me revise: remove the `_login` static method and inline `_login_with_credentials` call directly in `submit()`. Rewrite `submit()` to call `self._login_with_credentials(client)` instead of `self._login(client)`.

**Correct implementation** — replace the `AutoAPIClient` class in `wq_interface.py` with:

```python
# ── AutoAPIClient ────────────────────────────────────────────────────────────

class AutoAPIClient(WQBrainInterface):
    """Submits alphas to WQ Brain via the unofficial API; blocks until complete."""

    def __init__(
        self,
        email: str,
        password: str,
        poll_interval: float = 5.0,
        poll_timeout: float = 300.0,
    ) -> None:
        self._email = email
        self._password = password
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def _login(self, client: httpx.AsyncClient) -> None:
        """POST /authentication with HTTP Basic auth. Raises BiometricAuthRequired if 2FA needed."""
        resp = await client.post(WQ_AUTH_URL, auth=(self._email, self._password))
        data = resp.json() if resp.content else {}
        if "inquiryId" in data:
            url = (
                data.get("message")
                or f"https://platform.worldquantbrain.com/?inquiryId={data['inquiryId']}"
            )
            raise BiometricAuthRequired(url)

    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        async with httpx.AsyncClient() as client:
            # 1. Authenticate
            await self._login(client)

            # 2. Submit simulation
            body = {
                "type": "REGULAR",
                "settings": {
                    "instrumentType": "EQUITY",
                    "region": alpha.region,
                    "universe": alpha.universe,
                    "delay": alpha.delay,
                    "decay": alpha.decay,
                    "neutralization": alpha.neutralization.upper(),
                    "truncation": alpha.truncation,
                    "pasteurization": alpha.pasteurization.upper(),
                    "nanHandling": alpha.nan_handling.upper(),
                    "language": "FASTEXPR",
                    "visualization": False,
                },
                "regular": alpha.expression,
            }
            resp = await client.post(WQ_SIMULATIONS_URL, json=body)

            if not resp.is_success:
                sim = Simulation(
                    alpha_id=alpha.id,
                    status="failed",
                    submitted_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(sim)
                db.commit()
                raise RuntimeError(f"WQ Brain submit failed: HTTP {resp.status_code}")

            location_url: str = resp.headers.get("Location", "")

            # 3. Create simulation row (status=submitted)
            sim = Simulation(
                alpha_id=alpha.id,
                status="submitted",
                wq_sim_id=location_url,
                submitted_at=datetime.now(timezone.utc),
            )
            db.add(sim)
            db.commit()
            db.refresh(sim)

            # 4. Poll until done or timeout
            elapsed = 0.0
            poll_data: dict = {}
            while elapsed < self._poll_timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                poll_resp = await client.get(location_url)
                poll_data = poll_resp.json()
                wq_status = poll_data.get("status", "")
                if wq_status in WQ_DONE_STATUSES:
                    break
                if wq_status in WQ_FAILED_STATUSES:
                    sim.status = "failed"
                    sim.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    raise SimulationFailed(wq_status)
            else:
                raise SimulationTimeout(
                    f"Simulation did not complete within {self._poll_timeout}s"
                )

            # 5. Fetch alpha metrics
            alpha_link: str = poll_data.get("alpha", "")
            if not alpha_link.startswith("http"):
                alpha_link = WQ_ALPHAS_URL.format(alpha_id=alpha_link)
            metrics_resp = await client.get(alpha_link)
            metrics = metrics_resp.json()

            is_data: dict = metrics.get("is", {})
            checks = is_data.get("checks", [])
            passed: bool | None = (
                all(c.get("result") == "PASS" for c in checks) if checks else None
            )

            # 6. Mark complete and persist metrics
            sim.status = "completed"
            sim.sharpe = is_data.get("sharpe")
            sim.fitness = is_data.get("fitness")
            sim.returns = is_data.get("returns")
            sim.turnover = is_data.get("turnover")
            sim.passed = passed
            sim.completed_at = datetime.now(timezone.utc)
            db.commit()

            return str(sim.id)

    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        sim = db.get(Simulation, int(simulation_id))
        if sim is None:
            return None
        return SimulationRead.model_validate(sim)
```

- [ ] **Step 4: Fix test mocking pattern**

The tests above use `patch("httpx.AsyncClient")` but `AutoAPIClient.submit()` uses `async with httpx.AsyncClient() as client`. The mock must handle the `__aenter__`/`__aexit__` context manager protocol. The `_make_httpx_response` and `patch` pattern already accounts for this with `MockClient.return_value.__aenter__.return_value = mock_instance`.

However, the `_login` method is now an instance method that takes `client` as a parameter. The tests mock `client.post` directly, which is correct.

One issue: `test_biometric_auth_raises` and `test_non_2xx_submit_sets_failed_row` mock `client.post.side_effect` but login is `client.post` call 1 and submit is call 2. The side_effect list handles this correctly.

- [ ] **Step 5: Run all AutoAPIClient tests**

```bash
uv run pytest tests/services/test_wq_interface.py::TestAutoAPIClient -v
```

Expected: all 8 tests pass (9 total in class; 1 is parametrized with 3 values = 10 pass)

- [ ] **Step 6: Run all service tests**

```bash
uv run pytest tests/services/ -v
```

Expected: all 16 tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/services/wq_interface.py tests/services/test_wq_interface.py
git commit -m "feat: implement AutoAPIClient with async httpx and TDD"
```

---

## Task 6: Submit API endpoints (TDD)

**Files:**
- Create: `tests/api/test_submit.py`
- Implement: `backend/api/submit.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/api/test_submit.py`:

```python
"""Integration tests for /api/submit/* endpoints."""
import pytest
from unittest.mock import AsyncMock, patch
from backend.core.models import AlphaSource, compute_alpha_id
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation


# ── Helpers ──────────────────────────────────────────────────────────────────

def _insert_alpha(client, expression="-rank(ts_delta(close,5))"):
    """Insert an alpha via the API and return the response JSON."""
    r = client.post("/api/alphas", json={"expression": expression, "source": "seed"})
    assert r.status_code in (200, 201)
    return r.json()


def _insert_alpha_with_pending_sim(client, expression="-rank(ts_delta(close,5))"):
    """Insert alpha and enqueue it for manual submission."""
    alpha = _insert_alpha(client, expression)
    r = client.post("/api/submit/queue", json={"alpha_id": alpha["id"]})
    assert r.status_code == 201
    return alpha, r.json()


# ── POST /submit/queue ────────────────────────────────────────────────────────

class TestEnqueueAlpha:
    def test_enqueue_creates_pending_simulation(self, client):
        alpha = _insert_alpha(client)
        r = client.post("/api/submit/queue", json={"alpha_id": alpha["id"]})
        assert r.status_code == 201
        data = r.json()
        assert data["alpha_id"] == alpha["id"]
        assert data["status"] == "pending"
        assert data["submitted_at"] is not None

    def test_enqueue_unknown_alpha_returns_404(self, client):
        r = client.post("/api/submit/queue", json={"alpha_id": "nonexistent"})
        assert r.status_code == 404

    def test_enqueue_duplicate_returns_409(self, client):
        alpha = _insert_alpha(client)
        client.post("/api/submit/queue", json={"alpha_id": alpha["id"]})
        r = client.post("/api/submit/queue", json={"alpha_id": alpha["id"]})
        assert r.status_code == 409


# ── GET /submit/queue ─────────────────────────────────────────────────────────

class TestGetQueue:
    def test_get_queue_returns_all_simulations(self, client):
        _insert_alpha_with_pending_sim(client, "-rank(ts_delta(close,5))")
        _insert_alpha_with_pending_sim(client, "rank(ts_mean(close,10))")
        r = client.get("/api/submit/queue")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_get_queue_filters_by_status(self, client):
        alpha, sim = _insert_alpha_with_pending_sim(client)
        r = client.get("/api/submit/queue?status=pending")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "pending"

    def test_get_queue_empty(self, client):
        r = client.get("/api/submit/queue")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_queue_status_filter_no_match(self, client):
        _insert_alpha_with_pending_sim(client)
        r = client.get("/api/submit/queue?status=completed")
        assert r.status_code == 200
        assert r.json() == []


# ── GET /submit/export ────────────────────────────────────────────────────────

class TestExportQueue:
    def test_export_json_format(self, client):
        _insert_alpha_with_pending_sim(client)
        r = client.get("/api/submit/export")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert "alpha_id" in data[0]
        assert "expression" in data[0]
        assert "settings" in data[0]
        s = data[0]["settings"]
        assert "region" in s
        assert "universe" in s
        assert "delay" in s

    def test_export_csv_format(self, client):
        _insert_alpha_with_pending_sim(client)
        r = client.get("/api/submit/export?format=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        lines = r.text.strip().splitlines()
        assert len(lines) == 2  # header + 1 row
        assert "alpha_id" in lines[0]

    def test_export_empty_returns_empty_list(self, client):
        r = client.get("/api/submit/export")
        assert r.status_code == 200
        assert r.json() == []

    def test_export_empty_csv_returns_header_only(self, client):
        r = client.get("/api/submit/export?format=csv")
        assert r.status_code == 200
        lines = [l for l in r.text.strip().splitlines() if l]
        assert len(lines) == 1
        assert "alpha_id" in lines[0]


# ── POST /submit/result ───────────────────────────────────────────────────────

class TestImportResult:
    def _result_body(self, alpha_id, **kwargs):
        return {
            "alpha_id": alpha_id,
            "sharpe": 1.43,
            "fitness": 1.12,
            "returns": 0.087,
            "turnover": 0.61,
            "passed": True,
            **kwargs,
        }

    def test_import_result_updates_simulation(self, client):
        alpha, sim = _insert_alpha_with_pending_sim(client)
        r = client.post("/api/submit/result", json=self._result_body(alpha["id"]))
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["sharpe"] == pytest.approx(1.43)
        assert data["fitness"] == pytest.approx(1.12)
        assert data["passed"] is True
        assert data["completed_at"] is not None

    def test_import_result_with_simulation_id(self, client):
        alpha, sim = _insert_alpha_with_pending_sim(client)
        body = self._result_body(alpha["id"])
        body["simulation_id"] = sim["id"]
        r = client.post("/api/submit/result", json=body)
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_import_result_unknown_alpha_returns_404(self, client):
        r = client.post("/api/submit/result", json=self._result_body("nonexistent"))
        assert r.status_code == 404

    def test_import_result_twice_returns_409(self, client):
        alpha, sim = _insert_alpha_with_pending_sim(client)
        body = self._result_body(alpha["id"])
        client.post("/api/submit/result", json=body)
        r = client.post("/api/submit/result", json=body)
        assert r.status_code == 409

    def test_import_result_for_failed_sim_succeeds(self, client, test_db):
        """Re-importing a result for a failed simulation should be allowed."""
        alpha = _insert_alpha(client)
        # Manually insert a failed simulation row
        sim = Simulation(alpha_id=alpha["id"], status="failed")
        test_db.add(sim)
        test_db.commit()
        test_db.refresh(sim)
        body = self._result_body(alpha["id"])
        body["simulation_id"] = sim.id
        r = client.post("/api/submit/result", json=body)
        assert r.status_code == 200
        assert r.json()["status"] == "completed"


# ── POST /submit/auto/{alpha_id} ──────────────────────────────────────────────

class TestAutoSubmit:
    def _mock_auto_client(self, sim_id: str):
        """Return an AsyncMock for AutoAPIClient.submit that returns sim_id."""
        mock = AsyncMock(return_value=sim_id)
        return mock

    def test_auto_submit_returns_simulation_read(self, client, test_db):
        alpha = _insert_alpha(client)
        # Pre-create completed simulation so we can return its id
        sim = Simulation(alpha_id=alpha["id"], status="completed", sharpe=1.5, fitness=1.2,
                         returns=0.09, turnover=0.5, passed=True)
        test_db.add(sim)
        test_db.commit()
        test_db.refresh(sim)

        with patch("backend.api.submit.AutoAPIClient") as MockCls:
            mock_instance = MockCls.return_value
            mock_instance.submit = AsyncMock(return_value=str(sim.id))
            r = client.post(f"/api/submit/auto/{alpha['id']}")

        assert r.status_code == 200
        data = r.json()
        assert data["alpha_id"] == alpha["id"]
        assert data["status"] == "completed"

    def test_auto_submit_unknown_alpha_returns_404(self, client):
        r = client.post("/api/submit/auto/nonexistent")
        assert r.status_code == 404

    def test_auto_submit_when_submitted_row_exists_returns_409(self, client, test_db):
        alpha = _insert_alpha(client)
        sim = Simulation(alpha_id=alpha["id"], status="submitted")
        test_db.add(sim)
        test_db.commit()
        r = client.post(f"/api/submit/auto/{alpha['id']}")
        assert r.status_code == 409

    def test_auto_submit_biometric_returns_503(self, client):
        from backend.services.wq_interface import BiometricAuthRequired
        alpha = _insert_alpha(client, expression="rank(ts_std(close,20))")

        with patch("backend.api.submit.AutoAPIClient") as MockCls:
            mock_instance = MockCls.return_value
            mock_instance.submit = AsyncMock(
                side_effect=BiometricAuthRequired("https://platform.worldquantbrain.com/?inquiryId=abc")
            )
            r = client.post(f"/api/submit/auto/{alpha['id']}")

        assert r.status_code == 503
        assert "Biometric" in r.json()["detail"]

    def test_auto_submit_timeout_returns_504(self, client):
        from backend.services.wq_interface import SimulationTimeout
        alpha = _insert_alpha(client, expression="-rank(ts_mean(volume,5))")

        with patch("backend.api.submit.AutoAPIClient") as MockCls:
            mock_instance = MockCls.return_value
            mock_instance.submit = AsyncMock(side_effect=SimulationTimeout("timed out"))
            r = client.post(f"/api/submit/auto/{alpha['id']}")

        assert r.status_code == 504
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/api/test_submit.py -v 2>&1 | head -30
```

Expected: tests fail because submit.py is still a stub

- [ ] **Step 3: Implement submit.py**

Replace `backend/api/submit.py`:

```python
"""Submit queue API — manual export, result import, and auto-submission."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.models import AlphaCandidate, AlphaSource
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.schemas.simulation import EnqueueRequest, ResultImportRequest, SimulationRead
from backend.services.wq_interface import (
    AutoAPIClient,
    BiometricAuthRequired,
    ManualQueueClient,
    SimulationFailed,
    SimulationTimeout,
)

router = APIRouter(tags=["submit"])
_manual_client = ManualQueueClient()


def _get_auto_client() -> AutoAPIClient:
    s = get_settings()
    return AutoAPIClient(
        email=s.WQ_EMAIL,
        password=s.WQ_PASSWORD,
        poll_interval=s.WQ_POLL_INTERVAL_SEC,
        poll_timeout=s.WQ_POLL_TIMEOUT_SEC,
    )


def _orm_to_candidate(orm: Alpha) -> AlphaCandidate:
    return AlphaCandidate(
        id=orm.id, expression=orm.expression, universe=orm.universe,
        region=orm.region, delay=orm.delay, decay=orm.decay,
        neutralization=orm.neutralization, truncation=orm.truncation,
        pasteurization=orm.pasteurization, nan_handling=orm.nan_handling,
        source=AlphaSource(orm.source), parent_id=orm.parent_id,
        rationale=orm.rationale, created_at=orm.created_at,
        filter_skipped=orm.filter_skipped,
    )


# ── Enqueue alpha for manual submission ──────────────────────────────────────

@router.post("/submit/queue", response_model=SimulationRead, status_code=201)
async def enqueue_alpha(body: EnqueueRequest, db: Session = Depends(get_db)):
    alpha_orm = db.get(Alpha, body.alpha_id)
    if alpha_orm is None:
        raise HTTPException(status_code=404, detail="Alpha not found")

    existing = (
        db.query(Simulation)
        .filter(Simulation.alpha_id == body.alpha_id, Simulation.status == "pending")
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A pending simulation already exists for this alpha")

    alpha = _orm_to_candidate(alpha_orm)
    sim_id = await _manual_client.submit(alpha, db)
    sim = db.get(Simulation, int(sim_id))
    return SimulationRead.model_validate(sim)


# ── List simulation queue ─────────────────────────────────────────────────────

@router.get("/submit/queue", response_model=list[SimulationRead])
def get_queue(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Simulation)
    if status:
        q = q.filter(Simulation.status == status)
    return q.order_by(Simulation.submitted_at.desc()).all()


# ── Export pending alphas ─────────────────────────────────────────────────────

@router.get("/submit/export")
def export_queue(format: str = "json", db: Session = Depends(get_db)):
    if format == "csv":
        csv_data = _manual_client.export_pending(db, format="csv")
        return Response(content=csv_data, media_type="text/csv")
    return _manual_client.export_pending(db, format="json")


# ── Import manual result ──────────────────────────────────────────────────────

@router.post("/submit/result", response_model=SimulationRead)
def import_result(body: ResultImportRequest, db: Session = Depends(get_db)):
    if body.simulation_id is not None:
        sim = db.get(Simulation, body.simulation_id)
    else:
        sim = (
            db.query(Simulation)
            .filter(Simulation.alpha_id == body.alpha_id)
            .filter(Simulation.status == "pending")
            .order_by(Simulation.submitted_at.desc())
            .first()
        )

    if sim is None:
        raise HTTPException(status_code=404, detail="No matching simulation found")
    if sim.status == "completed":
        raise HTTPException(status_code=409, detail="Simulation already completed")

    sim.sharpe = body.sharpe
    sim.fitness = body.fitness
    sim.returns = body.returns
    sim.turnover = body.turnover
    sim.passed = body.passed
    sim.notes = body.notes
    sim.status = "completed"
    sim.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sim)
    return SimulationRead.model_validate(sim)


# ── Auto-submit via WQ Brain API ──────────────────────────────────────────────

@router.post("/submit/auto/{alpha_id}", response_model=SimulationRead)
async def auto_submit(alpha_id: str, db: Session = Depends(get_db)):
    alpha_orm = db.get(Alpha, alpha_id)
    if alpha_orm is None:
        raise HTTPException(status_code=404, detail="Alpha not found")

    existing = (
        db.query(Simulation)
        .filter(Simulation.alpha_id == alpha_id, Simulation.status == "submitted")
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A submitted simulation already exists for this alpha")

    alpha = _orm_to_candidate(alpha_orm)
    auto_client = _get_auto_client()

    try:
        sim_id = await auto_client.submit(alpha, db)
    except BiometricAuthRequired as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except SimulationTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except SimulationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    sim = db.get(Simulation, int(sim_id))
    return SimulationRead.model_validate(sim)
```

- [ ] **Step 4: Run API tests**

```bash
uv run pytest tests/api/test_submit.py -v
```

Expected: all tests pass

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass (including Phase 1 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/api/submit.py tests/api/test_submit.py
git commit -m "feat: implement submit API endpoints with TDD (Phase 2 complete)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Start the API server**

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

- [ ] **Step 2: Smoke test the endpoints**

```bash
# Verify all submit endpoints are registered (not 501)
curl -s http://localhost:8000/api/submit/queue | python -m json.tool
curl -s http://localhost:8000/api/submit/export | python -m json.tool
```

Expected: `[]` for both (empty queue), not `{"detail": "Not implemented"}`

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest -v --tb=short
```

Expected: all tests pass, no failures

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: Phase 2 complete — WQ Brain interface, manual queue, auto-submit"
```
