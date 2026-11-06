"""Add management models and desired runtime state without changing existing IDs."""

from pathlib import Path
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    for statement in (
        (Path(__file__).parents[1] / "modernization.sql").read_text().split(";")
    ):
        if statement.strip():
            op.execute(statement)


def downgrade():
    for name in [
        "route_options",
        "deployment_releases",
        "operation_runs",
        "deployment_sources",
        "policy_rules",
        "service_aliases",
        "service_profiles",
    ]:
        op.drop_table(name)
    op.drop_column("runtimes", "autostart_policy")
    op.drop_column("runtimes", "desired_state")
