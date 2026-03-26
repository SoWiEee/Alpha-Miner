from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.expression_validator import ExpressionValidator
from backend.core.llm_generator import LLMGenerator, PoolContext
from backend.core.models import AlphaCandidate, AlphaSource
from backend.core.mutator import TemplateMutator
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.correlation import Run
from backend.models.simulation import Simulation
from backend.schemas.alpha import (
    AlphaRead,
    LLMRequest,
    LLMResponse,
    MutateRequest,
    MutateResponse,
    RunRead,
)
from backend.services.diversity_filter import AlphaEvaluator, DiversityFilter, UnsupportedOperatorError
from backend.services.proxy_data import ProxyDataManager

router = APIRouter(tags=["generate"])
_mutator = TemplateMutator()
_validator = ExpressionValidator()
_evaluator = AlphaEvaluator()
_proxy_mgr = ProxyDataManager()


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


def _get_pool_alphas(db: Session) -> list[AlphaCandidate]:
    """Return all alphas that have at least one completed simulation."""
    alpha_ids = {
        s.alpha_id
        for s in db.query(Simulation).filter(Simulation.status == "completed").all()
    }
    result = []
    for aid in alpha_ids:
        a = db.get(Alpha, aid)
        if a:
            result.append(_alpha_orm_to_candidate(a))
    return result


def _apply_diversity(
    candidates: list[AlphaCandidate],
    db: Session,
    settings,
) -> tuple[list[AlphaCandidate], int, int]:
    """
    Apply diversity filter to candidates.
    Returns (accepted_candidates, rejected_count, skipped_count).
    accepted_candidates have filter_skipped set correctly.
    """
    panel = _proxy_mgr.get_panel(db)
    pool_alphas = _get_pool_alphas(db)

    if panel.empty:
        # No proxy data — all pass with filter_skipped=True
        for c in candidates:
            c.filter_skipped = True
        return candidates, 0, len(candidates)

    filter_results = DiversityFilter(settings.DIVERSITY_THRESHOLD).filter_batch(
        candidates, pool_alphas, _evaluator, panel
    )

    accepted = []
    rejected = 0
    skipped = 0
    for cand, should_submit, max_corr in filter_results:
        if not should_submit:
            rejected += 1
            continue
        if np.isnan(max_corr):
            cand.filter_skipped = True
            skipped += 1
        else:
            cand.filter_skipped = False
        accepted.append(cand)

    return accepted, rejected, skipped


@router.post("/generate/mutate", response_model=MutateResponse)
def mutate(body: MutateRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    started = datetime.now(timezone.utc)

    if body.alpha_id is not None:
        orm = db.get(Alpha, body.alpha_id)
        if orm is None:
            raise HTTPException(status_code=404, detail="Alpha not found")
        targets = [_alpha_orm_to_candidate(orm)]
    else:
        targets = [_alpha_orm_to_candidate(o) for o in db.query(Alpha).filter(
            Alpha.source == AlphaSource.SEED.value
        ).all()]

    # Collect raw mutations
    raw_candidates: list[AlphaCandidate] = []
    for target in targets:
        raw_candidates.extend(
            _mutator.mutate_lookback(target)
            + _mutator.mutate_operator(target)
            + _mutator.mutate_rank_wrap(target)
            + _mutator.mutate_config(target)
        )

    generated = len(raw_candidates)

    # Validate and deduplicate
    seen: dict[str, AlphaCandidate] = {}
    for candidate in raw_candidates:
        if candidate.id not in seen:
            if _validator.validate(candidate.expression).valid:
                seen[candidate.id] = candidate

    all_candidates = list(seen.values())

    # Diversity filter (Phase 4)
    all_candidates, _rejected, _skipped = _apply_diversity(all_candidates, db, settings)

    # Persist — skip duplicates already in DB
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
        finished_at=datetime.now(timezone.utc),
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


@router.post("/generate/llm", response_model=LLMResponse, status_code=201)
def generate_llm(body: LLMRequest, db: Session = Depends(get_db)):
    settings = get_settings()

    if not settings.CLAUDE_API_KEY:
        raise HTTPException(status_code=503, detail="CLAUDE_API_KEY not configured")

    # Check daily rate limit
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    llm_runs_today = (
        db.query(Run)
        .filter(Run.mode == "llm", Run.started_at >= today_start)
        .count()
    )
    if llm_runs_today >= settings.LLM_MAX_CALLS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Daily LLM call limit ({settings.LLM_MAX_CALLS_PER_DAY}) reached",
        )

    started = datetime.now(timezone.utc)

    # Build pool context
    completed_sims = (
        db.query(Simulation)
        .filter(Simulation.status == "completed")
        .order_by(Simulation.fitness.desc())
        .all()
    )
    seen_ids: set[str] = set()
    top_alphas: list[dict] = []
    for sim in completed_sims:
        if sim.alpha_id not in seen_ids:
            seen_ids.add(sim.alpha_id)
            alpha = db.get(Alpha, sim.alpha_id)
            if alpha:
                top_alphas.append({
                    "expression": alpha.expression,
                    "sharpe": sim.sharpe,
                    "fitness": sim.fitness,
                    "returns": sim.returns,
                    "turnover": sim.turnover,
                })
        if len(top_alphas) >= 10:
            break

    pool_context = PoolContext(
        top_alphas=top_alphas,
        total_pool_size=len(seen_ids),
    )

    # Generate candidates
    generator = LLMGenerator(api_key=settings.CLAUDE_API_KEY)
    raw_candidates = generator.generate(pool_context, theme=body.theme, n=body.n)
    raw_count = len(raw_candidates)

    # Validate
    valid_candidates = [
        c for c in raw_candidates
        if _validator.validate(c.expression).valid
    ]
    passed_validation = len(valid_candidates)

    # Diversity filter
    accepted, rejected_count, skipped_count = _apply_diversity(valid_candidates, db, settings)
    passed_diversity = len(accepted) - skipped_count  # accepted with actual corr check

    # Persist
    saved: list[Alpha] = []
    for candidate in accepted:
        if db.get(Alpha, candidate.id) is None:
            orm = _candidate_to_orm(candidate)
            db.add(orm)
            saved.append(orm)

    run = Run(
        mode="llm",
        llm_theme=body.theme,
        candidates_gen=raw_count,
        candidates_pass=len(saved),
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    for orm in saved:
        db.refresh(orm)

    return LLMResponse(
        run_id=run.id,
        candidates_generated=raw_count,
        candidates_passed_validation=passed_validation,
        candidates_passed_diversity=passed_diversity,
        candidates_skipped_filter=skipped_count,
        candidates_rejected_diversity=rejected_count,
        candidates=[AlphaRead.model_validate(o) for o in saved],
    )


@router.post("/generate/gp", status_code=501)
def generate_gp():
    return {"detail": "Not implemented (Phase 5)"}
