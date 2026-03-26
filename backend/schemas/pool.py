from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PoolStatus(BaseModel):
    pool_size: int
    avg_sharpe: float | None
    avg_fitness: float | None
    max_correlation: float | None
    min_correlation: float | None


class CorrelationEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    alpha_a: str
    alpha_b: str
    correlation: float
    computed_at: datetime


class TopAlphaEntry(BaseModel):
    id: str
    expression: str
    source: str
    sharpe: float | None
    fitness: float | None
    returns: float | None
    turnover: float | None
    passed: bool | None


class RecomputeResult(BaseModel):
    pairs_computed: int
    skipped: int
