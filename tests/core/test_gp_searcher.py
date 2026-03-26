"""Tests for GPSearcher — mock SymbolicRegressor throughout."""
import itertools

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from backend.core.gp_searcher import GPSearcher, FEATURE_EXPRESSIONS
from backend.core.models import AlphaSource


def _make_panel(n_tickers=3, n_dates=30):
    """Small synthetic panel for testing."""
    tickers = [f"T{i}" for i in range(n_tickers)]
    # Use a base date and increment by 1 day each step to generate unique dates
    base = pd.Timestamp("2023-01-01")
    date_list = [(base + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_dates)]
    idx = pd.MultiIndex.from_tuples(
        list(itertools.product(date_list, tickers)), names=["date", "ticker"]
    )
    np.random.seed(42)
    n = len(idx)
    df = pd.DataFrame(
        {
            "open": np.random.uniform(10, 100, n),
            "high": np.random.uniform(10, 100, n),
            "low": np.random.uniform(10, 100, n),
            "close": np.random.uniform(10, 100, n),
            "volume": np.random.uniform(1e6, 1e8, n),
        },
        index=idx,
    )
    return df


def _make_large_panel(n_tickers=10, n_dates=300):
    """Larger panel that yields enough rows after subsampling (>= 100)."""
    # 300 dates × 10 tickers → 3000 rows total
    # After subsampling every 5th of last 252 → ~51 dates × 10 = 510 rows > 100
    tickers = [f"T{i}" for i in range(n_tickers)]
    base = pd.Timestamp("2022-01-01")
    date_list = [(base + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_dates)]
    idx = pd.MultiIndex.from_tuples(
        list(itertools.product(date_list, tickers)), names=["date", "ticker"]
    )
    np.random.seed(42)
    n = len(idx)
    df = pd.DataFrame(
        {
            "open": np.random.uniform(10, 100, n),
            "high": np.random.uniform(10, 100, n),
            "low": np.random.uniform(10, 100, n),
            "close": np.random.uniform(10, 100, n),
            "volume": np.random.uniform(1e6, 1e8, n),
        },
        index=idx,
    )
    return df


# ── _to_wq_expression tests ───────────────────────────────────────────────────

class TestToWqExpression:
    def setup_method(self):
        self.searcher = GPSearcher()
        # Use the actual feature names from FEATURE_EXPRESSIONS
        self.feature_names = [wq for _, wq in FEATURE_EXPRESSIONS]

    def test_add(self):
        result = self.searcher._to_wq_expression("add(X0, X1)", self.feature_names)
        assert result == "(close + open)"

    def test_neg(self):
        result = self.searcher._to_wq_expression("neg(X5)", self.feature_names)
        assert result == "(-returns)"

    def test_log(self):
        result = self.searcher._to_wq_expression("log(X6)", self.feature_names)
        assert result == "log(ts_mean(close, 5))"

    def test_mul_with_literal(self):
        result = self.searcher._to_wq_expression("mul(X0, 0.123)", self.feature_names)
        assert result == "(close * 0.123)"

    def test_deeply_nested(self):
        result = self.searcher._to_wq_expression(
            "add(mul(X0, X1), neg(X2))", self.feature_names
        )
        assert result == "((close * open) + (-high))"

    def test_sub_same_feature(self):
        result = self.searcher._to_wq_expression("sub(X0, X0)", self.feature_names)
        assert result == "(close - close)"

    def test_malformed_returns_none(self):
        # A bare identifier without parentheses should fail
        result = self.searcher._to_wq_expression("abc", self.feature_names)
        assert result is None

    def test_div(self):
        result = self.searcher._to_wq_expression("div(X0, X1)", self.feature_names)
        assert result == "(close / open)"


# ── _build_dataset tests ──────────────────────────────────────────────────────

