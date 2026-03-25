from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.models import AlphaCandidate, AlphaSource
from backend.core.mutator import TemplateMutator
from backend.core.expression_validator import ExpressionValidator
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.correlation import Run
from backend.schemas.alpha import MutateRequest, MutateResponse, AlphaRead, RunRead

router = APIRouter(tags=["generate"])
_mutator = TemplateMutator()
_validator = ExpressionValidator()


def _alpha_orm_to_candidate(orm: Alpha) -> AlphaCandidate:
    return AlphaCandidate(
        id=orm.id, expression=orm.expression, universe=orm.universe,
        region=orm.region, delay=orm.delay, decay=orm.decay,
        neutralization=orm.neutralization, truncation=orm.truncation,
        pasteurization=orm.pasteurization, nan_handling=orm.nan_handling,
        source=AlphaSource(orm.source), parent_id=orm.parent_id,
        rationale=orm.rationale, created_at=orm.created_at,
        filter_skipped=orm.filter_skipped,
    )


def _candidate_to_orm(candidate: AlphaCandidate) -> Alpha:
    return Alpha(
        id=candidate.id, expression=candidate.expression,
        universe=candidate.universe, region=candidate.region,
        delay=candidate.delay, decay=candidate.decay,
        neutralization=candidate.neutralization, truncation=candidate.truncation,
        pasteurization=candidate.pasteurization, nan_handling=candidate.nan_handling,
        source=candidate.source.value, parent_id=candidate.parent_id,
        rationale=candidate.rationale, filter_skipped=candidate.filter_skipped,
        created_at=candidate.created_at,
    )


@router.post("/generate/mutate", response_model=MutateResponse)
def mutate(body: MutateRequest, db: Session = Depends(get_db)):
    started = datetime.utcnow()

    if body.alpha_id is not None:
        orm = db.get(Alpha, body.alpha_id)
        if orm is None:
            raise HTTPException(status_code=404, detail="Alpha not found")
        targets = [_alpha_orm_to_candidate(orm)]
    else:
        targets = [_alpha_orm_to_candidate(o) for o in db.query(Alpha).filter(
            Alpha.source == AlphaSource.SEED.value
        ).all()]

    # Collect raw mutations (pre-validation) to get the true generated count
    raw_candidates: list[AlphaCandidate] = []
    for target in targets:
        raw_candidates.extend(
            _mutator.mutate_lookback(target)
            + _mutator.mutate_operator(target)
            + _mutator.mutate_rank_wrap(target)
            + _mutator.mutate_config(target)
        )

    generated = len(raw_candidates)  # raw count before validation and dedup

    # Validate and deduplicate
    seen: dict[str, AlphaCandidate] = {}
    for candidate in raw_candidates:
        if candidate.id not in seen:
            if _validator.validate(candidate.expression).valid:
                seen[candidate.id] = candidate

    all_candidates = list(seen.values())

    # Persist — skip duplicates that already exist in DB
    saved: list[Alpha] = []
    for candidate in all_candidates:
        if db.get(Alpha, candidate.id) is None:
            orm = _candidate_to_orm(candidate)
            db.add(orm)
            saved.append(orm)

    run = Run(
        mode="mutation",
        candidates_gen=generated,
        candidates_pass=len(saved),
        started_at=started,
        finished_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    for orm in saved:
        db.refresh(orm)

    return MutateResponse(
        run_id=run.id,
        candidates_generated=generated,
        candidates_passed_validation=len(saved),
        candidates=[AlphaRead.model_validate(o) for o in saved],
    )


@router.get("/generate/runs", response_model=list[RunRead])
def list_runs(db: Session = Depends(get_db)):
    return db.query(Run).order_by(Run.started_at.desc()).all()


@router.post("/generate/llm", status_code=501)
def generate_llm():
    return {"detail": "Not implemented (Phase 4)"}


@router.post("/generate/gp", status_code=501)
def generate_gp():
    return {"detail": "Not implemented (Phase 5)"}
