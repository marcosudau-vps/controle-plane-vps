from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .db import Base


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


JsonType = JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class Service(Base, TimestampMixin):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    system: Mapped[str] = mapped_column(String(40), default="services", nullable=False)
    component_type: Mapped[str] = mapped_column(String(40), default="service", nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(40), default="development", nullable=False)
    owner: Mapped[str] = mapped_column(String(80), default="marco", nullable=False)
    criticality: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    port_base: Mapped[int | None] = mapped_column(Integer, nullable=True)
    large_port_space: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    caddy_protection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    routes: Mapped[list["Route"]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
        foreign_keys="Route.service_id",
    )
    ports: Mapped[list["Port"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    runtimes: Mapped[list["Runtime"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    resources: Mapped[list["Resource"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    apis: Mapped[list["ApiEntity"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    skills: Mapped[list["Skill"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    secret_refs: Mapped[list["SecretRef"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    docs: Mapped[list["DocRef"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    healthchecks: Mapped[list["Healthcheck"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class SubService(Base, TimestampMixin):
    __tablename__ = "sub_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_type: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    caddy_protection_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    routes: Mapped[list["Route"]] = relationship(
        back_populates="subservice",
        cascade="all, delete-orphan",
        foreign_keys="Route.subservice_id",
    )


class Route(Base, TimestampMixin):
    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("host", "path", name="uq_route_host_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=True)
    subservice_id: Mapped[str | None] = mapped_column(ForeignKey("sub_services.id", ondelete="CASCADE"), nullable=True)
    parent_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(255), default="/", nullable=False)
    upstream: Mapped[str] = mapped_column(String(255), nullable=False)
    tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_policy: Mapped[str] = mapped_column(String(80), default="public", nullable=False)
    caddy_protection_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    service: Mapped[Service | None] = relationship(
        back_populates="routes",
        foreign_keys=[service_id],
    )
    subservice: Mapped[SubService | None] = relationship(
        back_populates="routes",
        foreign_keys=[subservice_id],
    )


class Port(Base, TimestampMixin):
    __tablename__ = "ports"
    __table_args__ = (UniqueConstraint("number", "protocol", name="uq_port_number_protocol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), default="tcp", nullable=False)
    bind: Mapped[str] = mapped_column(String(64), default="127.0.0.1", nullable=False)
    purpose: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    service: Mapped[Service | None] = relationship(back_populates="ports")


class Runtime(Base, TimestampMixin):
    __tablename__ = "runtimes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    runtime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    compose_project: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    systemd_unit: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    restart_policy: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)

    service: Mapped[Service] = relationship(back_populates="runtimes")


class Resource(Base, TimestampMixin):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner: Mapped[str] = mapped_column(String(80), default="marco", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)

    service: Mapped[Service | None] = relationship(back_populates="resources")


class ApiEntity(Base, TimestampMixin):
    __tablename__ = "apis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    api_type: Mapped[str] = mapped_column(String(40), default="openapi", nullable=False)
    definition_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    service: Mapped[Service] = relationship(back_populates="apis")


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    skill_type: Mapped[str] = mapped_column(String(40), default="component", nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    service: Mapped[Service | None] = relationship(back_populates="skills")
    items: Mapped[list["SkillItem"]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class SkillItem(Base, TimestampMixin):
    __tablename__ = "skill_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(40), default="file", nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="items")


class SecretRef(Base, TimestampMixin):
    __tablename__ = "secret_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="bitwarden", nullable=False)
    ref: Mapped[str] = mapped_column(String(255), nullable=False)
    target_env: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    service: Mapped[Service] = relationship(back_populates="secret_refs")


class DocRef(Base, TimestampMixin):
    __tablename__ = "docs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)

    service: Mapped[Service] = relationship(back_populates="docs")


class Healthcheck(Base, TimestampMixin):
    __tablename__ = "healthchecks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    check_type: Mapped[str] = mapped_column(String(40), default="http", nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    service: Mapped[Service] = relationship(back_populates="healthchecks")


class Relation(Base, TimestampMixin):
    __tablename__ = "relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)


class ValidationRun(Base, TimestampMixin):
    __tablename__ = "validation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(80), default="all", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="passed", nullable=False)
    results: Mapped[list["ValidationResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ValidationResult(Base, TimestampMixin):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)

    run: Mapped[ValidationRun] = relationship(back_populates="results")


class GeneratedArtifact(Base, TimestampMixin):
    __tablename__ = "generated_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="generated", nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    detail: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(120), default="marco", nullable=False)


class ExportRun(Base):
    __tablename__ = "export_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    export_type: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)


class LifecycleRun(Base, TimestampMixin):
    __tablename__ = "lifecycle_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_slug: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="planned", nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    archive_dir: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    archive_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    quarantine_dir: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    request_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    result_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
