"""GP Searcher — Phase 5 implementation."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from gplearn.fitness import make_fitness
from gplearn.genetic import SymbolicRegressor

from backend.core.models import AlphaCandidate, AlphaSource
from backend.services.diversity_filter import AlphaEvaluator, UnsupportedOperatorError


# ── Feature set ───────────────────────────────────────────────────────────────

FEATURE_EXPRESSIONS: list[tuple[str, str]] = [
    ("X0",  "close"),
    ("X1",  "open"),
    ("X2",  "high"),
    ("X3",  "low"),
    ("X4",  "volume"),
    ("X5",  "returns"),
    ("X6",  "ts_mean(close, 5)"),
    ("X7",  "ts_mean(close, 10)"),
    ("X8",  "ts_mean(close, 20)"),
    ("X9",  "ts_std(close, 5)"),
    ("X10", "ts_std(close, 20)"),
    ("X11", "ts_delta(close, 1)"),
    ("X12", "ts_delta(close, 5)"),
    ("X13", "ts_mean(volume, 5)"),
    ("X14", "ts_mean(volume, 20)"),
]

# ── Constants ─────────────────────────────────────────────────────────────────

N_MAX_DATES = 252
DATE_STEP = 5
MIN_VALID_ROWS = 100


# ── Custom IC fitness ─────────────────────────────────────────────────────────

def _ic_metric(y: np.ndarray, y_pred: np.ndarray, w: np.ndarray) -> float:
    if np.std(y_pred) < 1e-8:
        return 0.0
    corr, _ = spearmanr(y_pred, y)
    return float(abs(corr))


IC_FITNESS = make_fitness(function=_ic_metric, greater_is_better=True)


# ── Expression parser ─────────────────────────────────────────────────────────

class _GPParser:
    """Recursive descent parser for gplearn program strings."""

    def __init__(self, s: str, feature_names: list[str]):
        self.s = s.strip()
        self.pos = 0
        self.feature_names = feature_names

    def parse(self) -> str:
        result = self._parse_node()
        return result

    def _skip_ws(self) -> None:
        while self.pos < len(self.s) and self.s[self.pos] in " \t\n\r":
            self.pos += 1

    def _parse_node(self) -> str:
        self._skip_ws()
        if self.pos >= len(self.s):
            raise ValueError("Unexpected end of input")

        # Try X<int> — feature reference
        if self.s[self.pos] == "X" and self.pos + 1 < len(self.s) and self.s[self.pos + 1].isdigit():
            self.pos += 1  # skip 'X'
            num_start = self.pos
            while self.pos < len(self.s) and self.s[self.pos].isdigit():
                self.pos += 1
            idx = int(self.s[num_start:self.pos])
            if idx < len(self.feature_names):
                return self.feature_names[idx]
            return "close"

        # Try negative number literal: -digits[.digits]
        if self.s[self.pos] == "-":
            # Peek ahead — if followed by digits, it's a negative number
            peek = self.pos + 1
            if peek < len(self.s) and (self.s[peek].isdigit()):
                self.pos += 1  # skip '-'
                num_start = self.pos
                while self.pos < len(self.s) and (self.s[self.pos].isdigit() or self.s[self.pos] == "."):
                    self.pos += 1
                return "-" + self.s[num_start:self.pos]

        # Try positive number literal: digits[.digits]
        if self.s[self.pos].isdigit():
            num_start = self.pos
            while self.pos < len(self.s) and (self.s[self.pos].isdigit() or self.s[self.pos] == "."):
                self.pos += 1
            return self.s[num_start:self.pos]

        # Try function call: name(...)
        if self.s[self.pos].isalpha() or self.s[self.pos] == "_":
            name_start = self.pos
            while self.pos < len(self.s) and (self.s[self.pos].isalnum() or self.s[self.pos] == "_"):
                self.pos += 1
            name = self.s[name_start:self.pos]
            self._skip_ws()
            if self.pos < len(self.s) and self.s[self.pos] == "(":
                self.pos += 1  # consume '('
                args = self._parse_args()
                return self._convert(name, args)
            else:
                # bare identifier — shouldn't happen in gplearn output, raise
                raise ValueError(f"Unexpected identifier without call: {name!r}")

        raise ValueError(f"Unexpected character at pos {self.pos}: {self.s[self.pos]!r}")

    def _parse_args(self) -> list[str]:
        """Parse comma-separated args until matching ')'."""
        args: list[str] = []
        self._skip_ws()
        if self.pos < len(self.s) and self.s[self.pos] == ")":
            self.pos += 1
            return args
        args.append(self._parse_node())
        self._skip_ws()
        while self.pos < len(self.s) and self.s[self.pos] == ",":
            self.pos += 1
            args.append(self._parse_node())
            self._skip_ws()
        if self.pos >= len(self.s) or self.s[self.pos] != ")":
            raise ValueError(f"Expected ')' at pos {self.pos}")
        self.pos += 1  # consume ')'
        return args

    def _convert(self, name: str, args: list[str]) -> str:
        if name == "add":
            return f"({args[0]} + {args[1]})"
        if name == "sub":
            return f"({args[0]} - {args[1]})"
        if name == "mul":
            return f"({args[0]} * {args[1]})"
        if name == "div":
            return f"({args[0]} / {args[1]})"
        if name == "neg":
            return f"(-{args[0]})"
        if name == "log":
            return f"log({args[0]})"
        if name == "abs":
            return f"abs({args[0]})"
        raise ValueError(f"Unknown function: {name!r}")


# ── GPSearcher ────────────────────────────────────────────────────────────────

class GPSearcher:
    """Symbolic regression-based alpha searcher using gplearn."""

    def _build_dataset(
        self, panel: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """
        Build (X, y, feature_wq_names) from proxy panel.
        Returns float32 arrays; rows with NaN/inf are dropped.
        Raises ValueError if fewer than MIN_VALID_ROWS rows remain.
        """
        evaluator = AlphaEvaluator()

        # Evaluate features on the FULL panel (so rolling windows have proper history)
        feature_series: list[pd.Series] = []
        feature_wq_list: list[str] = []

        for name, wq_expr in FEATURE_EXPRESSIONS:
            try:
                s = evaluator.evaluate(wq_expr, panel)
                feature_series.append(s.rename(name))
                feature_wq_list.append(wq_expr)
            except (UnsupportedOperatorError, ValueError, Exception):
                # Skip this feature on any error
                pass

        # Compute y = next-day return on full panel
        y = (
            panel["close"]
            .groupby(level="ticker")
            .pct_change()
            .groupby(level="ticker")
            .shift(-1)
        )

        if not feature_series:
            raise ValueError("No features could be evaluated")

        # Subsample dates for speed
        all_dates = sorted(panel.index.get_level_values("date").unique())
        sampled_dates = all_dates[-N_MAX_DATES:][::DATE_STEP]
        sampled_set = set(sampled_dates)

        # Filter all series to subsampled dates
        mask = panel.index.get_level_values("date").isin(sampled_set)

        feature_series_sub = [s.loc[mask] for s in feature_series]
        y_sub = y.loc[mask]

        # Stack into DataFrame
        df = pd.concat(feature_series_sub, axis=1)
        df.columns = [f"X{i}" for i in range(len(feature_series_sub))]
        df["__y__"] = y_sub

        # Drop NaN and infinite rows
        df = df.replace([np.inf, -np.inf], np.nan).dropna()

        if len(df) < MIN_VALID_ROWS:
            raise ValueError(f"Insufficient data: {len(df)} rows after cleaning")

        X = df.drop(columns=["__y__"])
        y_col = df["__y__"]

        return (
            X.values.astype("float32"),
            y_col.values.astype("float32"),
            feature_wq_list,
        )

    def _to_wq_expression(self, program_str: str, feature_names: list[str]) -> str | None:
        """
        Convert a gplearn program string to a WQ Fast Expression.
        Returns None on any parse failure.
        """
        try:
            parser = _GPParser(program_str, feature_names)
            result = parser.parse()
            # Ensure we consumed the full string
            parser._skip_ws()
            if parser.pos != len(parser.s):
                return None
            return result
        except Exception:
            return None

    def run(
        self,
        panel: pd.DataFrame,
        n_results: int = 10,
        population_size: int = 500,
        generations: int = 20,
    ) -> list[AlphaCandidate]:
        """
        Run symbolic regression on proxy panel.
        Returns up to n_results AlphaCandidates (raw — not validated or diversity-filtered).
        """
        X, y, feature_names = self._build_dataset(panel)

        est = SymbolicRegressor(
            population_size=population_size,
            generations=generations,
            tournament_size=20,
            p_crossover=0.7,
            p_subtree_mutation=0.1,
            p_hoist_mutation=0.05,
            p_point_mutation=0.1,
            max_samples=0.9,
            parsimony_coefficient=0.001,
            metric=IC_FITNESS,
            function_set=("add", "sub", "mul", "div", "log", "abs", "neg"),
            n_jobs=1,
            random_state=42,
            verbose=0,
        )
        est.fit(X, y)

        # Extract top programs from final generation
        final_gen = est._programs[-1] if est._programs else []
        valid_progs = [
            p for p in final_gen
            if p is not None and hasattr(p, "fitness_") and p.fitness_ is not None
        ]
        valid_progs.sort(key=lambda p: p.fitness_, reverse=True)

        # Deduplicate by string representation
        seen_exprs: set[str] = set()
        top_programs = []
        for p in valid_progs:
            s = str(p)
            if s not in seen_exprs:
                seen_exprs.add(s)
                top_programs.append(p)
            if len(top_programs) >= n_results:
                break

        # Convert to AlphaCandidates
        candidates: list[AlphaCandidate] = []
        for p in top_programs:
            wq_expr = self._to_wq_expression(str(p), feature_names)
            if wq_expr is None:
                continue
            cand = AlphaCandidate.create(
                expression=wq_expr,
                source=AlphaSource.GP,
                rationale=f"GP IC={p.fitness_:.4f} gen={generations}",
            )
            candidates.append(cand)

        return candidates
