import re
from dataclasses import dataclass

ALLOWED_OPERATORS: frozenset[str] = frozenset({
    "ts_mean", "ts_std", "ts_delta", "ts_rank", "ts_corr", "ts_covariance",
    "ts_max", "ts_min", "ts_median", "ts_argmax", "ts_argmin",
    "rank", "zscore", "scale",
    "log", "abs", "sign",
    "IndNeutralize",
    "adv",
    # Data fields that appear as function calls in some WQ expressions
    "cap",
})

BLACKLISTED_TOKENS: frozenset[str] = frozenset({
    "import", "eval", "exec", "compile", "__",
    "globals", "locals", "vars", "dir", "getattr", "setattr",
    # Note: "open" intentionally excluded — it's a valid WQ price data field
})

# Matches function-call patterns: word(
_FUNC_CALL_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
# Matches trailing integer in a ts_ / adv call: , N)
_WINDOW_ARG_RE = re.compile(
    r"\b(?:ts_mean|ts_std|ts_delta|ts_rank|ts_corr|ts_covariance|"
    r"ts_max|ts_min|ts_median|ts_argmax|ts_argmin|adv)\b[^)]*,\s*(\d+)\s*\)"
)


@dataclass
class ValidationResult:
    valid: bool
    reason: str | None = None


class ExpressionValidator:
    def validate(self, expression: str) -> ValidationResult:
        result = self._check_parentheses(expression)
        if not result.valid:
            return result

        result = self._check_operator_whitelist(expression)
        if not result.valid:
            return result

        result = self._check_numeric_ranges(expression)
        if not result.valid:
            return result

        result = self._check_blacklist(expression)
        return result

    # ------------------------------------------------------------------
    def _check_parentheses(self, expression: str) -> ValidationResult:
        depth = 0
        for ch in expression:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return ValidationResult(False, "Unbalanced parentheses: unexpected ')'")
        if depth != 0:
            return ValidationResult(False, f"Unbalanced parentheses: {depth} unclosed '('")
        return ValidationResult(True)

    def _check_operator_whitelist(self, expression: str) -> ValidationResult:
        for match in _FUNC_CALL_RE.finditer(expression):
            name = match.group(1)
            if name not in ALLOWED_OPERATORS:
                return ValidationResult(False, f"Unknown operator: {name!r}")
        return ValidationResult(True)

    def _check_numeric_ranges(self, expression: str) -> ValidationResult:
        for match in _WINDOW_ARG_RE.finditer(expression):
            window = int(match.group(1))
            if window < 1 or window > 252:
                return ValidationResult(
                    False,
                    f"Window argument out of range [1, 252]: {window}",
                )
        return ValidationResult(True)

    def _check_blacklist(self, expression: str) -> ValidationResult:
        for token in BLACKLISTED_TOKENS:
            if token in expression:
                return ValidationResult(False, f"Forbidden token: {token!r}")
        return ValidationResult(True)
