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


from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.wq_interface import AutoAPIClient, BiometricAuthRequired, SimulationFailed, SimulationTimeout


def _make_httpx_response(status_code: int, json_data: dict, headers: dict = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    resp.is_success = 200 <= status_code < 300
    resp.content = b"x"  # non-empty so json() is called
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
    async def test_login_success_and_submit_completes(self, test_db):
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
        assert sim.sharpe == pytest.approx(1.43)
        assert sim.fitness == pytest.approx(1.12)

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

        orm = _make_alpha_orm(test_db, expression="rank(ts_mean(close,20))")
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

    @pytest.mark.parametrize("wq_status", ["ERROR", "CANCELLED", "FAILED"])
    async def test_terminal_failure_status_raises(self, test_db, wq_status):
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
        sim = test_db.query(Simulation).filter(Simulation.alpha_id == alpha.id).first()
        assert sim.status == "failed"

    async def test_simulation_timeout_raises(self, test_db):
        client = AutoAPIClient(
            email="test@example.com",
            password="secret",
            poll_interval=0.01,
            poll_timeout=0.05,  # extremely short for test
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