class TestBuildDataset:
    def setup_method(self):
        self.searcher = GPSearcher()

    def test_returns_correct_shapes(self):
        panel = _make_large_panel(n_tickers=10, n_dates=300)
        X, y, feature_names = self.searcher._build_dataset(panel)
        # X should be (n_samples, n_features) and y (n_samples,)
        assert X.ndim == 2
        assert y.ndim == 1
        assert X.shape[0] == y.shape[0]
        assert X.shape[1] == len(feature_names)

    def test_no_nan_in_output(self):
        panel = _make_large_panel(n_tickers=10, n_dates=300)
        X, y, feature_names = self.searcher._build_dataset(panel)
        assert not np.any(np.isnan(X))
        assert not np.any(np.isnan(y))
        assert not np.any(np.isinf(X))
        assert not np.any(np.isinf(y))

    def test_dtypes_are_float32(self):
        panel = _make_large_panel(n_tickers=10, n_dates=300)
        X, y, _ = self.searcher._build_dataset(panel)
        assert X.dtype == np.float32
        assert y.dtype == np.float32

    def test_insufficient_data_raises_value_error(self):
        # 2 dates × 3 tickers = 6 rows — way fewer than MIN_VALID_ROWS=100
        panel = _make_panel(n_tickers=3, n_dates=2)
        with pytest.raises(ValueError, match="Insufficient data"):
            self.searcher._build_dataset(panel)


# ── run() tests (mock SymbolicRegressor) ─────────────────────────────────────

def _make_fake_program(expr_str: str, fitness: float):
    prog = MagicMock()
    prog.fitness_ = fitness
    prog.__str__ = lambda self: expr_str
    return prog


class TestRun:
    def setup_method(self):
        self.searcher = GPSearcher()

    @patch("backend.core.gp_searcher.SymbolicRegressor")
    def test_run_returns_alpha_candidates(self, mock_cls):
        mock_est = MagicMock()
        mock_cls.return_value = mock_est
        progs = [
            _make_fake_program("add(X0, X1)", 0.08),
            _make_fake_program("neg(X5)", 0.07),
            _make_fake_program("log(X6)", 0.06),
        ]
        mock_est._programs = [progs]

        panel = _make_large_panel(n_tickers=10, n_dates=300)
        results = self.searcher.run(panel, n_results=3, population_size=10, generations=2)

        assert len(results) > 0
        for c in results:
            assert hasattr(c, "expression")
            assert hasattr(c, "source")

    @patch("backend.core.gp_searcher.SymbolicRegressor")
    def test_run_candidates_have_gp_source(self, mock_cls):
        mock_est = MagicMock()
        mock_cls.return_value = mock_est
        progs = [_make_fake_program("add(X0, X1)", 0.05)]
        mock_est._programs = [progs]

        panel = _make_large_panel(n_tickers=10, n_dates=300)
        results = self.searcher.run(panel, n_results=5, population_size=10, generations=2)

        for c in results:
            assert c.source == AlphaSource.GP

    @patch("backend.core.gp_searcher.SymbolicRegressor")
    def test_run_deduplicates_programs(self, mock_cls):
        mock_est = MagicMock()
        mock_cls.return_value = mock_est
        # Two programs with identical string representation
        progs = [
            _make_fake_program("add(X0, X1)", 0.08),
            _make_fake_program("add(X0, X1)", 0.07),
            _make_fake_program("neg(X5)", 0.06),
        ]
        mock_est._programs = [progs]

        panel = _make_large_panel(n_tickers=10, n_dates=300)
        results = self.searcher.run(panel, n_results=10, population_size=10, generations=2)

        expressions = [c.expression for c in results]
        # The duplicated expression should appear at most once
        wq_for_add = "(close + open)"
        assert expressions.count(wq_for_add) <= 1

    @patch("backend.core.gp_searcher.SymbolicRegressor")
    def test_run_with_empty_programs_returns_empty(self, mock_cls):
        mock_est = MagicMock()
        mock_cls.return_value = mock_est
        mock_est._programs = []

        panel = _make_large_panel(n_tickers=10, n_dates=300)
        results = self.searcher.run(panel, n_results=5, population_size=10, generations=2)

        assert results == []
