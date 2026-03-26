"""LLM Generator (Claude API) — Phase 4 implementation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic

from backend.config import get_settings
from backend.core.models import AlphaCandidate, AlphaSource, compute_alpha_id

_VALID_NEUTRALIZATIONS = frozenset({"none", "market", "sector", "industry", "subindustry"})

_SYSTEM_PROMPT = """\
You are a quantitative finance researcher specializing in formulaic alpha expressions
for the WorldQuant BRAIN platform (IQC competition, USA TOP3000 equity universe).

## WQ Fast Expression Syntax

Expressions operate on cross-sectional stock panels. Available data fields:
  close, open, high, low, volume  — daily OHLCV
  returns                          — daily return (close/prev_close - 1)
  adv{N}                           — avg daily dollar volume, e.g. adv20
  cap                              — market capitalization
  vwap                             — volume-weighted average price

Cross-sectional functions (operate across all stocks each day):
  rank(x)                          — percentile rank [0, 1]
  zscore(x)                        — z-score across stocks
  scale(x)                         — normalize: sum(abs(x)) = 1
  IndNeutralize(x, IndClass.X)     — neutralize by sector/industry/subindustry

Time-series functions (operate over time per stock, n = lookback window in days):
  ts_mean(x, n)    ts_std(x, n)    ts_delta(x, n)    ts_rank(x, n)
  ts_corr(x, y, n) ts_max(x, n)   ts_min(x, n)      ts_median(x, n)
  ts_argmax(x, n)  ts_argmin(x, n)

Math: log(x), abs(x), sign(x), and arithmetic +, -, *, /

## Output Format

Return ONLY a JSON array. Each element must have:
  "expression"    : string   — WQ Fast Expression (required)
  "neutralization": string   — "none"|"market"|"sector"|"industry"|"subindustry" (optional)
  "decay"         : integer  — 0 to 20 (optional)
  "rationale"     : string   — one-sentence alpha hypothesis (required)

Example:
[
  {
    "expression": "-rank(ts_delta(close, 5))",
    "neutralization": "subindustry",
    "decay": 4,
    "rationale": "Short-term mean reversion: stocks that fell most in 5 days tend to bounce."
  }
]

CRITICAL: Respond with ONLY the JSON array — no explanation, no markdown fences, no preamble.\
"""


@dataclass
class PoolContext:
    top_alphas: list[dict] = field(default_factory=list)
    total_pool_size: int = 0


class LLMGenerator:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or get_settings().CLAUDE_MODEL

    def generate(
        self,
        pool_context: PoolContext,
        theme: str | None = None,
        n: int = 10,
    ) -> list[AlphaCandidate]:
        """Call Claude once. Returns raw AlphaCandidates (not yet validated or diversity-filtered)."""
        user_prompt = self._build_user_prompt(pool_context, theme, n)
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text if message.content else ""
        parsed = self._parse_response(raw)

        defaults = {
            "universe": "TOP3000",
            "region": "USA",
            "delay": 1,
            "decay": 0,
            "neutralization": "subindustry",
            "truncation": 0.08,
            "pasteurization": "off",
            "nan_handling": "off",
        }
        candidates = []
        for d in parsed:
            cand = self._dict_to_candidate(d, defaults)
            if cand is not None:
                candidates.append(cand)
        return candidates

    def _build_user_prompt(self, pool_context: PoolContext, theme: str | None, n: int) -> str:
        if pool_context.top_alphas:
            lines = []
            for a in pool_context.top_alphas:
                sharpe = f"{a.get('sharpe', 0.0):.2f}" if a.get("sharpe") is not None else "N/A"
                fitness = f"{a.get('fitness', 0.0):.2f}" if a.get("fitness") is not None else "N/A"
                returns = f"{a.get('returns', 0.0):.3f}" if a.get("returns") is not None else "N/A"
                turnover = f"{a.get('turnover', 0.0):.3f}" if a.get("turnover") is not None else "N/A"
                lines.append(
                    f'- expression="{a["expression"]}"  '
                    f"sharpe={sharpe}  fitness={fitness}  "
                    f"returns={returns}  turnover={turnover}"
                )
            pool_summary = "\n".join(lines)
        else:
            pool_summary = "(pool is empty — generate diverse foundational alphas)"

        theme_line = f"3. Focus on this theme: {theme}" if theme else ""

        return (
            f"## Current Alpha Pool\n\n"
            f"Pool size: {pool_context.total_pool_size} alphas with completed simulations.\n\n"
            f"Top alphas by Fitness:\n{pool_summary}\n\n"
            f"(Higher Fitness = better. Fitness = sqrt(|Returns| / max(Turnover, 0.125)) * Sharpe)\n\n"
            f"## Task\n\n"
            f"Generate {n} alpha expressions that are:\n"
            f"1. Syntactically valid WQ Fast Expressions\n"
            f"2. Conceptually different from the alphas listed above (avoid similar logic)\n"
            f"{theme_line}\n\n"
            f"Prefer subindustry neutralization and low-turnover signals (Fitness > 1.0 target)."
        )

    def _parse_response(self, raw: str) -> list[dict]:
        # Try direct parse
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return [d for d in result if isinstance(d, dict) and d.get("expression")]
        except json.JSONDecodeError:
            pass

        # Try extracting [...] block
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return [d for d in result if isinstance(d, dict) and d.get("expression")]
            except json.JSONDecodeError:
                pass

        return []

    def _dict_to_candidate(self, d: dict, defaults: dict) -> AlphaCandidate | None:
        try:
            expression = d["expression"].strip()
            if not expression:
                return None

            neutralization = str(d.get("neutralization", defaults["neutralization"])).lower()
            if neutralization not in _VALID_NEUTRALIZATIONS:
                neutralization = defaults["neutralization"]

            try:
                decay = max(0, min(20, int(d.get("decay", defaults["decay"]))))
            except (ValueError, TypeError):
                decay = defaults["decay"]

            rationale = d.get("rationale", None)

            # Use the canonical compute_alpha_id function (same as all other alpha sources)
            alpha_id = compute_alpha_id(
                expression=expression,
                universe=defaults["universe"],
                region=defaults["region"],
                delay=defaults["delay"],
                decay=decay,
                neutralization=neutralization,
                truncation=defaults["truncation"],
                pasteurization=defaults["pasteurization"],
                nan_handling=defaults["nan_handling"],
            )

            return AlphaCandidate(
                id=alpha_id,
                expression=expression,
                universe=defaults["universe"],
                region=defaults["region"],
                delay=defaults["delay"],
                decay=decay,
                neutralization=neutralization,
                truncation=defaults["truncation"],
                pasteurization=defaults["pasteurization"],
                nan_handling=defaults["nan_handling"],
                source=AlphaSource.LLM,
                parent_id=None,
                rationale=rationale,
                created_at=datetime.now(timezone.utc),
                filter_skipped=False,
            )
        except Exception:
            return None
