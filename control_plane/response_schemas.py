"""Stable wire shapes for the new management resources."""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    ok: bool = True
    data: T
    error: dict[str, Any] | None = None


class TechnicalContract(BaseModel):
    schema_version: Literal["1.0"]
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    service: dict[str, Any]
    profile: dict[str, Any]
    aliases: list[str]
    routes: list[dict[str, Any]]
    ports: list[dict[str, Any]]
    runtimes: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    apis: list[dict[str, Any]]
    docs: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    secret_refs: list[dict[str, Any]]
    healthchecks: list[dict[str, Any]]
    subservices: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    route_options: list[dict[str, Any]]
    deployment_sources: list[dict[str, Any]]
    lifecycle: dict[str, Any]
    policies: list[dict[str, Any]]


class RuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="allow")
    runtime_id: str
    runtime_type: str
    desired_state: Literal["manual", "running", "stopped"]
    autostart_policy: Literal["on_demand", "always", "disabled"]
    observed_at: datetime
    source: Literal["docker"]
    observed_state: Literal[
        "unknown", "unavailable", "running", "stopped", "unhealthy", "partial"
    ]
    containers: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    error: str | None = None


class OperationOut(BaseModel):
    id: str
    service_id: str
    runtime_id: str
    actor: str
    action: Literal[
        "start",
        "stop",
        "restart",
        "autostart",
        "pull",
        "build",
        "deploy",
        "update",
        "rollback",
    ]
    status: Literal[
        "planned", "queued", "running", "completed", "failed", "interrupted"
    ]
    active_key: str | None
    idempotency_key: str
    plan_hash: str
    plan: dict[str, Any]
    result: dict[str, Any]
    events: list[dict[str, Any]]
    error: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
