"""Tests for WQBrainInterface concrete implementations."""
import pytest
from backend.core.models import AlphaCandidate, AlphaSource
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.services.wq_interface import ManualQueueClient


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_alpha_orm(db, expression="-rank(ts_delta(close,5))") -> Alpha:
    """Insert a minimal Alpha row and return the ORM object."""
    from backend.core.models import compute_alpha_id
    alpha_id = compute_alpha_id(expression, "TOP3000", "USA", 1, 0, "subindustry", 0.08, "off", "off")
    orm = Alpha(
        id=alpha_id, expression=expression, universe="TOP3000", region="USA",
        delay=1, decay=0, neutralization="subindustry", truncation=0.08,
        pasteurization="off", nan_handling="off", source="seed",
        parent_id=None, rationale=None, filter_skipped=False,
    )
    db.add(orm)
    db.commit()
    db.refresh(orm)
    return orm


def _orm_to_candidate(orm: Alpha) -> AlphaCandidate:
    return AlphaCandidate(
        id=orm.id, expression=orm.expression, universe=orm.universe,
        region=orm.region, delay=orm.delay, decay=orm.decay,
        neutralization=orm.neutralization, truncation=orm.truncation,
        pasteurization=orm.pasteurization, nan_handling=orm.nan_handling,
        source=AlphaSource(orm.source), parent_id=orm.parent_id,
        rationale=orm.rationale, created_at=orm.created_at,
        filter_skipped=orm.filter_skipped,
    )


# ── ManualQueueClient ─────────────────────────────────────────────────────────

class TestManualQueueClient:
    def setup_method(self):
        self.client = ManualQueueClient()

    async def test_submit_creates_pending_simulation(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        sim_id = await self.client.submit(alpha, test_db)
        sim = test_db.get(Simulation, int(sim_id))
        assert sim is not None
        assert sim.alpha_id == alpha.id
        assert sim.status == "pending"
        assert sim.submitted_at is not None

    async def test_submit_returns_string_id(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        result = await self.client.submit(alpha, test_db)
        assert isinstance(result, str)
        assert int(result) > 0  # valid integer as string

    async def test_submit_duplicate_pending_raises(self, test_db):
        orm = _make_alpha_orm(test_db, expression="-rank(ts_mean(close,5))")
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)  # first submit — creates pending row
        with pytest.raises(ValueError, match="pending simulation"):
            await self.client.submit(alpha, test_db)  # second — should raise

    async def test_get_result_returns_simulation_read(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        sim_id = await self.client.submit(alpha, test_db)
        result = await self.client.get_result(sim_id, test_db)
        assert result is not None
        assert result.alpha_id == alpha.id
        assert result.status == "pending"

    async def test_get_result_returns_none_for_unknown_id(self, test_db):
        result = await self.client.get_result("99999", test_db)
        assert result is None

    async def test_export_pending_json_format(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)
        rows = self.client.export_pending(test_db, format="json")
        assert len(rows) == 1
        row = rows[0]
        assert row["alpha_id"] == alpha.id
        assert row["expression"] == alpha.expression
        assert "settings" in row
        s = row["settings"]
        assert s["region"] == "USA"
        assert s["universe"] == "TOP3000"
        assert s["delay"] == 1
        assert s["decay"] == 0

    async def test_export_pending_csv_format(self, test_db):
        orm = _make_alpha_orm(test_db)
        alpha = _orm_to_candidate(orm)
        await self.client.submit(alpha, test_db)
        csv_text = self.client.export_pending(test_db, format="csv")
        assert isinstance(csv_text, str)
        lines = csv_text.strip().splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert "alpha_id" in lines[0]
        assert "expression" in lines[0]

    async def test_export_pending_empty_json(self, test_db):
        rows = self.client.export_pending(test_db, format="json")
        assert rows == []

    async def test_export_pending_empty_csv(self, test_db):
        csv_text = self.client.export_pending(test_db, format="csv")
        assert isinstance(csv_text, str)
        lines = [l for l in csv_text.strip().splitlines() if l]
        assert len(lines) == 1  # header only
        assert "alpha_id" in lines[0]
