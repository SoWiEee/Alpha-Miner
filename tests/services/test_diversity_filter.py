"""Tests for AlphaEvaluator and DiversityFilter."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.core.models import AlphaCandidate, AlphaSource
from backend.services.diversity_filter import (
    AlphaEvaluator,
    DiversityFilter,
    UnsupportedOperatorError,
)


# ── Synthetic panel fixture ───────────────────────────────────────────────────

@pytest.fixture
def panel() -> pd.DataFrame:
    """
    Small deterministic panel: 3 tickers × 20 dates.
    Index: MultiIndex(["date", "ticker"]).
    Columns: open, high, low, close, volume.
    """
    tickers = ["A", "B", "C"]
    dates = [f"2024-{m:02d}-{d:02d}" for m, d in [
        (1, 2), (1, 3), (1, 4), (1, 5), (1, 8),
        (1, 9), (1, 10), (1, 11), (1, 12), (1, 15),
        (1, 16), (1, 17), (1, 18), (1, 19), (1, 22),
        (1, 23), (1, 24), (1, 25), (1, 26), (1, 29),
    ]]
    n = len(dates)

    close_A = np.linspace(10.0, 30.0, n)
    close_B = np.linspace(20.0, 40.0, n)
    close_C = np.linspace(50.0, 70.0, n)

    records = []
    for i, date in enumerate(dates):
        records.append({"date": date, "ticker": "A",
                        "open": close_A[i] - 0.5, "high": close_A[i] + 1.0,
                        "low": close_A[i] - 1.0, "close": close_A[i],
                        "volume": int(1_000_000 + i * 10_000)})
        records.append({"date": date, "ticker": "B",
                        "open": close_B[i] - 0.5, "high": close_B[i] + 1.0,
                        "low": close_B[i] - 1.0, "close": close_B[i],
                        "volume": int(2_000_000 + i * 20_000)})
        records.append({"date": date, "ticker": "C",
                        "open": close_C[i] - 0.5, "high": close_C[i] + 1.0,
                        "low": close_C[i] - 1.0, "close": close_C[i],
                        "volume": int(3_000_000 + i * 30_000)})

    df = pd.DataFrame.from_records(records)
    df = df.set_index(["date", "ticker"]).sort_index()
    return df


# ── AlphaEvaluator tests ──────────────────────────────────────────────────────

class TestAlphaEvaluator:
    def test_evaluate_close_returns_close_series(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("close", panel)
        pd.testing.assert_series_equal(result, panel["close"], check_names=False)

    def test_evaluate_rank_returns_values_in_0_1(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("rank(close)", panel)
        assert isinstance(result, pd.Series)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_evaluate_ts_mean_returns_reasonable_values(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("ts_mean(close, 5)", panel)
        assert isinstance(result, pd.Series)
        # Rolling mean should be between min and max of close
        assert result.min() >= panel["close"].min() - 1e-6
        assert result.max() <= panel["close"].max() + 1e-6

    def test_evaluate_ts_delta_matches_manual(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("ts_delta(close, 5)", panel)
        # Manual: close - ts_delay(close, 5)
        delayed = panel["close"].groupby(level="ticker").transform(lambda x: x.shift(5))
        expected = panel["close"] - delayed
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_evaluate_arithmetic_close_minus_open(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("close - open", panel)
        expected = panel["close"] - panel["open"]
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_evaluate_unary_minus(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("-rank(close)", panel)
        rank = panel["close"].groupby(level="date").rank(pct=True)
        pd.testing.assert_series_equal(result, -rank, check_names=False)

    def test_evaluate_scalar_multiply(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("rank(close) * 2.0", panel)
        rank = panel["close"].groupby(level="date").rank(pct=True)
        pd.testing.assert_series_equal(result, rank * 2.0, check_names=False)

    def test_evaluate_nested_calls(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("rank(ts_mean(close, 5))", panel)
        assert isinstance(result, pd.Series)
        # rank should return values in [0, 1]
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_evaluate_unknown_field_raises(self, panel):
        ev = AlphaEvaluator()
        with pytest.raises(UnsupportedOperatorError, match="adv5"):
            ev.evaluate("adv5", panel)

    def test_evaluate_unknown_function_raises(self, panel):
        ev = AlphaEvaluator()
        with pytest.raises(UnsupportedOperatorError, match="unknown_func"):
            ev.evaluate("unknown_func(close)", panel)

    def test_evaluate_returns_field(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("returns", panel)
        expected = panel["close"].groupby(level="ticker").pct_change()
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_evaluate_abs(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("abs(close - open)", panel)
        expected = (panel["close"] - panel["open"]).abs()
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_evaluate_ts_delay(self, panel):
        ev = AlphaEvaluator()
        result = ev.evaluate("ts_delay(close, 3)", panel)
        expected = panel["close"].groupby(level="ticker").transform(lambda x: x.shift(3))
        pd.testing.assert_series_equal(result, expected, check_names=False)


# ── DiversityFilter tests ─────────────────────────────────────────────────────

def _make_candidate(expression: str) -> AlphaCandidate:
    return AlphaCandidate.create(expression=expression, source=AlphaSource.SEED)


class TestDiversityFilter:
    def test_unevaluable_candidate_returns_true_nan(self, panel):
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("adv5")  # unsupported field
        pool = [_make_candidate("close")]
        submit, corr = filt.should_submit(candidate, pool, ev, panel)
        assert submit is True
        assert math.isnan(corr)

    def test_empty_pool_returns_true_zero(self, panel):
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("close")
        submit, corr = filt.should_submit(candidate, [], ev, panel)
        assert submit is True
        assert corr == 0.0

    def test_identical_expression_rejected(self, panel):
        """Identical expressions have correlation ~1.0, should be rejected."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(close)")]
        submit, corr = filt.should_submit(candidate, pool, ev, panel)
        assert bool(submit) is False
        assert corr > 0.7

    def test_uncorrelated_expressions_pass(self, panel):
        """
        Mock spearmanr to return low correlation to test the pass-through logic.
        """
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(open)")]

        from unittest.mock import patch
        with patch("backend.services.diversity_filter.spearmanr") as mock_sr:
            mock_sr.return_value = (0.3, 0.1)
            submit, corr = filt.should_submit(candidate, pool, ev, panel)

        assert bool(submit) is True
        assert corr == pytest.approx(0.3)

    def test_pool_member_failing_evaluation_is_skipped(self, panel):
        """If a pool member can't be evaluated, it should be skipped (not crash)."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("close")
        # adv5 is unsupported — pool member should be skipped
        bad_member = _make_candidate("adv5")
        submit, corr = filt.should_submit(candidate, [bad_member], ev, panel)
        # No valid pool members → treated as empty pool
        assert submit is True
        assert corr == 0.0

    def test_threshold_boundary(self, panel):
        """Correlation exactly at threshold passes (<=)."""
        from unittest.mock import patch, MagicMock
        from scipy.stats import spearmanr as real_spearmanr

        filt = DiversityFilter(threshold=0.85)
        ev = AlphaEvaluator()
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(close)")]

        # Patch spearmanr to return exactly 0.85
        with patch("backend.services.diversity_filter.spearmanr") as mock_sr:
            mock_sr.return_value = (0.85, 0.01)
            submit, corr = filt.should_submit(candidate, pool, ev, panel)

        assert submit is True  # 0.85 <= 0.85
        assert corr == pytest.approx(0.85)

    def test_above_threshold_rejected(self, panel):
        """Correlation above threshold is rejected."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(close)")]

        from unittest.mock import patch
        with patch("backend.services.diversity_filter.spearmanr") as mock_sr:
            mock_sr.return_value = (0.95, 0.001)
            submit, corr = filt.should_submit(candidate, pool, ev, panel)

        assert submit is False
        assert corr == pytest.approx(0.95)


