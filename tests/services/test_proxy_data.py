"""Tests for ProxyDataManager."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from backend.services.proxy_data import ProxyDataManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_sp500_tables():
    """Return a list of DataFrames simulating pd.read_html(SP500_URL)."""
    df = pd.DataFrame({"Symbol": ["AAPL", "MSFT", "GOOG"]})
    return [df]


def _make_fake_download(tickers: list[str], n_dates: int = 5) -> pd.DataFrame:
    """Return a fake yf.download result with MultiIndex columns (field, ticker)."""
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    fields = ["Open", "High", "Low", "Close", "Volume"]
    cols = pd.MultiIndex.from_product([fields, tickers], names=[None, None])
    data = np.random.default_rng(42).random((n_dates, len(fields) * len(tickers))) * 100
    return pd.DataFrame(data, index=dates, columns=cols)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestProxyDataManagerUpdate:
    def test_update_stores_rows_and_returns_count(self, test_db):
        tickers = ["AAPL", "GOOG", "MSFT"]
        fake_download = _make_fake_download(tickers, n_dates=5)

        with (
            patch("backend.services.proxy_data.pd.read_html", return_value=_make_fake_sp500_tables()),
            patch("backend.services.proxy_data.yf.download", return_value=fake_download),
        ):
            mgr = ProxyDataManager()
            count = mgr.update(test_db, max_tickers=3)

        # 3 tickers × 5 dates = 15 rows
        assert count == 15

        from backend.models.correlation import ProxyPrice
        rows = test_db.query(ProxyPrice).all()
        assert len(rows) == 15

    def test_update_is_idempotent(self, test_db):
        # Sorted symbols from _make_fake_sp500_tables() = ['AAPL', 'GOOG', 'MSFT']
        # With max_tickers=2, the fetched tickers will be ['AAPL', 'GOOG']
        tickers = ["AAPL", "GOOG"]
        fake_download = _make_fake_download(tickers, n_dates=3)

        with (
            patch("backend.services.proxy_data.pd.read_html", return_value=_make_fake_sp500_tables()),
            patch("backend.services.proxy_data.yf.download", return_value=fake_download),
        ):
            mgr = ProxyDataManager()
            mgr.update(test_db, max_tickers=2)
            count2 = mgr.update(test_db, max_tickers=2)

        from backend.models.correlation import ProxyPrice
        rows = test_db.query(ProxyPrice).all()
        # Should still be 2 × 3 = 6 rows (no duplication)
        assert len(rows) == 6
        # Second call still returns the update count (rows processed)
        assert count2 == 6

    def test_update_replaces_values_on_second_call(self, test_db):
        """Second update with different prices updates existing rows."""
        # Use 2 tickers so xs() works correctly with MultiIndex
        tickers = ["AAPL", "MSFT"]
        fake1 = _make_fake_download(tickers, n_dates=2)
        # Modify the close price for second call (AAPL only)
        fake2 = fake1.copy()
        fake2[("Close", "AAPL")] = 999.0

        with (
            patch("backend.services.proxy_data.pd.read_html", return_value=_make_fake_sp500_tables()),
            patch("backend.services.proxy_data.yf.download", return_value=fake1),
        ):
            mgr = ProxyDataManager()
            mgr.update(test_db, max_tickers=2)

        with (
            patch("backend.services.proxy_data.pd.read_html", return_value=_make_fake_sp500_tables()),
            patch("backend.services.proxy_data.yf.download", return_value=fake2),
        ):
            mgr.update(test_db, max_tickers=2)

        from backend.models.correlation import ProxyPrice
        rows = test_db.query(ProxyPrice).filter(ProxyPrice.ticker == "AAPL").all()
        assert all(r.close == pytest.approx(999.0) for r in rows)


class TestProxyDataManagerGetPanel:
    def test_get_panel_returns_empty_dataframe_when_no_data(self, test_db):
        mgr = ProxyDataManager()
        df = mgr.get_panel(test_db)

        assert df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.names == ["date", "ticker"]

    def test_get_panel_returns_multiindex_dataframe(self, test_db):
        from backend.models.correlation import ProxyPrice
        # Insert a few rows
        test_db.add(ProxyPrice(ticker="AAPL", date="2024-01-02", open=150.0, high=155.0,
                               low=149.0, close=153.0, volume=1000000))
        test_db.add(ProxyPrice(ticker="MSFT", date="2024-01-02", open=300.0, high=305.0,
                               low=299.0, close=302.0, volume=500000))
        test_db.add(ProxyPrice(ticker="AAPL", date="2024-01-03", open=153.0, high=158.0,
                               low=152.0, close=157.0, volume=1100000))
        test_db.commit()

        mgr = ProxyDataManager()
        df = mgr.get_panel(test_db)

        assert df.index.names == ["date", "ticker"]
        assert set(df.columns) == {"open", "high", "low", "close", "volume"}
        assert len(df) == 3
        # Check MultiIndex contains expected tuples
        assert ("2024-01-02", "AAPL") in df.index
        assert ("2024-01-02", "MSFT") in df.index
        assert ("2024-01-03", "AAPL") in df.index

    def test_get_panel_sorted_by_date_then_ticker(self, test_db):
        from backend.models.correlation import ProxyPrice
        test_db.add(ProxyPrice(ticker="MSFT", date="2024-01-03", open=1.0, high=1.0,
                               low=1.0, close=1.0, volume=1))
        test_db.add(ProxyPrice(ticker="AAPL", date="2024-01-01", open=1.0, high=1.0,
                               low=1.0, close=1.0, volume=1))
        test_db.add(ProxyPrice(ticker="AAPL", date="2024-01-03", open=1.0, high=1.0,
                               low=1.0, close=1.0, volume=1))
        test_db.commit()

        mgr = ProxyDataManager()
        df = mgr.get_panel(test_db)

        # Index should be sorted
        assert list(df.index) == sorted(df.index.tolist())
