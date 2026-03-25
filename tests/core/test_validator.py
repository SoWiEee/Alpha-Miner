import pytest
from backend.core.expression_validator import ExpressionValidator, ValidationResult


@pytest.fixture
def validator():
    return ExpressionValidator()


# --- Balanced parentheses ---
def test_valid_expression_passes(validator):
    result = validator.validate("rank(ts_delta(close, 5))")
    assert result.valid is True
    assert result.reason is None


def test_unbalanced_open_paren_fails(validator):
    result = validator.validate("rank(ts_delta(close, 5)")
    assert result.valid is False
    assert "parenthes" in result.reason.lower()


def test_unbalanced_close_paren_fails(validator):
    result = validator.validate("rank(close))")
    assert result.valid is False


# --- Operator whitelist ---
def test_known_operator_passes(validator):
    result = validator.validate("ts_mean(close, 10)")
    assert result.valid is True


def test_unknown_operator_fails(validator):
    result = validator.validate("unknown_func(close, 5)")
    assert result.valid is False
    assert "unknown_func" in result.reason


def test_all_allowed_operators_pass(validator):
    expressions = [
        "ts_std(returns, 20)",
        "zscore(rank(close))",
        "scale(log(volume))",
        "abs(ts_delta(close, 1))",
        "sign(close - open)",
        "adv(20)",
        "ts_corr(close, volume, 5)",
        "ts_covariance(close, volume, 10)",
        "IndNeutralize(rank(close), IndClass.sector)",
    ]
    for expr in expressions:
        r = validator.validate(expr)
        assert r.valid is True, f"Expected {expr!r} to be valid, got: {r.reason}"


# --- Numeric argument ranges ---
def test_window_in_range_passes(validator):
    assert validator.validate("ts_mean(close, 252)").valid is True
    assert validator.validate("ts_mean(close, 1)").valid is True


def test_window_zero_fails(validator):
    result = validator.validate("ts_mean(close, 0)")
    assert result.valid is False
    assert "range" in result.reason.lower() or "window" in result.reason.lower()


def test_window_too_large_fails(validator):
    result = validator.validate("ts_mean(close, 300)")
    assert result.valid is False


# --- Python keyword blacklist ---
def test_import_keyword_fails(validator):
    result = validator.validate("import os")
    assert result.valid is False


def test_eval_keyword_fails(validator):
    result = validator.validate("eval(close)")
    assert result.valid is False
    assert "eval" in result.reason


def test_dunder_fails(validator):
    result = validator.validate("__class__")
    assert result.valid is False
