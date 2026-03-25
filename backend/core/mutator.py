import re
from backend.core.models import AlphaCandidate, AlphaSource
from backend.core.expression_validator import ExpressionValidator

_validator = ExpressionValidator()

# Matches the trailing integer window in ts_* and adv() calls
_WINDOW_RE = re.compile(
    r"((?:ts_mean|ts_std|ts_delta|ts_rank|ts_corr|ts_covariance|"
    r"ts_max|ts_min|ts_median|ts_argmax|ts_argmin|adv)\s*\([^()]*,\s*)(\d+)(\s*\))"
)


class TemplateMutator:
    LOOKBACK_VARIANTS: list[int] = [5, 10, 20, 40, 60]
    OPERATOR_SWAPS: dict[str, list[str]] = {
        "ts_mean": ["ts_median", "ts_max", "ts_min", "ts_std"],
        "ts_corr": ["ts_covariance"],
    }
    CONFIG_VARIANTS: dict[str, list] = {
        "neutralization": ["market", "sector", "subindustry"],
        "decay": [0, 4, 8],
        "truncation": [0.05, 0.08, 0.10],
    }

    # ── public API ──────────────────────────────────────────────────

    def mutate_lookback(self, alpha: AlphaCandidate) -> list[AlphaCandidate]:
        if not _WINDOW_RE.search(alpha.expression):
            return []
        results = []
        for window in self.LOOKBACK_VARIANTS:
            new_expr = _WINDOW_RE.sub(
                lambda m, w=window: m.group(1) + str(w) + m.group(3),
                alpha.expression,
            )
            if new_expr != alpha.expression:
                results.append(self._make_mutation(alpha, new_expr))
        return results

    def mutate_operator(self, alpha: AlphaCandidate) -> list[AlphaCandidate]:
        results = []
        for old_op, new_ops in self.OPERATOR_SWAPS.items():
            if f"{old_op}(" not in alpha.expression:
                continue
            for new_op in new_ops:
                new_expr = alpha.expression.replace(f"{old_op}(", f"{new_op}(")
                if new_expr != alpha.expression:
                    results.append(self._make_mutation(alpha, new_expr))
        return results

    def mutate_rank_wrap(self, alpha: AlphaCandidate) -> list[AlphaCandidate]:
        return [
            self._make_mutation(alpha, f"rank({alpha.expression})"),
            self._make_mutation(alpha, f"zscore({alpha.expression})"),
        ]

    def mutate_config(self, alpha: AlphaCandidate) -> list[AlphaCandidate]:
        results = []
        for neut in self.CONFIG_VARIANTS["neutralization"]:
            if neut != alpha.neutralization:
                results.append(self._make_mutation(alpha, alpha.expression, neutralization=neut))
        for decay in self.CONFIG_VARIANTS["decay"]:
            if decay != alpha.decay:
                results.append(self._make_mutation(alpha, alpha.expression, decay=decay))
        for trunc in self.CONFIG_VARIANTS["truncation"]:
            if abs(trunc - alpha.truncation) > 1e-9:
                results.append(self._make_mutation(alpha, alpha.expression, truncation=trunc))
        return results

    def mutate_all(self, alpha: AlphaCandidate) -> list[AlphaCandidate]:
        raw = (
            self.mutate_lookback(alpha)
            + self.mutate_operator(alpha)
            + self.mutate_rank_wrap(alpha)
            + self.mutate_config(alpha)
        )
        seen: dict[str, AlphaCandidate] = {}
        for candidate in raw:
            if candidate.id not in seen:
                validation = _validator.validate(candidate.expression)
                if validation.valid:
                    seen[candidate.id] = candidate
        return list(seen.values())

    # ── helpers ─────────────────────────────────────────────────────

    def _make_mutation(
        self,
        parent: AlphaCandidate,
        new_expression: str,
        **config_overrides,
    ) -> AlphaCandidate:
        return AlphaCandidate.create(
            new_expression,
            AlphaSource.MUTATION,
            universe=config_overrides.get("universe", parent.universe),
            region=config_overrides.get("region", parent.region),
            delay=config_overrides.get("delay", parent.delay),
            decay=config_overrides.get("decay", parent.decay),
            neutralization=config_overrides.get("neutralization", parent.neutralization),
            truncation=config_overrides.get("truncation", parent.truncation),
            pasteurization=config_overrides.get("pasteurization", parent.pasteurization),
            nan_handling=config_overrides.get("nan_handling", parent.nan_handling),
            parent_id=parent.id,
        )
