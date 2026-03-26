"""Submit queue API — manual export, result import, and auto-submission."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.models import AlphaCandidate, AlphaSource
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.schemas.simulation import EnqueueRequest, ResultImportRequest, SimulationRead
from backend.services.wq_interface import (
    AutoAPIClient,
    BiometricAuthRequired,
    ManualQueueClient,
    SimulationFailed,
    SimulationTimeout,
)

router = APIRouter(tags=["submit"])
_manual_client = ManualQueueClient()


def _get_auto_client() -> AutoAPIClient:
    s = get_settings()
    return AutoAPIClient(
        email=s.WQ_EMAIL,
        password=s.WQ_PASSWORD.get_secret_value(),
        poll_interval=s.WQ_POLL_INTERVAL_SEC,
        poll_timeout=s.WQ_POLL_TIMEOUT_SEC,
    )


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


# ── Enqueue alpha for manual submission ──────────────────────────────────────

@router.post("/submit/queue", response_model=SimulationRead, status_code=201)
async def enqueue_alpha(body: EnqueueRequest, db: Session = Depends(get_db)):
    alpha_orm = db.get(Alpha, body.alpha_id)
    if alpha_orm is None:
        raise HTTPException(status_code=404, detail="Alpha not found")

    existing = (
        db.query(Simulation)
        .filter(Simulation.alpha_id == body.alpha_id, Simulation.status == "pending")
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A pending simulation already exists for this alpha")

    alpha = _orm_to_candidate(alpha_orm)
    sim_id = await _manual_client.submit(alpha, db)
    sim = db.get(Simulation, int(sim_id))
    return SimulationRead.model_validate(sim)


# ── List simulation queue ─────────────────────────────────────────────────────

@router.get("/submit/queue", response_model=list[SimulationRead])
def get_queue(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Simulation)
    if status:
        q = q.filter(Simulation.status == status)
    return q.order_by(Simulation.submitted_at.desc()).all()


# ── Export pending alphas ─────────────────────────────────────────────────────

@router.get("/submit/export")
def export_queue(format: str = "json", db: Session = Depends(get_db)):
    if format == "csv":
        csv_data = _manual_client.export_pending(db, format="csv")
        return Response(content=csv_data, media_type="text/csv")
    return _manual_client.export_pending(db, format="json")


# ── Import manual result ──────────────────────────────────────────────────────

@router.post("/submit/result", response_model=SimulationRead)
def import_result(body: ResultImportRequest, db: Session = Depends(get_db)):
    if body.simulation_id is not None:
        sim = db.get(Simulation, body.simulation_id)
        if sim is None:
            raise HTTPException(status_code=404, detail="No matching simulation found")
    else:
        # First try to find a pending simulation
        sim = (
            db.query(Simulation)
            .filter(Simulation.alpha_id == body.alpha_id)
            .filter(Simulation.status == "pending")
            .order_by(Simulation.submitted_at.desc())
            .first()
        )
        if sim is None:
            # Also allow re-importing results for failed simulations,
            # and check for completed ones to raise 409 if needed
            sim = (
                db.query(Simulation)
                .filter(Simulation.alpha_id == body.alpha_id)
                .filter(Simulation.status.in_(["failed", "completed"]))
                .order_by(Simulation.submitted_at.desc())
                .first()
            )
            if sim is None:
                raise HTTPException(status_code=404, detail="No matching simulation found")

    if sim.status == "completed":
        raise HTTPException(status_code=409, detail="Simulation already completed")

    sim.sharpe = body.sharpe
    sim.fitness = body.fitness
    sim.returns = body.returns
    sim.turnover = body.turnover
    sim.passed = body.passed
    sim.notes = body.notes
    sim.status = "completed"
    sim.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sim)
    return SimulationRead.model_validate(sim)


# ── Auto-submit via WQ Brain API ──────────────────────────────────────────────

@router.post("/submit/auto/{alpha_id}", response_model=SimulationRead)
async def auto_submit(alpha_id: str, db: Session = Depends(get_db)):
    alpha_orm = db.get(Alpha, alpha_id)
    if alpha_orm is None:
        raise HTTPException(status_code=404, detail="Alpha not found")

    existing = (
        db.query(Simulation)
        .filter(Simulation.alpha_id == alpha_id, Simulation.status == "submitted")
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A submitted simulation already exists for this alpha")

    alpha = _orm_to_candidate(alpha_orm)
    auto_client = _get_auto_client()

    try:
        sim_id = await auto_client.submit(alpha, db)
    except BiometricAuthRequired as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except SimulationTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except SimulationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    sim = db.get(Simulation, int(sim_id))
    return SimulationRead.model_validate(sim)
