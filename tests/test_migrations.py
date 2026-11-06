"""Opt-in real PostgreSQL tests; the DSN must point to a dedicated local test database."""

import os
from pathlib import Path
import subprocess
import pytest


@pytest.mark.skipif(
    not os.environ.get("CP_TEST_POSTGRES_URL"),
    reason="set isolated CP_TEST_POSTGRES_URL",
)
def test_postgres_empty_baseline_upgrade_roundtrip(tmp_path):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    url = os.environ["CP_TEST_POSTGRES_URL"]
    args = conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://"))
    assert args.get("host") == "127.0.0.1" and args.get("dbname", "").startswith(
        "ctpl_test_"
    )
    schema = "ctpl_isolated_test"
    env = {
        **os.environ,
        "CP_CONFIG_PATH": "/dev/null",
        "CP_DATABASE_URL": url,
        "CP_DB_SCHEMA": schema,
    }
    root = Path(__file__).parents[1]
    python = os.sys.executable

    def run(*command):
        result = subprocess.run(
            [python, "-m", *command], cwd=root, env=env, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr

    run("alembic", "upgrade", "0001")
    with psycopg.connect(**args) as connection:
        connection.execute(f"SET search_path TO {schema}")
        connection.execute(
            "INSERT INTO services (id,slug,title,summary,system,component_type,lifecycle,owner,criticality,status,tags,metadata_json,large_port_space,caddy_protection_enabled,created_at,updated_at) VALUES ('stable-id','migration-sample','Migration sample','','services','service','development','test',3,'active','[]','{}',false,false,now(),now())"
        )
    run("control_plane.migration_tools")
    run("alembic", "upgrade", "head")
    run("alembic", "upgrade", "head")
    with psycopg.connect(**args) as connection:
        connection.execute(f"SET search_path TO {schema}")
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0002"
        )
        assert (
            connection.execute("SELECT id FROM services").fetchone()[0] == "stable-id"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO policy_rules (id,rule_id,version,severity,actions,message,owner,created_at,updated_at) VALUES ('bad','negative',0,'block','[]','invalid','test',now(),now())"
                )
    run("alembic", "downgrade", "0001")
    run("alembic", "upgrade", "head")
    with psycopg.connect(**args) as connection:
        connection.execute(f"SET search_path TO {schema}")
        assert (
            connection.execute("SELECT id FROM services").fetchone()[0] == "stable-id"
        )
        connection.execute(f"DROP SCHEMA {schema} CASCADE")
