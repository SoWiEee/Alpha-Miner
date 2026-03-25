from datetime import datetime
from pydantic import BaseModel, ConfigDict


class SimulationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alpha_id: str
    sharpe: float | None
    fitness: float | None
    returns: float | None
    turnover: float | None
    passed: bool | None
    status: str
    submitted_at: datetime | None
    completed_at: datetime | None
    wq_sim_id: str | None
    notes: str | None
