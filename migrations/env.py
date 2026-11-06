from alembic import context
from control_plane.db import create_control_engine
from control_plane.config import get_settings
import re
from sqlalchemy import text

settings = get_settings()
if not re.fullmatch(r"[a-z_][a-z0-9_]*", settings.db_schema):
    raise ValueError("invalid schema name")
engine = create_control_engine(settings.database_url)
with engine.connect() as connection:
    if engine.dialect.name == "postgresql":
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
        connection.commit()
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
