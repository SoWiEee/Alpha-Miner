import pytest
from backend.core.seed_pool import SEED_POOL
from backend.models.alpha import Alpha


def _load_seeds(client):
    """Helper: insert all seeds via POST /api/alphas."""
    for seed in SEED_POOL:
        client.post("/api/alphas", json={
            "expression": seed.expression,
            "source": "seed",
            "universe": seed.universe,
            "region": seed.region,
            "delay": seed.delay,
            "decay": seed.decay,
            "neutralization": seed.neutralization,
            "truncation": seed.truncation,
            "pasteurization": seed.pasteurization,
            "nan_handling": seed.nan_handling,
        })


def test_mutate_no_seeds_returns_empty_candidates(client):
    r = client.post("/api/generate/mutate", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["candidates"] == []
    assert data["candidates_generated"] == 0


def test_mutate_specific_alpha_not_found(client):
    r = client.post("/api/generate/mutate", json={"alpha_id": "nonexistent"})
    assert r.status_code == 404


def test_mutate_all_seeds_generates_candidates(client):
    _load_seeds(client)
    r = client.post("/api/generate/mutate", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["candidates_generated"] > 0
    assert data["candidates_passed_validation"] > 0
    assert len(data["candidates"]) == data["candidates_passed_validation"]
    assert data["run_id"] is not None


def test_mutate_specific_alpha(client):
    _load_seeds(client)
    # Get first seed's id
    alphas = client.get("/api/alphas?source=seed").json()
    seed_id = alphas[0]["id"]
    r = client.post("/api/generate/mutate", json={"alpha_id": seed_id})
    assert r.status_code == 200
    data = r.json()
    for candidate in data["candidates"]:
        assert candidate["parent_id"] == seed_id


def test_mutate_logs_run(client):
    _load_seeds(client)
    client.post("/api/generate/mutate", json={})
    r = client.get("/api/generate/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["mode"] == "mutation"
    assert runs[0]["candidates_gen"] > 0


def test_mutate_is_idempotent(client):
    _load_seeds(client)
    r1 = client.post("/api/generate/mutate", json={})
    r2 = client.post("/api/generate/mutate", json={})
    # Second run should produce 0 new candidates (all duplicates)
    assert r2.json()["candidates_passed_validation"] == 0


def test_gp_stub_returns_501(client):
    r = client.post("/api/generate/gp", json={})
    assert r.status_code == 501
