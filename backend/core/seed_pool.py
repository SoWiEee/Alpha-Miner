"""
Representative subset of Alpha101 formulas (Kakushadze 2016) in WQ Fast Expression syntax.
~25 alphas covering 5 strategy families.
"""
from backend.core.models import AlphaCandidate, AlphaSource

_S = AlphaSource.SEED


def _seed(expression: str) -> AlphaCandidate:
    return AlphaCandidate.create(expression, _S)


SEED_POOL: list[AlphaCandidate] = [
    # ── Price Momentum ─────────────────────────────────────────────
    _seed("rank(ts_delta(close, 1))"),
    _seed("rank(ts_delta(close, 5))"),
    _seed("-1 * ts_corr(rank(ts_delta(log(volume), 2)), rank((close - open) / open), 6)"),
    _seed("sign(ts_delta(volume, 1)) * (-1 * ts_delta(close, 1))"),
    _seed("-1 * ts_rank(rank(low), 9)"),
    _seed("rank(ts_mean(close, 5)) - rank(ts_mean(close, 20))"),

    # ── Mean Reversion ─────────────────────────────────────────────
    _seed("-1 * ts_corr(rank(open), rank(volume), 10)"),
    _seed("rank((close - ts_mean(close, 20)) / ts_std(close, 20))"),
    _seed("-1 * ts_delta(rank(close), 5)"),
    _seed("rank(-1 * ts_delta(close, 10))"),
    _seed("-1 * rank(ts_mean(rank(ts_delta(close, 1)), 10))"),

    # ── Volume-Price Divergence ─────────────────────────────────────
    _seed("-1 * ts_corr(open, volume, 10)"),
    _seed("rank(ts_delta(volume, 5)) * (-1 * rank(ts_delta(close, 5)))"),
    _seed("ts_rank(volume, 5) - ts_rank(close, 5)"),
    _seed("rank(log(volume) - ts_mean(log(volume), 20))"),
    _seed("-1 * ts_corr(rank(close), rank(volume), 5)"),

    # ── Volatility ─────────────────────────────────────────────────
    _seed("-1 * ts_std(returns, 20)"),
    _seed("-1 * rank(ts_std(close, 10))"),
    _seed("ts_rank(ts_std(close, 5), 20)"),
    _seed("rank(ts_mean(abs(ts_delta(close, 1)), 20))"),

    # ── Correlation-Based ──────────────────────────────────────────
    _seed("-1 * ts_corr(ts_rank(adv(81), 17), ts_rank(close, 17), 5)"),
    _seed("rank(ts_corr(close, volume, 5))"),
    _seed("-1 * rank(ts_corr(rank(high), rank(volume), 5))"),
    _seed("ts_corr(rank(close), rank(ts_mean(volume, 20)), 10)"),
    _seed("-1 * ts_corr(rank(vwap), rank(volume), 5)"),
]
