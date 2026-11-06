"""Read-only verification before an operator explicitly stamps an existing baseline."""

import json
from pathlib import Path
from sqlalchemy import inspect
from .db import engine


def verify_baseline():
    signature = json.loads(
        (Path(__file__).parents[1] / "migrations/baseline-signature.json").read_text()
    )
    inspector = inspect(engine)
    for table, expected in signature.items():
        actual = {
            c["name"]: str(c["type"].compile(dialect=engine.dialect))
            for c in inspector.get_columns(table)
        }
        if actual != expected:
            raise RuntimeError(f"baseline column/type mismatch: {table}")
    print(f"Baseline verified: {len(signature)} existing tables; no writes performed")


if __name__ == "__main__":
    verify_baseline()
