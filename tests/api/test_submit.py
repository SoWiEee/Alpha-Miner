"""Integration tests for /api/submit/* endpoints."""
import pytest
from unittest.mock import AsyncMock, patch
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
        _insert_alpha_with_pending_sim(client)
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
        """Re-importing a result for a failed simulation row is allowed."""
        alpha = _insert_alpha(client)
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
    def test_auto_submit_returns_simulation_read(self, client, test_db):
        alpha = _insert_alpha(client)
        sim = Simulation(alpha_id=alpha["id"], status="completed", sharpe=1.5,
                         fitness=1.2, returns=0.09, turnover=0.5, passed=True)
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
