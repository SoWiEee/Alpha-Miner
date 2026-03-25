import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AlphaSource(str, Enum):
    SEED = "seed"
    MUTATION = "mutation"
    GP = "gp"
    LLM = "llm"
    MANUAL = "manual"


def compute_alpha_id(
    expression: str,
    universe: str,
    region: str,
    delay: int,
    decay: int,
    neutralization: str,
    truncation: float,
    pasteurization: str,
    nan_handling: str,
) -> str:
    """Deterministic SHA256 ID over canonicalised alpha config."""
    payload = json.dumps(
        {
            "expression": expression.strip().lower(),
            "universe": universe.lower(),
            "region": region.lower(),
            "delay": int(delay),
            "decay": int(decay),
            "neutralization": neutralization.lower(),
            "truncation": f"{truncation:.4f}",
            "pasteurization": pasteurization.lower(),
            "nan_handling": nan_handling.lower(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class AlphaCandidate:
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
    created_at: datetime
    filter_skipped: bool = False

    @classmethod
    def create(
        cls,
        expression: str,
        source: AlphaSource,
        *,
        universe: str = "TOP3000",
        region: str = "USA",
        delay: int = 1,
        decay: int = 0,
        neutralization: str = "subindustry",
        truncation: float = 0.08,
        pasteurization: str = "off",
        nan_handling: str = "off",
        parent_id: str | None = None,
        rationale: str | None = None,
        filter_skipped: bool = False,
        created_at: datetime | None = None,
    ) -> "AlphaCandidate":
        alpha_id = compute_alpha_id(
            expression, universe, region, delay, decay,
            neutralization, truncation, pasteurization, nan_handling,
        )
        return cls(
            id=alpha_id,
            expression=expression,
            universe=universe,
            region=region,
            delay=delay,
            decay=decay,
            neutralization=neutralization,
            truncation=truncation,
            pasteurization=pasteurization,
            nan_handling=nan_handling,
            source=source,
            parent_id=parent_id,
            rationale=rationale,
            created_at=created_at or datetime.utcnow(),
            filter_skipped=filter_skipped,
        )
