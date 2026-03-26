"""Diversity filter — expression evaluator + Spearman correlation filter."""
from __future__ import annotations

import re
from typing import Union

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy.orm import Session

from backend.core.models import AlphaCandidate


# ── Custom exception ─────────────────────────────────────────────────────────

class UnsupportedOperatorError(Exception):
    """Raised when an expression uses a field or function not locally evaluable."""


# ── Tokenizer ────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"(?P<NUMBER>\d+\.?\d*)"
    r"|(?P<IDENT>[a-zA-Z_]\w*)"
    r"|(?P<LPAREN>\()"
    r"|(?P<RPAREN>\))"
    r"|(?P<COMMA>,)"
    r"|(?P<OP>[+\-*/])"
    r"|(?P<WS>\s+)"
)

Token = tuple[str, str]  # (type, value)


def _tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(expr):
        kind = m.lastgroup
        if kind != "WS":
            tokens.append((kind, m.group()))  # type: ignore[arg-type]
    return tokens


# ── Recursive descent parser ──────────────────────────────────────────────────

_SUPPORTED_FIELDS = frozenset({"open", "high", "low", "close", "volume", "returns"})

_TS_OPS_1ARG = frozenset({"log", "abs", "sign", "rank", "zscore", "scale"})
_TS_OPS_2ARG = frozenset({
    "ts_mean", "ts_std", "ts_delta", "ts_delay",
    "ts_rank", "ts_max", "ts_min", "ts_sum",
})


class _Parser:
    def __init__(self, tokens: list[Token], panel: pd.DataFrame) -> None:
        self.tokens = tokens
        self.pos = 0
        self.panel = panel

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self, kind: str | None = None) -> Token:
        tok = self.tokens[self.pos]
        if kind and tok[0] != kind:
            raise ValueError(f"Expected {kind}, got {tok!r} at pos {self.pos}")
        self.pos += 1
        return tok

    # expr := term (('+' | '-') term)*
    def parse_expr(self) -> Union[pd.Series, float]:
        left = self.parse_term()
        while (tok := self.peek()) and tok[0] == "OP" and tok[1] in ("+", "-"):
            self.pos += 1
            right = self.parse_term()
            left = (left + right) if tok[1] == "+" else (left - right)
        return left

    # term := factor (('*' | '/') factor)*
    def parse_term(self) -> Union[pd.Series, float]:
        left = self.parse_factor()
        while (tok := self.peek()) and tok[0] == "OP" and tok[1] in ("*", "/"):
            self.pos += 1
            right = self.parse_factor()
            left = (left * right) if tok[1] == "*" else (left / right)
        return left

    # factor := '-' factor | primary
    def parse_factor(self) -> Union[pd.Series, float]:
        tok = self.peek()
        if tok and tok[0] == "OP" and tok[1] == "-":
            self.pos += 1
            return -self.parse_primary()
        return self.parse_primary()

    # primary := NUMBER | '(' expr ')' | IDENT ['(' arglist ')']
    def parse_primary(self) -> Union[pd.Series, float]:
        tok = self.peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")

        if tok[0] == "NUMBER":
            self.pos += 1
            return float(tok[1])

        if tok[0] == "LPAREN":
            self.pos += 1
            result = self.parse_expr()
            self.consume("RPAREN")
            return result

        if tok[0] == "IDENT":
            self.pos += 1
            name = tok[1]
            if self.peek() and self.peek()[0] == "LPAREN":
                return self._call_function(name)
            return self._get_field(name)

        raise ValueError(f"Unexpected token {tok!r} at pos {self.pos}")

    def _get_field(self, name: str) -> pd.Series:
        if name == "returns":
            return (
                self.panel["close"]
                .groupby(level="ticker")
                .pct_change()
            )
        if name in _SUPPORTED_FIELDS:
            return self.panel[name]
        raise UnsupportedOperatorError(f"Unknown field: {name!r}")

    def _call_function(self, name: str) -> pd.Series:
        self.consume("LPAREN")
        args: list[Union[pd.Series, float]] = [self.parse_expr()]
        while self.peek() and self.peek()[0] == "COMMA":
            self.pos += 1
            args.append(self.parse_expr())
        self.consume("RPAREN")
        return self._apply(name, args)

    def _apply(self, name: str, args: list[Union[pd.Series, float]]) -> pd.Series:
        s = args[0]
        if not isinstance(s, pd.Series):
            raise ValueError(f"First argument to {name!r} must be a Series, got {type(s)}")

        if name == "rank":
            return s.groupby(level="date").rank(pct=True)

        if name == "zscore":
            def _zs(x: pd.Series) -> pd.Series:
                std = x.std()
                return (x - x.mean()) / (std + 1e-8)
            return s.groupby(level="date").transform(_zs)

        if name == "scale":
            def _sc(x: pd.Series) -> pd.Series:
                return x / (x.abs().sum() + 1e-8)
            return s.groupby(level="date").transform(_sc)

        if name == "log":
            return np.log(s.abs() + 1e-8)

        if name == "abs":
            return s.abs()

        if name == "sign":
            return np.sign(s)

        # Two-argument time-series ops
        if name in _TS_OPS_2ARG:
            if len(args) < 2:
                raise ValueError(f"{name} requires 2 arguments")
            n = int(args[1])

            if name == "ts_mean":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=1).mean()
                )
            if name == "ts_std":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=2).std()
                )
            if name == "ts_delay":
                return s.groupby(level="ticker").transform(lambda x: x.shift(n))
            if name == "ts_delta":
                return s - s.groupby(level="ticker").transform(lambda x: x.shift(n))
            if name == "ts_rank":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=1).rank(pct=True)
                )
            if name == "ts_max":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=1).max()
                )
            if name == "ts_min":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=1).min()
                )
            if name == "ts_sum":
                return s.groupby(level="ticker").transform(
                    lambda x: x.rolling(n, min_periods=1).sum()
                )

        raise UnsupportedOperatorError(f"Unknown function: {name!r}")


