"""Pool health API — status, correlations, top alphas, recompute."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from scipy.stats import spearmanr
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db
from backend.models.alpha import Alpha
from backend.models.correlation import PoolCorrelation
from backend.models.simulation import Simulation
from backend.schemas.pool import (
    CorrelationEntry,
    PoolStatus,
    RecomputeResult,
    TopAlphaEntry,
)
from backend.services.diversity_filter import AlphaEvaluator, UnsupportedOperatorError
from backend.services.proxy_data import ProxyDataManager

router = APIRouter(tags=["pool"])

_evaluator = AlphaEvaluator()
_proxy_mgr = ProxyDataManager()


@router.get("/pool/status", response_model=PoolStatus)
def pool_status(db: Session = Depends(get_db)):
    completed = db.query(Simulation).filter(Simulation.status == "completed").all()
    pool_size = len({s.alpha_id for s in completed})
    sharpes = [s.sharpe for s in completed if s.sharpe is not None]
    fitnesses = [s.fitness for s in completed if s.fitness is not None]
    corr_rows = db.query(PoolCorrelation).all()
    corr_vals = [r.correlation for r in corr_rows]
    return PoolStatus(
        pool_size=pool_size,
        avg_sharpe=float(np.mean(sharpes)) if sharpes else None,
        avg_fitness=float(np.mean(fitnesses)) if fitnesses else None,
        max_correlation=float(max(corr_vals)) if corr_vals else None,
        min_correlation=float(min(corr_vals)) if corr_vals else None,
    )


@router.get("/pool/correlations", response_model=list[CorrelationEntry])
def pool_correlations(db: Session = Depends(get_db)):
    return (
        db.query(PoolCorrelation)
        .order_by(PoolCorrelation.correlation.desc())
        .all()
    )


@router.get("/pool/top", response_model=list[TopAlphaEntry])
def pool_top(n: int = 10, db: Session = Depends(get_db)):
    completed = (
        db.query(Simulation)
        .filter(Simulation.status == "completed")
        .order_by(Simulation.fitness.desc())
        .all()
    )
    seen: set[str] = set()
    result: list[TopAlphaEntry] = []
    for sim in completed:
        if sim.alpha_id in seen:
            continue
        seen.add(sim.alpha_id)
        alpha = db.get(Alpha, sim.alpha_id)
        if alpha is None:
            continue
        result.append(
            TopAlphaEntry(
                id=alpha.id,
                expression=alpha.expression,
                source=alpha.source,
                sharpe=sim.sharpe,
                fitness=sim.fitness,
                returns=sim.returns,
                turnover=sim.turnover,
                passed=sim.passed,
            )
        )
        if len(result) >= n:
            break
    return result


@router.post("/pool/recompute", response_model=RecomputeResult)
def pool_recompute(db: Session = Depends(get_db)):
    # Get all alphas with at least one completed simulation
    completed_alpha_ids = {
        s.alpha_id
        for s in db.query(Simulation).filter(Simulation.status == "completed").all()
    }
    alphas = [db.get(Alpha, aid) for aid in completed_alpha_ids if db.get(Alpha, aid)]

    panel = _proxy_mgr.get_panel(db)
    if panel.empty:
        return RecomputeResult(pairs_computed=0, skipped=len(alphas))

    # Evaluate each alpha
    evaluated: dict[str, object] = {}  # alpha_id -> pd.Series (dropna'd)
    skipped = 0
    for alpha in alphas:
        try:
            vals = _evaluator.evaluate(alpha.expression, panel).dropna()
            if len(vals) >= 10:
                evaluated[alpha.id] = vals
            else:
                skipped += 1
        except (UnsupportedOperatorError, ValueError):
            skipped += 1

    # Compute pairwise correlations
    alpha_ids = list(evaluated.keys())
    pairs_computed = 0
    now = datetime.now(timezone.utc)

    for i in range(len(alpha_ids)):
        for j in range(i + 1, len(alpha_ids)):
            id_a, id_b = sorted([alpha_ids[i], alpha_ids[j]])
            sa = evaluated[id_a]
            sb = evaluated[id_b]
            aligned_a, aligned_b = sa.align(sb, join="inner")
            mask = aligned_a.notna() & aligned_b.notna()
            a_clean = aligned_a[mask]
            b_clean = aligned_b[mask]
            if len(a_clean) < 10:
                continue
            corr, _ = spearmanr(a_clean.values, b_clean.values)
            if np.isnan(corr):
                continue
            # Upsert
            existing = db.get(PoolCorrelation, (id_a, id_b))
            if existing:
                existing.correlation = float(corr)
                existing.computed_at = now
            else:
                db.add(PoolCorrelation(
                    alpha_a=id_a,
                    alpha_b=id_b,
                    correlation=float(corr),
                    computed_at=now,
                ))
            pairs_computed += 1

    db.commit()
    return RecomputeResult(pairs_computed=pairs_computed, skipped=skipped)
