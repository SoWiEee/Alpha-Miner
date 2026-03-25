from backend.core.models import AlphaSource


def test_alpha_create_defaults():
    from backend.schemas.alpha import AlphaCreate
    s = AlphaCreate(expression="rank(close)")
    assert s.universe == "TOP3000"
    assert s.region == "USA"
    assert s.delay == 1
    assert s.decay == 0
    assert s.neutralization == "subindustry"
    assert s.truncation == 0.08
    assert s.source == AlphaSource.MANUAL
    assert s.parent_id is None


def test_alpha_read_from_orm(test_db):
    from datetime import datetime
    from backend.models.alpha import Alpha
    from backend.schemas.alpha import AlphaRead

    orm = Alpha(
        id="xyz789", expression="rank(open)", universe="TOP3000",
        region="USA", delay=1, decay=0, neutralization="subindustry",
        truncation=0.08, pasteurization="off", nan_handling="off",
        source="seed", filter_skipped=False, created_at=datetime.utcnow(),
    )
    test_db.add(orm)
    test_db.commit()
    test_db.refresh(orm)
    schema = AlphaRead.model_validate(orm)
    assert schema.id == "xyz789"
    assert schema.source == AlphaSource.SEED


def test_mutate_request_defaults():
    from backend.schemas.alpha import MutateRequest
    r = MutateRequest()
    assert r.alpha_id is None
    assert set(r.strategies) == {"lookback", "operator", "rank_wrap", "config"}
