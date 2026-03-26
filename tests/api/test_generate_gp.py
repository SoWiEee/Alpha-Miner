"""Tests for POST /generate/gp (Phase 5 GP generation endpoint)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from backend.core.models import AlphaCandidate, AlphaSource
from backend.models.alpha import Alpha
from backend.models.correlation import ProxyPrice, Run


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_proxy_data(db):
    """Insert minimal proxy price rows so get_panel() returns non-empty."""
    for t in ["AAPL", "MSFT"]:
        for d in [
            "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"
        ]:
            db.add(
                ProxyPrice(
                    ticker=t,
                    date=d,
                    open=100.0,
                    high=105.0,
                    low=98.0,
                    close=102.0,
                    adj_close=102.0,
                    volume=1000000,
                )
            )
    db.commit()


def _fake_candidates():
    return [
        AlphaCandidate.create(
            expression="rank(close)",
            source=AlphaSource.GP,
            rationale="GP IC=0.050 gen=2",
        ),
        AlphaCandidate.create(
            expression="rank(volume)",
            source=AlphaSource.GP,
            rationale="GP IC=0.040 gen=2",
        ),
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_gp_returns_503_when_no_proxy_data(client):
    """503 when panel is empty (no proxy data in DB)."""
    r = client.post("/api/generate/gp", json={})
    assert r.status_code == 503


def test_gp_returns_202_with_run_id(client, test_db, test_engine):
    """202 Accepted with run_id and status='running' when proxy data present."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.return_value = _fake_candidates()
        r = client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    assert r.status_code == 202
    data = r.json()
    assert "run_id" in data
    assert isinstance(data["run_id"], int)
    assert data["status"] == "running"
    assert "message" in data


def test_gp_background_task_sets_finished_at(client, test_db, test_engine):
    """After background task (sync in TestClient), Run row has finished_at set."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.return_value = _fake_candidates()
        r = client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    assert r.status_code == 202
    run_id = r.json()["run_id"]

    # TestClient runs BackgroundTasks synchronously — finished_at should be set
    run = test_db.get(Run, run_id)
    test_db.refresh(run)
    assert run is not None
    assert run.finished_at is not None
    assert run.mode == "gp"


def test_gp_background_saves_candidates(client, test_db, test_engine):
    """After background task, GP candidates appear in DB with source='gp'."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.return_value = _fake_candidates()
        r = client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    assert r.status_code == 202

    # Refresh session to pick up changes committed by background task
    test_db.expire_all()
    gp_alphas = test_db.query(Alpha).filter(Alpha.source == "gp").all()
    assert len(gp_alphas) > 0


def test_gp_candidates_appear_in_alphas_endpoint(client, test_db, test_engine):
    """GET /api/alphas shows GP candidates with source='gp'."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.return_value = _fake_candidates()
        client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    r = client.get("/api/alphas?source=gp")
    assert r.status_code == 200
    alphas = r.json()
    assert len(alphas) > 0
    for a in alphas:
        assert a["source"] == "gp"


def test_gp_run_appears_in_generate_runs(client, test_db, test_engine):
    """GET /generate/runs returns the GP run with mode='gp'."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.return_value = _fake_candidates()
        client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    r = client.get("/api/generate/runs")
    assert r.status_code == 200
    runs = r.json()
    gp_runs = [run for run in runs if run["mode"] == "gp"]
    assert len(gp_runs) >= 1


def test_gp_n_results_passed_to_searcher(client, test_db, test_engine):
    """n_results=5 in request body is forwarded to GPSearcher.run."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_inst = mock_gp_cls.return_value
        mock_inst.run.return_value = []
        client.post("/api/generate/gp", json={"n_results": 5, "generations": 2})

    # run() should have been called with n_results=5
    call_args = mock_inst.run.call_args
    assert call_args is not None
    # n_results is the second positional arg (panel, n_results, pop_size, gens)
    assert call_args[0][1] == 5


def test_gp_graceful_failure_sets_finished_at(client, test_db, test_engine):
    """If GPSearcher.run raises, Run still gets finished_at (graceful failure)."""
    _insert_proxy_data(test_db)
    TestSession = sessionmaker(bind=test_engine)

    with patch("backend.api.generate.GPSearcher") as mock_gp_cls, \
         patch("backend.api.generate._gp_db_factory", new=lambda: TestSession()):
        mock_gp_cls.return_value.run.side_effect = RuntimeError("GP exploded")
        r = client.post("/api/generate/gp", json={"n_results": 2, "generations": 2})

    assert r.status_code == 202
    run_id = r.json()["run_id"]

    test_db.expire_all()
    run = test_db.get(Run, run_id)
    test_db.refresh(run)
    assert run is not None
    assert run.finished_at is not None
