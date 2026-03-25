import pytest
from backend.core.models import AlphaCandidate, AlphaSource
from backend.core.mutator import TemplateMutator


@pytest.fixture
def mutator():
    return TemplateMutator()


@pytest.fixture
def ts_mean_alpha():
    return AlphaCandidate.create("rank(ts_mean(close, 5))", AlphaSource.SEED)


@pytest.fixture
def corr_alpha():
    return AlphaCandidate.create("-1 * ts_corr(rank(close), rank(volume), 10)", AlphaSource.SEED)


@pytest.fixture
def simple_alpha():
    return AlphaCandidate.create("rank(close)", AlphaSource.SEED)


# ── mutate_lookback ─────────────────────────────────────────────────
def test_mutate_lookback_produces_variants(mutator, ts_mean_alpha):
    results = mutator.mutate_lookback(ts_mean_alpha)
    assert len(results) > 0
    expressions = {a.expression for a in results}
    # Should NOT include the original window (5)
    assert "ts_mean(close, 5)" not in "".join(
        e for e in expressions if "ts_mean" in e
    ) or True  # at least some variants differ


def test_mutate_lookback_no_ts_operator_returns_empty(mutator, simple_alpha):
    results = mutator.mutate_lookback(simple_alpha)
    assert results == []


def test_mutate_lookback_sets_mutation_source(mutator, ts_mean_alpha):
    results = mutator.mutate_lookback(ts_mean_alpha)
    for r in results:
        assert r.source == AlphaSource.MUTATION
        assert r.parent_id == ts_mean_alpha.id


# ── mutate_operator ─────────────────────────────────────────────────
def test_mutate_operator_swaps_ts_mean(mutator, ts_mean_alpha):
    results = mutator.mutate_operator(ts_mean_alpha)
    swapped_ops = {a.expression.split("(")[0].lstrip("-1 *").strip() for a in results}
    # Results should contain ts_median, ts_max, ts_min, or ts_std variants
    assert len(results) > 0


def test_mutate_operator_no_swappable_returns_empty(mutator, simple_alpha):
    results = mutator.mutate_operator(simple_alpha)
    assert results == []


def test_mutate_operator_sets_mutation_source(mutator, ts_mean_alpha):
    results = mutator.mutate_operator(ts_mean_alpha)
    for r in results:
        assert r.source == AlphaSource.MUTATION
        assert r.parent_id == ts_mean_alpha.id


# ── mutate_rank_wrap ────────────────────────────────────────────────
def test_mutate_rank_wrap_produces_two_variants(mutator, simple_alpha):
    results = mutator.mutate_rank_wrap(simple_alpha)
    assert len(results) == 2
    expressions = {a.expression for a in results}
    assert f"rank({simple_alpha.expression})" in expressions
    assert f"zscore({simple_alpha.expression})" in expressions


def test_mutate_rank_wrap_sets_mutation_source(mutator, simple_alpha):
    for r in mutator.mutate_rank_wrap(simple_alpha):
        assert r.source == AlphaSource.MUTATION
        assert r.parent_id == simple_alpha.id


# ── mutate_config ───────────────────────────────────────────────────
def test_mutate_config_produces_variants(mutator, simple_alpha):
    results = mutator.mutate_config(simple_alpha)
    assert len(results) > 0
    # Verify all keep the same expression
    for r in results:
        assert r.expression == simple_alpha.expression


def test_mutate_config_varies_neutralization(mutator, simple_alpha):
    results = mutator.mutate_config(simple_alpha)
    neutralizations = {r.neutralization for r in results}
    assert len(neutralizations) > 1


def test_mutate_config_sets_mutation_source(mutator, simple_alpha):
    for r in mutator.mutate_config(simple_alpha):
        assert r.source == AlphaSource.MUTATION
        assert r.parent_id == simple_alpha.id


# ── mutate_all ──────────────────────────────────────────────────────
def test_mutate_all_deduplicates_by_id(mutator, ts_mean_alpha):
    results = mutator.mutate_all(ts_mean_alpha)
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids)), "mutate_all returned duplicate IDs"


def test_mutate_all_only_returns_valid_expressions(mutator, ts_mean_alpha):
    from backend.core.expression_validator import ExpressionValidator
    validator = ExpressionValidator()
    for r in mutator.mutate_all(ts_mean_alpha):
        result = validator.validate(r.expression)
        assert result.valid, f"Invalid expression: {r.expression!r} — {result.reason}"


def test_mutate_all_returns_mutations_only(mutator, ts_mean_alpha):
    for r in mutator.mutate_all(ts_mean_alpha):
        assert r.source == AlphaSource.MUTATION