# ── Public evaluator ──────────────────────────────────────────────────────────

class AlphaEvaluator:
    def evaluate(self, expression: str, panel: pd.DataFrame) -> pd.Series:
        """
        Evaluate a WQ Fast Expression on the proxy panel.
        Returns a Series indexed by (date, ticker).
        Raises UnsupportedOperatorError for unsupported fields/functions.
        """
        tokens = _tokenize(expression)
        parser = _Parser(tokens, panel)
        result = parser.parse_expr()
        if parser.pos != len(tokens):
            raise ValueError(f"Unexpected token: {tokens[parser.pos]!r}")
        if isinstance(result, (int, float)):
            # Scalar expression — broadcast to panel index
            return pd.Series(float(result), index=panel.index)
        return result


# ── Diversity filter ──────────────────────────────────────────────────────────

_MIN_VALID_POINTS = 10


class DiversityFilter:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def should_submit(
        self,
        candidate: AlphaCandidate,
        pool: list[AlphaCandidate],
        evaluator: AlphaEvaluator,
        panel: pd.DataFrame,
    ) -> tuple[bool, float]:
        """
        Returns (should_submit, max_correlation).
        - Unevaluable candidate → (True, nan)  [caller sets filter_skipped=True]
        - Empty pool or all pool members fail → (True, 0.0)
        - Otherwise → (max_corr <= threshold, max_corr)
        """
        try:
            cand_vals = evaluator.evaluate(candidate.expression, panel).dropna()
        except (UnsupportedOperatorError, ValueError):
            return True, float("nan")

        if len(cand_vals) < _MIN_VALID_POINTS:
            return True, float("nan")

        correlations: list[float] = []
        for member in pool:
            try:
                pool_vals = evaluator.evaluate(member.expression, panel)
            except (UnsupportedOperatorError, ValueError):
                continue
            # Align on common index
            aligned_cand, aligned_pool = cand_vals.align(pool_vals, join="inner")
            mask = aligned_cand.notna() & aligned_pool.notna()
            c = aligned_cand[mask]
            p = aligned_pool[mask]
            if len(c) < _MIN_VALID_POINTS:
                continue
            corr, _ = spearmanr(c.values, p.values)
            if not np.isnan(corr):
                correlations.append(abs(corr))

        if not correlations:
            return True, 0.0

        max_corr = max(correlations)
        return max_corr <= self.threshold, max_corr
