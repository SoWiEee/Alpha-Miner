import pytest
from datetime import datetime
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.models.correlation import Run


def test_alpha_orm_insert_and_fetch(test_db):
    alpha = Alpha(
        id="abc123", expression="rank(close)", universe="TOP3000",
        region="USA", delay=1, decay=0, neutralization="subindustry",
        truncation=0.08, pasteurization="off", nan_handling="off",
        source="seed", filter_skipped=False, created_at=datetime.utcnow(),
    )
    test_db.add(alpha)
    test_db.commit()
    fetched = test_db.get(Alpha, "abc123")
    assert fetched is not None
    assert fetched.expression == "rank(close)"
    assert fetched.source == "seed"


def test_simulation_orm_insert(test_db):
    alpha = Alpha(
        id="abc123", expression="rank(close)", universe="TOP3000",
        region="USA", delay=1, decay=0, neutralization="subindustry",
        truncation=0.08, pasteurization="off", nan_handling="off",
        source="seed", filter_skipped=False, created_at=datetime.utcnow(),
    )
    test_db.add(alpha)
    test_db.commit()
    sim = Simulation(alpha_id="abc123", status="pending")
    test_db.add(sim)
    test_db.commit()
    assert sim.id is not None
    assert sim.status == "pending"


def test_run_orm_insert(test_db):
    run = Run(mode="mutation", candidates_gen=10, candidates_pass=8)
    test_db.add(run)
    test_db.commit()
    assert run.id is not None
    assert run.mode == "mutation"
