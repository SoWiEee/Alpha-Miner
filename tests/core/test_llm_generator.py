"""Tests for LLMGenerator (Phase 4)."""
from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, patch

import pytest

from backend.core.llm_generator import LLMGenerator, PoolContext
from backend.core.models import AlphaCandidate, AlphaSource


def _make_generator() -> LLMGenerator:
    """Create an LLMGenerator with a mocked Anthropic client."""
    with patch("backend.core.llm_generator.anthropic.Anthropic"):
        gen = LLMGenerator(api_key="test-key", model="claude-test-model")
    return gen


def _make_mock_message(text: str) -> MagicMock:
    content_item = MagicMock()
    content_item.text = text
    msg = MagicMock()
    msg.content = [content_item]
    return msg


# ── generate() tests ──────────────────────────────────────────────────────────

class TestGenerate:
    def test_generate_calls_messages_create_once(self):
        """generate() calls messages.create exactly once with correct model."""
        with patch("backend.core.llm_generator.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            gen = LLMGenerator(api_key="test-key", model="my-model")

            response_text = json.dumps([
                {"expression": "rank(close)", "rationale": "Test alpha."}
            ])
            mock_client.messages.create.return_value = _make_mock_message(response_text)

            pool_context = PoolContext(top_alphas=[], total_pool_size=0)
            gen.generate(pool_context, n=5)

            mock_client.messages.create.assert_called_once()
            call_kwargs = mock_client.messages.create.call_args
            assert call_kwargs.kwargs["model"] == "my-model"

    def test_generate_returns_alpha_candidates_from_valid_response(self):
        """generate() correctly parses a well-formed JSON response."""
        with patch("backend.core.llm_generator.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            gen = LLMGenerator(api_key="test-key", model="my-model")

            response_text = json.dumps([
                {"expression": "rank(close)", "rationale": "Mean rev.", "decay": 4, "neutralization": "sector"},
                {"expression": "-ts_delta(close, 5)", "rationale": "Momentum."},
            ])
            mock_client.messages.create.return_value = _make_mock_message(response_text)

            pool_context = PoolContext(top_alphas=[], total_pool_size=0)
            results = gen.generate(pool_context, n=2)

            assert len(results) == 2
            assert all(isinstance(r, AlphaCandidate) for r in results)
            expressions = {r.expression for r in results}
            assert "rank(close)" in expressions
            assert "-ts_delta(close, 5)" in expressions

    def test_generate_returns_empty_list_for_unparseable_response(self):
        """generate() returns [] when the API response can't be parsed."""
        with patch("backend.core.llm_generator.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            gen = LLMGenerator(api_key="test-key", model="my-model")

            mock_client.messages.create.return_value = _make_mock_message("Sorry, I cannot help.")

            pool_context = PoolContext(top_alphas=[], total_pool_size=0)
            results = gen.generate(pool_context, n=3)

            assert results == []

    def test_generate_candidates_have_llm_source(self):
        """All returned AlphaCandidates have source=AlphaSource.LLM."""
        with patch("backend.core.llm_generator.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            gen = LLMGenerator(api_key="test-key", model="my-model")

            response_text = json.dumps([
                {"expression": "rank(close)", "rationale": "Test."},
                {"expression": "rank(open)", "rationale": "Test2."},
            ])
            mock_client.messages.create.return_value = _make_mock_message(response_text)

            pool_context = PoolContext(top_alphas=[], total_pool_size=0)
            results = gen.generate(pool_context, n=2)

            assert all(r.source == AlphaSource.LLM for r in results)


# ── _parse_response() tests ───────────────────────────────────────────────────

class TestParseResponse:
    def setup_method(self):
        self.gen = _make_generator()

    def test_parse_valid_json_array(self):
        """_parse_response() handles a valid JSON array string."""
        raw = json.dumps([
            {"expression": "rank(close)", "rationale": "Test."},
        ])
        result = self.gen._parse_response(raw)
        assert len(result) == 1
        assert result[0]["expression"] == "rank(close)"

    def test_parse_json_within_text(self):
        """_parse_response() extracts JSON from within larger text with preamble."""
        preamble = "Here are some alphas:\n"
        array = json.dumps([
            {"expression": "rank(close)", "rationale": "Test."},
        ])
        raw = preamble + array + "\n\nDone."
        result = self.gen._parse_response(raw)
        assert len(result) == 1
        assert result[0]["expression"] == "rank(close)"

    def test_parse_drops_entries_missing_expression_key(self):
        """_parse_response() drops entries without 'expression' key."""
        raw = json.dumps([
            {"expression": "rank(close)", "rationale": "Good."},
            {"rationale": "Missing expression."},
            {"expression": "", "rationale": "Empty expression."},
        ])
        result = self.gen._parse_response(raw)
        assert len(result) == 1
        assert result[0]["expression"] == "rank(close)"

    def test_parse_returns_empty_list_for_malformed_response(self):
        """_parse_response() returns [] for completely malformed response."""
        result = self.gen._parse_response("This is not JSON at all!!!")
        assert result == []

    def test_parse_returns_empty_for_empty_string(self):
        """_parse_response() returns [] for empty string."""
        result = self.gen._parse_response("")
        assert result == []


# ── _dict_to_candidate() tests ────────────────────────────────────────────────

class TestDictToCandidate:
    def setup_method(self):
        self.gen = _make_generator()
        self.defaults = {
            "universe": "TOP3000",
            "region": "USA",
            "delay": 1,
            "decay": 0,
            "neutralization": "subindustry",
            "truncation": 0.08,
            "pasteurization": "off",
            "nan_handling": "off",
        }

    def test_decay_clamped_to_0_when_negative(self):
        """_dict_to_candidate() clamps decay to 0 when given a negative value."""
        d = {"expression": "rank(close)", "decay": -5, "rationale": "Test."}
        cand = self.gen._dict_to_candidate(d, self.defaults)
        assert cand is not None
        assert cand.decay == 0

    def test_decay_clamped_to_20_when_over(self):
        """_dict_to_candidate() clamps decay to 20 when given a value > 20."""
        d = {"expression": "rank(close)", "decay": 99, "rationale": "Test."}
        cand = self.gen._dict_to_candidate(d, self.defaults)
        assert cand is not None
        assert cand.decay == 20

    def test_invalid_neutralization_falls_back_to_subindustry(self):
        """_dict_to_candidate() uses 'subindustry' fallback for invalid neutralization."""
        d = {"expression": "rank(close)", "neutralization": "invalid_value", "rationale": "Test."}
        cand = self.gen._dict_to_candidate(d, self.defaults)
        assert cand is not None
        assert cand.neutralization == "subindustry"

    def test_valid_neutralization_is_preserved(self):
        """_dict_to_candidate() preserves valid neutralization values."""
        for neut in ("none", "market", "sector", "industry", "subindustry"):
            d = {"expression": "rank(close)", "neutralization": neut, "rationale": "Test."}
            cand = self.gen._dict_to_candidate(d, self.defaults)
            assert cand is not None
            assert cand.neutralization == neut

    def test_missing_expression_returns_none(self):
        """_dict_to_candidate() returns None if 'expression' key is missing."""
        d = {"rationale": "No expression here."}
        cand = self.gen._dict_to_candidate(d, self.defaults)
        assert cand is None

    def test_empty_expression_returns_none(self):
        """_dict_to_candidate() returns None for empty expression string."""
        d = {"expression": "   ", "rationale": "Empty."}
        cand = self.gen._dict_to_candidate(d, self.defaults)
        assert cand is None

    def test_id_is_deterministic(self):
        """Same expression+config always produces the same ID."""
        d = {"expression": "rank(close)", "rationale": "Test."}
        cand1 = self.gen._dict_to_candidate(d, self.defaults)
        cand2 = self.gen._dict_to_candidate(d, self.defaults)
        assert cand1 is not None
        assert cand2 is not None
        assert cand1.id == cand2.id


# ── _build_user_prompt() tests ────────────────────────────────────────────────

class TestBuildUserPrompt:
    def setup_method(self):
        self.gen = _make_generator()

    def test_empty_pool_mentions_pool_is_empty(self):
        """_build_user_prompt() contains 'pool is empty' when pool has no top_alphas."""
        pool_context = PoolContext(top_alphas=[], total_pool_size=0)
        prompt = self.gen._build_user_prompt(pool_context, theme=None, n=10)
        assert "pool is empty" in prompt

    def test_theme_included_when_provided(self):
        """_build_user_prompt() includes the theme text when theme is given."""
        pool_context = PoolContext(top_alphas=[], total_pool_size=0)
        prompt = self.gen._build_user_prompt(pool_context, theme="momentum reversal", n=5)
        assert "momentum reversal" in prompt

    def test_theme_not_present_when_none(self):
        """_build_user_prompt() does not mention theme when theme is None."""
        pool_context = PoolContext(top_alphas=[], total_pool_size=0)
        prompt = self.gen._build_user_prompt(pool_context, theme=None, n=5)
        assert "Focus on this theme" not in prompt

    def test_top_alphas_formatted_in_prompt(self):
        """_build_user_prompt() includes expression from top_alphas."""
        pool_context = PoolContext(
            top_alphas=[
                {"expression": "rank(close)", "sharpe": 1.5, "fitness": 2.0, "returns": 0.05, "turnover": 0.3},
            ],
            total_pool_size=1,
        )
        prompt = self.gen._build_user_prompt(pool_context, theme=None, n=10)
        assert "rank(close)" in prompt
        assert "pool is empty" not in prompt
