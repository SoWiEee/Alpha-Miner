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


# ── AutoAPIClient ────────────────────────────────────────────────────────────

class AutoAPIClient(WQBrainInterface):
    """Submits alphas to WQ Brain via the unofficial API; blocks until complete."""

    def __init__(
        self,
        email: str,
        password: str,
        poll_interval: float = 5.0,
        poll_timeout: float = 300.0,
    ) -> None:
        self._email = email
        self._password = password
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def _login(self, client: httpx.AsyncClient) -> None:
        """POST /authentication with HTTP Basic auth. Raises BiometricAuthRequired if 2FA needed."""
        resp = await client.post(WQ_AUTH_URL, auth=(self._email, self._password))
        data = resp.json() if resp.content else {}
        if "inquiryId" in data:
            url = (
                data.get("message")
                or f"https://platform.worldquantbrain.com/?inquiryId={data['inquiryId']}"
            )
            raise BiometricAuthRequired(url)

    async def submit(self, alpha: AlphaCandidate, db: Session) -> str:
        async with httpx.AsyncClient() as client:
            # 1. Authenticate
            await self._login(client)

            # 2. Submit simulation
            body = {
                "type": "REGULAR",
                "settings": {
                    "instrumentType": "EQUITY",
                    "region": alpha.region,
                    "universe": alpha.universe,
                    "delay": alpha.delay,
                    "decay": alpha.decay,
                    "neutralization": alpha.neutralization.upper(),
                    "truncation": alpha.truncation,
                    "pasteurization": alpha.pasteurization.upper(),
                    "nanHandling": alpha.nan_handling.upper(),
                    "language": "FASTEXPR",
                    "visualization": False,
                },
                "regular": alpha.expression,
            }
            resp = await client.post(WQ_SIMULATIONS_URL, json=body)

            if not resp.is_success:
                sim = Simulation(
                    alpha_id=alpha.id,
                    status="failed",
                    submitted_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(sim)
                db.commit()
                raise RuntimeError(f"WQ Brain submit failed: HTTP {resp.status_code}")

            location_url: str = resp.headers.get("Location", "")

            # 3. Create simulation row (status=submitted)
            sim = Simulation(
                alpha_id=alpha.id,
                status="submitted",
                wq_sim_id=location_url,
                submitted_at=datetime.now(timezone.utc),
            )
            db.add(sim)
            db.commit()
            db.refresh(sim)

            # 4. Poll until done or timeout
            elapsed = 0.0
            poll_data: dict = {}
            while elapsed < self._poll_timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                poll_resp = await client.get(location_url)
                poll_data = poll_resp.json()
                wq_status = poll_data.get("status", "")
                if wq_status in WQ_DONE_STATUSES:
                    break
                if wq_status in WQ_FAILED_STATUSES:
                    sim.status = "failed"
                    sim.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    raise SimulationFailed(wq_status)
            else:
                raise SimulationTimeout(
                    f"Simulation did not complete within {self._poll_timeout}s"
                )

            # 5. Fetch alpha metrics
            alpha_link: str = poll_data.get("alpha", "")
            if not alpha_link.startswith("http"):
                alpha_link = WQ_ALPHAS_URL.format(alpha_id=alpha_link)
            metrics_resp = await client.get(alpha_link)
            metrics = metrics_resp.json()

            is_data: dict = metrics.get("is", {})
            checks = is_data.get("checks", [])
            passed: bool | None = (
                all(c.get("result") == "PASS" for c in checks) if checks else None
            )

            # 6. Mark complete and persist metrics
            sim.status = "completed"
            sim.sharpe = is_data.get("sharpe")
            sim.fitness = is_data.get("fitness")
            sim.returns = is_data.get("returns")
            sim.turnover = is_data.get("turnover")
            sim.passed = passed
            sim.completed_at = datetime.now(timezone.utc)
            db.commit()

            return str(sim.id)

    async def get_result(self, simulation_id: str, db: Session) -> SimulationRead | None:
        sim = db.get(Simulation, int(simulation_id))
        if sim is None:
            return None
        return SimulationRead.model_validate(sim)
