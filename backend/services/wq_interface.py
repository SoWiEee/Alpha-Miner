"""WQ Brain submission interface — Manual and Auto implementations."""
from __future__ import annotations

import asyncio
import csv
import io
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from backend.core.models import AlphaCandidate
from backend.models.alpha import Alpha
from backend.models.simulation import Simulation
from backend.schemas.simulation import SimulationRead

# ── WQ Brain API constants ───────────────────────────────────────────────────

WQ_AUTH_URL = "https://api.worldquantbrain.com/authentication"
WQ_SIMULATIONS_URL = "https://api.worldquantbrain.com/simulations"
WQ_ALPHAS_URL = "https://api.worldquantbrain.com/alphas/{alpha_id}"

WQ_DONE_STATUSES = {"DONE"}
WQ_FAILED_STATUSES = {"ERROR", "CANCELLED", "FAILED"}


# ── Custom exceptions ────────────────────────────────────────────────────────

class BiometricAuthRequired(Exception):
    """Raised when WQ Brain requires biometric (2FA) authentication."""
    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Biometric authentication required. Complete it at: {url}")


class SimulationTimeout(Exception):
    """Raised when a simulation does not complete within the poll timeout."""


class SimulationFailed(Exception):
    """Raised when WQ Brain returns a terminal failure status."""
    def __init__(self, wq_status: str) -> None:
        self.wq_status = wq_status
        super().__init__(f"WQ Brain simulation failed with status: {wq_status}")


# ── Abstract interface ───────────────────────────────────────────────────────

class WQBrainInterface(ABC):
    @abstractmethod
    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        """Create Simulation DB row and initiate submission. Returns str(simulation.id)."""

    @abstractmethod
    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        """Retrieve result for a simulation by its DB id. Returns None if not found."""


# ── ManualQueueClient ────────────────────────────────────────────────────────

class ManualQueueClient(WQBrainInterface):
    """Queue-only client: creates pending Simulation rows; results imported manually."""

    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        existing = (
            db.query(Simulation)
            .filter(Simulation.alpha_id == alpha.id, Simulation.status == "pending")
            .first()
        )
        if existing:
            raise ValueError(f"A pending simulation already exists for alpha {alpha.id}")
        sim = Simulation(
            alpha_id=alpha.id,
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(sim)
        db.commit()
        db.refresh(sim)
        return str(sim.id)

    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        sim = db.get(Simulation, int(simulation_id))
        if sim is None:
            return None
        return SimulationRead.model_validate(sim)

    def export_pending(self, db: Session, format: str = "json") -> list[dict] | str:
        """Export pending alphas formatted for WQ Brain UI fields."""
        sims = db.query(Simulation).filter(Simulation.status == "pending").all()
        rows: list[dict] = []
        for sim in sims:
            alpha = db.get(Alpha, sim.alpha_id)
            if alpha is None:
                continue
            rows.append({
                "alpha_id": alpha.id,
                "expression": alpha.expression,
                "settings": {
                    "region": alpha.region,
                    "universe": alpha.universe,
                    "delay": alpha.delay,
                    "decay": alpha.decay,
                    "neutralization": alpha.neutralization.capitalize(),
                    "truncation": alpha.truncation,
                    "pasteurization": alpha.pasteurization.capitalize(),
                    "nan_handling": alpha.nan_handling.capitalize(),
                },
            })

        if format == "csv":
            output = io.StringIO()
            fieldnames = ["alpha_id", "expression", "region", "universe",
                          "delay", "decay", "neutralization", "truncation",
                          "pasteurization", "nan_handling"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "alpha_id": row["alpha_id"],
                    "expression": row["expression"],
                    **row["settings"],
                })
            return output.getvalue()

        return rows
