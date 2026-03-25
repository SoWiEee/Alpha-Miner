from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.core.models import AlphaSource, compute_alpha_id
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.schemas.alpha import AlphaCreate, AlphaRead

router = APIRouter(tags=["alphas"])



@router.get("/alphas", response_model=list[AlphaRead])
def list_alphas(
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Alpha)
    if source:
        q = q.filter(Alpha.source == source)
    return q.offset(offset).limit(limit).all()


@router.get("/alphas/{alpha_id}", response_model=AlphaRead)
def get_alpha(alpha_id: str, db: Session = Depends(get_db)):
    alpha = db.get(Alpha, alpha_id)
    if alpha is None:
        raise HTTPException(status_code=404, detail="Alpha not found")
    return alpha


@router.post("/alphas", response_model=AlphaRead, status_code=201)
def create_alpha(body: AlphaCreate, db: Session = Depends(get_db)):
    alpha_id = compute_alpha_id(
        body.expression, body.universe, body.region, body.delay,
        body.decay, body.neutralization, body.truncation,
        body.pasteurization, body.nan_handling,
    )
    existing = db.get(Alpha, alpha_id)
    if existing:
        return Response(
            content=AlphaRead.model_validate(existing).model_dump_json(),
            status_code=200,
            media_type="application/json",
        )
    orm = Alpha(
        id=alpha_id, expression=body.expression, universe=body.universe,
        region=body.region, delay=body.delay, decay=body.decay,
        neutralization=body.neutralization, truncation=body.truncation,
        pasteurization=body.pasteurization, nan_handling=body.nan_handling,
        source=body.source.value, parent_id=body.parent_id,
        rationale=body.rationale, filter_skipped=False,
    )
    db.add(orm)
    db.commit()
    db.refresh(orm)
    return Response(
        content=AlphaRead.model_validate(orm).model_dump_json(),
        status_code=201,
        media_type="application/json",
    )


@router.delete("/alphas/{alpha_id}", status_code=204)
def delete_alpha(alpha_id: str, db: Session = Depends(get_db)):
    alpha = db.get(Alpha, alpha_id)
    if alpha is None:
        raise HTTPException(status_code=404, detail="Alpha not found")
    child_count = db.query(Alpha).filter(Alpha.parent_id == alpha_id).count()
    sim_count = db.query(Simulation).filter(Simulation.alpha_id == alpha_id).count()
    if child_count > 0 or sim_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {child_count} child alpha(s), {sim_count} simulation(s) exist",
        )
    db.delete(alpha)
    db.commit()
