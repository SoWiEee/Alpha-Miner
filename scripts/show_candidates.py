#!/usr/bin/env python
"""Display the most recent mutation batch as a table. Usage: uv run python scripts/show_candidates.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import get_engine
from backend.models.correlation import Run
from backend.models.alpha import Alpha
import backend.models  # noqa: F401
from sqlalchemy.orm import sessionmaker


def main():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    latest_run = db.query(Run).filter(Run.mode == "mutation").order_by(Run.started_at.desc()).first()
    if latest_run is None:
        print("No mutation runs found. Run POST /api/generate/mutate first.")
        db.close()
        return

    print(f"\nRun #{latest_run.id} | {latest_run.started_at} | generated={latest_run.candidates_gen} passed={latest_run.candidates_pass}\n")
    print(f"{'ID':18} {'Source':10} {'Neutralization':16} {'Decay':6} {'Trunc':6}  Expression")
    print("-" * 120)

    candidates = (
        db.query(Alpha)
        .filter(
            Alpha.source == "mutation",
            Alpha.created_at >= latest_run.started_at,
        )
        .order_by(Alpha.created_at.desc())
        .all()
    )

    for a in candidates:
        expr = a.expression[:60] + "..." if len(a.expression) > 60 else a.expression
        print(f"{a.id[:16]:18} {a.source:10} {a.neutralization:16} {a.decay:<6} {a.truncation:<6.2f}  {expr}")

    print(f"\nTotal: {len(candidates)} candidates")
    db.close()


if __name__ == "__main__":
    main()
