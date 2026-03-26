from datetime import datetime
from pydantic import BaseModel, ConfigDict
from backend.core.models import AlphaSource


class AlphaCreate(BaseModel):
    expression: str
    universe: str = "TOP3000"
    region: str = "USA"
    delay: int = 1
    decay: int = 0
    neutralization: str = "subindustry"
    truncation: float = 0.08
    pasteurization: str = "off"
    nan_handling: str = "off"
    source: AlphaSource = AlphaSource.MANUAL
    parent_id: str | None = None
    rationale: str | None = None


class AlphaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    expression: str
    universe: str
    region: str
    delay: int
    decay: int
    neutralization: str
    truncation: float
    pasteurization: str
    nan_handling: str
    source: AlphaSource
    parent_id: str | None
    rationale: str | None
    filter_skipped: bool
    created_at: datetime


class MutateRequest(BaseModel):
    alpha_id: str | None = None
    strategies: list[str] = ["lookback", "operator", "rank_wrap", "config"]


class MutateResponse(BaseModel):
    run_id: int
    candidates_generated: int
    candidates_passed_validation: int
    candidates: list[AlphaRead]


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    candidates_gen: int
    candidates_pass: int
    llm_theme: str | None
    gp_generations: int | None
    started_at: datetime
    finished_at: datetime | None


class LLMRequest(BaseModel):
    theme: str | None = None
    n: int = 10


class LLMResponse(BaseModel):
    run_id: int
    candidates_generated: int
    candidates_passed_validation: int
    candidates_passed_diversity: int
    candidates_skipped_filter: int
    candidates_rejected_diversity: int
    candidates: list[AlphaRead]


class GPRequest(BaseModel):
    n_results: int = 10
    population_size: int | None = None
    generations: int | None = None


class GPResponse(BaseModel):
    run_id: int
    status: str
    message: str
