#!/usr/bin/env python
"""Load Alpha101 seed pool into the database. Safe to run multiple times."""
import sys
from pathlib import Path

# Allow running from repo root: uv run python scripts/seed_alpha101.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import get_settings
from backend.database import get_engine, Base
import backend.models  # noqa: F401
from backend.core.seed_pool import SEED_POOL
from backend.models.alpha import Alpha
from sqlalchemy.orm import sessionmaker


def main():
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    inserted = 0
    skipped = 0
    for seed in SEED_POOL:
        if db.get(Alpha, seed.id) is None:
            db.add(Alpha(
                id=seed.id, expression=seed.expression,
                universe=seed.universe, region=seed.region,
                delay=seed.delay, decay=seed.decay,
                neutralization=seed.neutralization, truncation=seed.truncation,
                pasteurization=seed.pasteurization, nan_handling=seed.nan_handling,
                source=seed.source.value, parent_id=None, rationale=None,
                filter_skipped=False, created_at=seed.created_at,
            ))
            inserted += 1
        else:
            skipped += 1

    db.commit()
    db.close()
    print(f"Seed pool loaded: {inserted} inserted, {skipped} skipped (already exist)")


if __name__ == "__main__":
    main()
