"""Frozen original 20-table schema. Existing databases require verified stamp."""

from pathlib import Path
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for statement in (
        (Path(__file__).parents[1] / "baseline.sql").read_text().split(";")
    ):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError(
        "Restore the verified pre-migration database backup; baseline removal is destructive"
    )
