from backend.core.seed_pool import SEED_POOL
from backend.core.models import AlphaSource
from backend.core.expression_validator import ExpressionValidator


def test_seed_pool_has_expected_size():
    assert len(SEED_POOL) >= 20


def test_all_seeds_have_seed_source():
    for alpha in SEED_POOL:
        assert alpha.source == AlphaSource.SEED


def test_all_seeds_have_unique_ids():
    ids = [a.id for a in SEED_POOL]
    assert len(ids) == len(set(ids)), "Duplicate IDs in seed pool"


def test_all_seeds_pass_validator():
    validator = ExpressionValidator()
    for alpha in SEED_POOL:
        result = validator.validate(alpha.expression)
        assert result.valid, f"Seed {alpha.expression!r} failed: {result.reason}"


def test_all_seeds_have_default_config():
    for alpha in SEED_POOL:
        assert alpha.universe == "TOP3000"
        assert alpha.region == "USA"
        assert alpha.delay == 1
        assert alpha.filter_skipped is False
