import hashlib
import json
from datetime import datetime

import pytest

from backend.core.models import AlphaCandidate, AlphaSource, compute_alpha_id


def test_compute_alpha_id_is_deterministic():
    id1 = compute_alpha_id("rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    id2 = compute_alpha_id("rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    assert id1 == id2


def test_compute_alpha_id_differs_for_different_expressions():
    id1 = compute_alpha_id("rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    id2 = compute_alpha_id("rank(ts_delta(close, 10))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    assert id1 != id2


def test_compute_alpha_id_differs_for_different_config():
    id1 = compute_alpha_id("rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    id2 = compute_alpha_id("rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 4, "subindustry", 0.08, "off", "off")
    assert id1 != id2


def test_alpha_candidate_create_sets_id():
    alpha = AlphaCandidate.create("rank(ts_delta(close, 5))", AlphaSource.SEED)
    assert len(alpha.id) == 64  # SHA256 hex digest
    assert alpha.id == compute_alpha_id(
        "rank(ts_delta(close, 5))", "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off"
    )


def test_alpha_candidate_create_defaults():
    alpha = AlphaCandidate.create("rank(close)", AlphaSource.SEED)
    assert alpha.universe == "TOP3000"
    assert alpha.region == "USA"
    assert alpha.delay == 1
    assert alpha.decay == 0
    assert alpha.neutralization == "subindustry"
    assert alpha.truncation == 0.08
    assert alpha.pasteurization == "off"
    assert alpha.nan_handling == "off"
    assert alpha.parent_id is None
    assert alpha.filter_skipped is False


def test_alpha_source_enum_values():
    assert AlphaSource.SEED == "seed"
    assert AlphaSource.MUTATION == "mutation"
    assert AlphaSource.GP == "gp"
    assert AlphaSource.LLM == "llm"
    assert AlphaSource.MANUAL == "manual"
