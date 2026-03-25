import pytest
from backend.core.models import AlphaSource


def test_health_check(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_list_alphas_empty(client):
    r = client.get("/api/alphas")
    assert r.status_code == 200
    assert r.json() == []


def test_create_alpha(client):
    payload = {"expression": "rank(close)"}
    r = client.post("/api/alphas", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["expression"] == "rank(close)"
    assert data["source"] == "manual"
    assert len(data["id"]) == 64


def test_create_alpha_idempotent(client):
    payload = {"expression": "rank(close)"}
    r1 = client.post("/api/alphas", json=payload)
    r2 = client.post("/api/alphas", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 200  # idempotent
    assert r1.json()["id"] == r2.json()["id"]


def test_get_alpha_by_id(client):
    payload = {"expression": "rank(close)"}
    created = client.post("/api/alphas", json=payload).json()
    r = client.get(f"/api/alphas/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_alpha_not_found(client):
    r = client.get("/api/alphas/nonexistent")
    assert r.status_code == 404


def test_list_alphas_after_create(client):
    client.post("/api/alphas", json={"expression": "rank(close)"})
    r = client.get("/api/alphas")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_list_alphas_filter_by_source(client):
    client.post("/api/alphas", json={"expression": "rank(close)", "source": "manual"})
    client.post("/api/alphas", json={"expression": "rank(open)", "source": "seed"})
    r = client.get("/api/alphas?source=manual")
    assert r.status_code == 200
    assert all(a["source"] == "manual" for a in r.json())


def test_delete_alpha(client):
    created = client.post("/api/alphas", json={"expression": "rank(close)"}).json()
    r = client.delete(f"/api/alphas/{created['id']}")
    assert r.status_code == 204
    # Confirm it's gone
    assert client.get(f"/api/alphas/{created['id']}").status_code == 404


def test_delete_alpha_with_child_returns_409(client):
    parent = client.post("/api/alphas", json={"expression": "rank(close)"}).json()
    client.post("/api/alphas", json={
        "expression": "rank(open)",
        "parent_id": parent["id"],
    })
    r = client.delete(f"/api/alphas/{parent['id']}")
    assert r.status_code == 409
