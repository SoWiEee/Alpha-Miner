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
_TS_FUNC_NAMES_RE = re.compile(
    r"\b(ts_mean|ts_std|ts_delta|ts_rank|ts_corr|ts_covariance|"
    r"ts_max|ts_min|ts_median|ts_argmax|ts_argmin|adv)\s*\("
)
_BLACKLIST_WORD_RE = re.compile(
    r"\b(?:import|eval|exec|compile|globals|locals|vars|dir|getattr|setattr)\b"
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
        for match in _TS_FUNC_NAMES_RE.finditer(expression):
            # Scan from '(' to find top-level args (ignoring nested parens)
            start = match.end() - 1  # position of '('
            depth = 0
            args: list[str] = []
            arg_start = start + 1
            for i in range(start, len(expression)):
                ch = expression[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        args.append(expression[arg_start:i].strip())
                        break
                elif ch == "," and depth == 1:
                    args.append(expression[arg_start:i].strip())
                    arg_start = i + 1
            # Check if last arg is an integer window
            if args:
                last_arg = args[-1].strip()
                if re.fullmatch(r"\d+", last_arg):
                    window = int(last_arg)
                    if window < 1 or window > 252:
                        return ValidationResult(
                            False,
                            f"Window argument out of range [1, 252]: {window}",
                        )
        return ValidationResult(True)

    def _check_blacklist(self, expression: str) -> ValidationResult:
        if "__" in expression:
            return ValidationResult(False, "Forbidden token: '__'")
        m = _BLACKLIST_WORD_RE.search(expression)
        if m:
            return ValidationResult(False, f"Forbidden token: {m.group()!r}")
        return ValidationResult(True)