# ── DiversityFilter.filter_batch() tests ──────────────────────────────────────

class TestFilterBatch:
    def test_filter_batch_empty_pool_returns_all_pass_zero(self, panel):
        """filter_batch() with empty pool returns (cand, True, 0.0) for each candidate."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidates = [_make_candidate("close"), _make_candidate("rank(close)")]
        results = filt.filter_batch(candidates, [], ev, panel)

        assert len(results) == 2
        for cand, should_submit, max_corr in results:
            assert should_submit is True
            assert max_corr == 0.0

    def test_filter_batch_unevaluable_candidate_returns_true_nan(self, panel):
        """filter_batch() returns (cand, True, nan) for unevaluable candidates."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidates = [_make_candidate("adv5")]  # unsupported field
        pool = [_make_candidate("close")]
        results = filt.filter_batch(candidates, pool, ev, panel)

        assert len(results) == 1
        _, should_submit, max_corr = results[0]
        assert should_submit is True
        assert math.isnan(max_corr)

    def test_filter_batch_rejects_high_correlation_candidate(self, panel):
        """filter_batch() rejects candidates whose correlation exceeds threshold."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        # Identical expressions will have ~1.0 correlation
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(close)")]
        results = filt.filter_batch([candidate], pool, ev, panel)

        assert len(results) == 1
        _, should_submit, max_corr = results[0]
        assert bool(should_submit) is False
        assert max_corr > 0.7

    def test_filter_batch_passes_low_correlation_candidate(self, panel):
        """filter_batch() accepts candidates whose correlation is below threshold."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("rank(close)")
        pool = [_make_candidate("rank(close)")]

        from unittest.mock import patch
        with patch("backend.services.diversity_filter.spearmanr") as mock_sr:
            mock_sr.return_value = (0.3, 0.1)
            results = filt.filter_batch([candidate], pool, ev, panel)

        assert len(results) == 1
        _, should_submit, max_corr = results[0]
        assert should_submit is True
        assert max_corr == pytest.approx(0.3)

    def test_filter_batch_pool_member_failure_skipped(self, panel):
        """filter_batch() skips unevaluable pool members without crashing."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        candidate = _make_candidate("close")
        bad_pool_member = _make_candidate("adv5")  # unsupported
        results = filt.filter_batch([candidate], [bad_pool_member], ev, panel)

        assert len(results) == 1
        _, should_submit, max_corr = results[0]
        # No valid pool members → treated as empty pool
        assert should_submit is True
        assert max_corr == 0.0

    def test_filter_batch_multiple_candidates(self, panel):
        """filter_batch() correctly processes multiple candidates independently."""
        filt = DiversityFilter(threshold=0.7)
        ev = AlphaEvaluator()
        pool = [_make_candidate("rank(close)")]

        # One candidate identical to pool member (will be rejected)
        # One candidate that is unevaluable (adv5, will pass with nan)
        # One candidate with empty pool after bad pool member — but pool is good here
        candidates = [
            _make_candidate("rank(close)"),  # high corr → rejected
            _make_candidate("adv5"),          # unevaluable → pass with nan
        ]
        results = filt.filter_batch(candidates, pool, ev, panel)
        assert len(results) == 2

        # First: rejected (high correlation)
        _, submit0, corr0 = results[0]
        assert bool(submit0) is False

        # Second: unevaluable → pass with nan
        _, submit1, corr1 = results[1]
        assert submit1 is True
        assert math.isnan(corr1)
