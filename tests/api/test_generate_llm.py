"""Tests for POST /generate/llm (Phase 4 LLM generation endpoint)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.core.models import AlphaCandidate, AlphaSource, compute_alpha_id
from backend.models.alpha import Alpha
from backend.models.correlation import Run


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm_candidate(expression: str, decay: int = 0, neutralization: str = "subindustry") -> AlphaCandidate:
    """Build a valid AlphaCandidate with source=LLM matching LLMGenerator defaults."""
    alpha_id = compute_alpha_id(
        expression=expression,
        universe="TOP3000",
        region="USA",
        delay=1,
        decay=decay,
        neutralization=neutralization,
        truncation=0.08,
        pasteurization="off",
        nan_handling="off",
    )
    return AlphaCandidate(
        id=alpha_id,
        expression=expression,
        universe="TOP3000",
        region="USA",
        delay=1,
        decay=decay,
        neutralization=neutralization,
        truncation=0.08,
        pasteurization="off",
        nan_handling="off",
        source=AlphaSource.LLM,
        parent_id=None,
        rationale="Test rationale.",
        created_at=datetime.now(timezone.utc),
        filter_skipped=False,
    )


def _fake_settings(api_key: str = "test-api-key", max_calls: int = 20):
    s = MagicMock()
    s.CLAUDE_API_KEY = api_key
    s.LLM_MAX_CALLS_PER_DAY = max_calls
    s.DIVERSITY_THRESHOLD = 0.7
    return s


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGenerateLLMEndpoint:
    def test_returns_503_when_api_key_missing(self, client):
        """POST /generate/llm returns 503 when CLAUDE_API_KEY is empty."""
        with patch("backend.api.generate.get_settings") as mock_settings:
            mock_settings.return_value = _fake_settings(api_key="")
            r = client.post("/api/generate/llm", json={})
        assert r.status_code == 503
        assert "CLAUDE_API_KEY" in r.json()["detail"]

    def test_returns_429_when_daily_limit_reached(self, client, test_db):
        """POST /generate/llm returns 429 when daily limit is already reached."""
        # Insert LLM run rows for today so limit is hit
        today = datetime.now(timezone.utc)
        for _ in range(3):
            run = Run(
                mode="llm",
                candidates_gen=0,
                candidates_pass=0,
                started_at=today,
                finished_at=today,
            )
            test_db.add(run)
        test_db.commit()

        with patch("backend.api.generate.get_settings") as mock_settings:
            mock_settings.return_value = _fake_settings(api_key="test-key", max_calls=3)
            r = client.post("/api/generate/llm", json={})
        assert r.status_code == 429
        assert "limit" in r.json()["detail"].lower()

    def test_returns_201_with_valid_llm_response(self, client):
        """POST /generate/llm with mocked generator returns 201 and valid LLMResponse."""
        candidates = [
            _make_llm_candidate("rank(close)"),
            _make_llm_candidate("rank(open)"),
        ]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={"n": 2})

        assert r.status_code == 201
        data = r.json()
        assert "run_id" in data
        assert "candidates_generated" in data
        assert "candidates_passed_validation" in data
        assert "candidates_passed_diversity" in data
        assert "candidates_skipped_filter" in data
        assert "candidates_rejected_diversity" in data
        assert "candidates" in data

    def test_run_id_matches_run_with_mode_llm(self, client, test_db):
        """run_id in response corresponds to a Run row with mode='llm'."""
        candidates = [_make_llm_candidate("rank(close)")]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={})

        assert r.status_code == 201
        run_id = r.json()["run_id"]
        run = test_db.get(Run, run_id)
        assert run is not None
        assert run.mode == "llm"

    def test_candidates_have_source_llm(self, client):
        """Candidates in response have source='llm'."""
        candidates = [
            _make_llm_candidate("rank(close)"),
            _make_llm_candidate("-rank(close)"),
        ]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={})

        assert r.status_code == 201
        for cand in r.json()["candidates"]:
            assert cand["source"] == "llm"

    def test_theme_sets_llm_theme_on_run(self, client, test_db):
        """POST /generate/llm with theme sets llm_theme on the Run row."""
        candidates = [_make_llm_candidate("rank(close)")]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={"theme": "momentum"})

        assert r.status_code == 201
        run_id = r.json()["run_id"]
        run = test_db.get(Run, run_id)
        assert run is not None
        assert run.llm_theme == "momentum"

    def test_two_calls_create_two_run_rows(self, client, test_db):
        """Two POST /generate/llm calls both succeed and create 2 run rows."""
        candidates = [_make_llm_candidate("rank(close)")]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings(max_calls=20)
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r1 = client.post("/api/generate/llm", json={})
            r2 = client.post("/api/generate/llm", json={})

        assert r1.status_code == 201
        assert r2.status_code == 201

        llm_runs = test_db.query(Run).filter(Run.mode == "llm").all()
        assert len(llm_runs) == 2

    def test_empty_pool_context_still_works(self, client):
        """POST /generate/llm works when there are no completed simulations."""
        # No DB records — empty pool context
        candidates = [_make_llm_candidate("rank(close)")]

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = candidates
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={})

        assert r.status_code == 201
        data = r.json()
        assert data["candidates_generated"] == 1

    def test_invalid_expression_not_saved(self, client):
        """Candidates with invalid expressions are filtered out and not saved."""
        # Create one valid and one invalid (validator rejects it)
        valid = _make_llm_candidate("rank(close)")
        invalid = _make_llm_candidate("invalid_func(close)")
        # Manually override expression to something the validator will reject
        invalid.expression = "import(close)"

        with patch("backend.api.generate.get_settings") as mock_settings, \
             patch("backend.api.generate.LLMGenerator") as mock_gen_cls:
            mock_settings.return_value = _fake_settings()
            mock_instance = MagicMock()
            mock_instance.generate.return_value = [valid, invalid]
            mock_gen_cls.return_value = mock_instance

            r = client.post("/api/generate/llm", json={})

        assert r.status_code == 201
        data = r.json()
        assert data["candidates_generated"] == 2
        assert data["candidates_passed_validation"] == 1
        assert len(data["candidates"]) == 1

    def test_no_api_key_empty_string_returns_503(self, client):
        """CLAUDE_API_KEY set to empty string returns 503."""
        with patch("backend.api.generate.get_settings") as mock_settings:
            mock_settings.return_value = _fake_settings(api_key="")
            r = client.post("/api/generate/llm", json={"n": 5})
        assert r.status_code == 503

    def test_limit_exactly_reached_returns_429(self, client, test_db):
        """When run count equals limit exactly, the next call returns 429."""
        today = datetime.now(timezone.utc)
        # Insert exactly `max_calls` runs
        max_calls = 2
        for _ in range(max_calls):
            run = Run(
                mode="llm",
                candidates_gen=0,
                candidates_pass=0,
                started_at=today,
                finished_at=today,
            )
            test_db.add(run)
        test_db.commit()

        with patch("backend.api.generate.get_settings") as mock_settings:
            mock_settings.return_value = _fake_settings(api_key="key", max_calls=max_calls)
            r = client.post("/api/generate/llm", json={})

        assert r.status_code == 429
