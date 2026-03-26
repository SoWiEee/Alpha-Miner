"""Integration tests for /api/pool/* endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.models.alpha import Alpha
from backend.models.correlation import PoolCorrelation, ProxyPrice
from backend.models.simulation import Simulation
from backend.core.models import compute_alpha_id


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_alpha(expression: str, source: str = "seed") -> Alpha:
    alpha_id = compute_alpha_id(
        expression, "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off"
    )
    return Alpha(
        id=alpha_id,
        expression=expression,
        source=source,
        universe="TOP3000",
        region="USA",
        delay=1,
        decay=0,
        neutralization="subindustry",
        truncation=0.08,
        pasteurization="off",
        nan_handling="off",
        filter_skipped=False,
    )


def _make_sim(alpha_id: str, sharpe=1.0, fitness=0.8, returns=0.05,
              turnover=0.5, passed=True, status="completed") -> Simulation:
    return Simulation(
        alpha_id=alpha_id,
        sharpe=sharpe,
        fitness=fitness,
        returns=returns,
        turnover=turnover,
        passed=passed,
        status=status,
    )


# ── GET /pool/status ──────────────────────────────────────────────────────────

class TestPoolStatus:
    def test_empty_db_returns_zeroes_and_nones(self, client):
        r = client.get("/api/pool/status")
        assert r.status_code == 200
        data = r.json()
        assert data["pool_size"] == 0
        assert data["avg_sharpe"] is None
        assert data["avg_fitness"] is None
        assert data["max_correlation"] is None
        assert data["min_correlation"] is None

    def test_correct_stats_with_completed_simulations(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()

        s1 = _make_sim(a1.id, sharpe=1.2, fitness=0.9)
        s2 = _make_sim(a2.id, sharpe=1.8, fitness=1.1)
        test_db.add(s1)
        test_db.add(s2)
        test_db.commit()

        r = client.get("/api/pool/status")
        assert r.status_code == 200
        data = r.json()
        assert data["pool_size"] == 2
        assert data["avg_sharpe"] == pytest.approx(1.5)
        assert data["avg_fitness"] == pytest.approx(1.0)
        assert data["max_correlation"] is None  # no correlations yet
        assert data["min_correlation"] is None

    def test_pool_size_deduplicates_alpha_ids(self, client, test_db):
        """Same alpha with two completed simulations counts as pool_size=1."""
        a1 = _make_alpha("rank(close)")
        test_db.add(a1)
        test_db.flush()

        s1 = _make_sim(a1.id, sharpe=1.0, fitness=0.8)
        s2 = _make_sim(a1.id, sharpe=1.2, fitness=0.9)
        test_db.add(s1)
        test_db.add(s2)
        test_db.commit()

        r = client.get("/api/pool/status")
        assert r.json()["pool_size"] == 1

    def test_correlation_stats_when_correlations_exist(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()

        corr = PoolCorrelation(
            alpha_a=a1.id,
            alpha_b=a2.id,
            correlation=0.65,
            computed_at=datetime.now(timezone.utc),
        )
        test_db.add(corr)
        test_db.commit()

        r = client.get("/api/pool/status")
        data = r.json()
        assert data["max_correlation"] == pytest.approx(0.65)
        assert data["min_correlation"] == pytest.approx(0.65)

    def test_non_completed_sims_excluded_from_pool_size(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        test_db.add(a1)
        test_db.flush()

        s1 = _make_sim(a1.id, status="pending")
        test_db.add(s1)
        test_db.commit()

        r = client.get("/api/pool/status")
        assert r.json()["pool_size"] == 0


# ── GET /pool/correlations ────────────────────────────────────────────────────

class TestPoolCorrelations:
    def test_empty_returns_empty_list(self, client):
        r = client.get("/api/pool/correlations")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_stored_correlations(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()

        corr = PoolCorrelation(
            alpha_a=a1.id,
            alpha_b=a2.id,
            correlation=0.55,
            computed_at=datetime.now(timezone.utc),
        )
        test_db.add(corr)
        test_db.commit()

        r = client.get("/api/pool/correlations")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["alpha_a"] == a1.id
        assert data[0]["alpha_b"] == a2.id
        assert data[0]["correlation"] == pytest.approx(0.55)

    def test_ordered_by_correlation_desc(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        a3 = _make_alpha("rank(volume)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.add(a3)
        test_db.flush()

        # Use sorted IDs for composite PK (alpha_a < alpha_b)
        ids = sorted([a1.id, a2.id, a3.id])
        c1 = PoolCorrelation(alpha_a=ids[0], alpha_b=ids[1], correlation=0.3,
                             computed_at=datetime.now(timezone.utc))
        c2 = PoolCorrelation(alpha_a=ids[0], alpha_b=ids[2], correlation=0.8,
                             computed_at=datetime.now(timezone.utc))
        test_db.add(c1)
        test_db.add(c2)
        test_db.commit()

        r = client.get("/api/pool/correlations")
        data = r.json()
        assert len(data) == 2
        assert data[0]["correlation"] > data[1]["correlation"]


# ── GET /pool/top ─────────────────────────────────────────────────────────────

class TestPoolTop:
    def test_empty_returns_empty_list(self, client):
        r = client.get("/api/pool/top")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_entries_ordered_by_fitness(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        a3 = _make_alpha("rank(volume)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.add(a3)
        test_db.flush()

        s1 = _make_sim(a1.id, fitness=0.5)
        s2 = _make_sim(a2.id, fitness=1.5)
        s3 = _make_sim(a3.id, fitness=1.0)
        test_db.add(s1)
        test_db.add(s2)
        test_db.add(s3)
        test_db.commit()

        r = client.get("/api/pool/top")
        data = r.json()
        assert len(data) == 3
        # First entry should have highest fitness
        assert data[0]["fitness"] == pytest.approx(1.5)
        assert data[1]["fitness"] == pytest.approx(1.0)
        assert data[2]["fitness"] == pytest.approx(0.5)

    def test_n_parameter_limits_results(self, client, test_db):
        for i in range(5):
            a = _make_alpha(f"rank(close) * {i + 1}.0")
            test_db.add(a)
            test_db.flush()
            s = _make_sim(a.id, fitness=float(i))
            test_db.add(s)
        test_db.commit()

        r = client.get("/api/pool/top?n=2")
        data = r.json()
        assert len(data) <= 2

    def test_deduplicates_by_alpha_id(self, client, test_db):
        """Multiple simulations for same alpha → only one entry in top."""
        a1 = _make_alpha("rank(close)")
        test_db.add(a1)
        test_db.flush()

        s1 = _make_sim(a1.id, fitness=0.5)
        s2 = _make_sim(a1.id, fitness=1.5)
        test_db.add(s1)
        test_db.add(s2)
        test_db.commit()

        r = client.get("/api/pool/top")
        data = r.json()
        assert len(data) == 1
        # Should pick the highest fitness
        assert data[0]["fitness"] == pytest.approx(1.5)

    def test_entry_contains_expected_fields(self, client, test_db):
        a1 = _make_alpha("rank(close)")
        test_db.add(a1)
        test_db.flush()

        s1 = _make_sim(a1.id, sharpe=1.4, fitness=1.1, returns=0.07,
                       turnover=0.55, passed=True)
        test_db.add(s1)
        test_db.commit()

        r = client.get("/api/pool/top")
        data = r.json()
        assert len(data) == 1
        entry = data[0]
        assert "id" in entry
        assert "expression" in entry
        assert "source" in entry
        assert entry["sharpe"] == pytest.approx(1.4)
        assert entry["fitness"] == pytest.approx(1.1)
        assert entry["returns"] == pytest.approx(0.07)
        assert entry["turnover"] == pytest.approx(0.55)
        assert entry["passed"] is True


# ── POST /pool/recompute ──────────────────────────────────────────────────────

class TestPoolRecompute:
    def test_empty_panel_returns_zero_pairs_and_skipped_count(self, client, test_db):
        """When panel is empty, skipped = number of completed alphas."""
        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()

        test_db.add(_make_sim(a1.id))
        test_db.add(_make_sim(a2.id))
        test_db.commit()

        r = client.post("/api/pool/recompute")
        assert r.status_code == 200
        data = r.json()
        assert data["pairs_computed"] == 0
        assert data["skipped"] == 2  # panel is empty, both alphas skipped

    def test_empty_db_returns_zero_pairs_zero_skipped(self, client):
        r = client.post("/api/pool/recompute")
        assert r.status_code == 200
        data = r.json()
        assert data["pairs_computed"] == 0
        assert data["skipped"] == 0

    def test_with_proxy_data_stores_correlations(self, client, test_db):
        """Insert proxy data and two completed alphas → recompute stores correlations."""
        # Insert proxy price data for two tickers over enough dates
        import numpy as np
        dates = [f"2024-01-{d:02d}" for d in range(2, 32) if d <= 31]
        # Use a full month of dates to get enough data points
        business_dates = []
        for m in range(1, 3):
            for d in range(1, 29):
                try:
                    import datetime as dt
                    day = dt.date(2024, m, d)
                    if day.weekday() < 5:  # weekday
                        business_dates.append(str(day))
                except ValueError:
                    pass
        business_dates = business_dates[:25]  # 25 dates per ticker

        tickers = ["AAPL", "MSFT"]
        close_A = np.linspace(150.0, 170.0, len(business_dates))
        close_B = np.linspace(300.0, 320.0, len(business_dates))

        for i, date in enumerate(business_dates):
            test_db.add(ProxyPrice(ticker="AAPL", date=date,
                                   open=close_A[i], high=close_A[i]+1,
                                   low=close_A[i]-1, close=close_A[i],
                                   volume=1_000_000))
            test_db.add(ProxyPrice(ticker="MSFT", date=date,
                                   open=close_B[i], high=close_B[i]+1,
                                   low=close_B[i]-1, close=close_B[i],
                                   volume=2_000_000))
        test_db.flush()

        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()

        test_db.add(_make_sim(a1.id))
        test_db.add(_make_sim(a2.id))
        test_db.commit()

        r = client.post("/api/pool/recompute")
        assert r.status_code == 200
        data = r.json()
        assert data["pairs_computed"] == 1  # 1 pair: a1 x a2
        assert data["skipped"] == 0

        # Check correlations were stored
        corr_rows = test_db.query(PoolCorrelation).all()
        assert len(corr_rows) == 1

    def test_recompute_updates_existing_correlation(self, client, test_db):
        """Running recompute twice updates existing rows."""
        import numpy as np
        import datetime as dt

        business_dates = []
        for d in range(1, 32):
            try:
                day = dt.date(2024, 1, d)
                if day.weekday() < 5:
                    business_dates.append(str(day))
            except ValueError:
                pass
        business_dates = business_dates[:20]

        close_A = np.linspace(150.0, 170.0, len(business_dates))
        close_B = np.linspace(300.0, 320.0, len(business_dates))

        for i, date in enumerate(business_dates):
            test_db.add(ProxyPrice(ticker="AAPL", date=date,
                                   open=close_A[i], high=close_A[i]+1,
                                   low=close_A[i]-1, close=close_A[i],
                                   volume=1_000_000))
            test_db.add(ProxyPrice(ticker="MSFT", date=date,
                                   open=close_B[i], high=close_B[i]+1,
                                   low=close_B[i]-1, close=close_B[i],
                                   volume=2_000_000))
        test_db.flush()

        a1 = _make_alpha("rank(close)")
        a2 = _make_alpha("rank(open)")
        test_db.add(a1)
        test_db.add(a2)
        test_db.flush()
        test_db.add(_make_sim(a1.id))
        test_db.add(_make_sim(a2.id))
        test_db.commit()

        # First recompute
        r1 = client.post("/api/pool/recompute")
        assert r1.json()["pairs_computed"] == 1

        # Second recompute — should update existing row
        r2 = client.post("/api/pool/recompute")
        assert r2.json()["pairs_computed"] == 1

        # Still only 1 correlation row
        corr_rows = test_db.query(PoolCorrelation).all()
        assert len(corr_rows) == 1
