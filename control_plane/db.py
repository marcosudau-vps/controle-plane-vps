from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql"):
        schema = get_settings().db_schema
        kwargs["connect_args"] = {"options": f"-csearch_path={schema},public"}
    return kwargs


def create_control_engine(url: str):
    new_engine = create_engine(url, **_engine_kwargs(url))

    @event.listens_for(new_engine, "connect")
    def _set_connection_defaults(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        if new_engine.url.get_backend_name() == "sqlite":
            cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return new_engine


engine = create_control_engine(get_settings().database_url)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401

    if engine.url.get_backend_name() == "postgresql":
        schema = get_settings().db_schema
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()


def _has_column(table: str, column: str) -> bool:
    inspector = inspect(engine)
    schema = get_settings().db_schema if engine.url.get_backend_name() == "postgresql" else None
    return column in {item["name"] for item in inspector.get_columns(table, schema=schema)}


def _exec_ddl(statement: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement))


def ensure_schema_compatibility() -> None:
    backend = engine.url.get_backend_name()
    schema_prefix = f'"{get_settings().db_schema}".' if backend == "postgresql" else ""

    def table(name: str) -> str:
        return f"{schema_prefix}{name}"

    if not _has_column("services", "port_base"):
        _exec_ddl(f"ALTER TABLE {table('services')} ADD COLUMN port_base INTEGER")
    if not _has_column("services", "large_port_space"):
        default_false = "BOOLEAN DEFAULT false NOT NULL" if backend == "postgresql" else "BOOLEAN DEFAULT 0 NOT NULL"
        _exec_ddl(f"ALTER TABLE {table('services')} ADD COLUMN large_port_space {default_false}")
    if not _has_column("services", "caddy_protection_enabled"):
        default_false = "BOOLEAN DEFAULT false NOT NULL" if backend == "postgresql" else "BOOLEAN DEFAULT 0 NOT NULL"
        _exec_ddl(f"ALTER TABLE {table('services')} ADD COLUMN caddy_protection_enabled {default_false}")

    if not _has_column("sub_services", "caddy_protection_enabled"):
        _exec_ddl(f"ALTER TABLE {table('sub_services')} ADD COLUMN caddy_protection_enabled BOOLEAN")

    if not _has_column("routes", "subservice_id"):
        _exec_ddl(f"ALTER TABLE {table('routes')} ADD COLUMN subservice_id VARCHAR(36)")
    if not _has_column("routes", "parent_type"):
        _exec_ddl(f"ALTER TABLE {table('routes')} ADD COLUMN parent_type VARCHAR(40)")
    if not _has_column("routes", "parent_id"):
        _exec_ddl(f"ALTER TABLE {table('routes')} ADD COLUMN parent_id VARCHAR(36)")
    if not _has_column("routes", "caddy_protection_enabled"):
        _exec_ddl(f"ALTER TABLE {table('routes')} ADD COLUMN caddy_protection_enabled BOOLEAN")

    if backend == "postgresql":
        _exec_ddl(f"ALTER TABLE {table('routes')} ALTER COLUMN service_id DROP NOT NULL")

    if not _has_column("lifecycle_runs", "quarantine_dir"):
        _exec_ddl(f"ALTER TABLE {table('lifecycle_runs')} ADD COLUMN quarantine_dir VARCHAR(255) DEFAULT '' NOT NULL")


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
