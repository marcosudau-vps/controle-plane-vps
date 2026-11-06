from datetime import datetime
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$"
HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
VALID_SYSTEMS = {"services", "special-purpose"}


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any = None
    error: dict[str, Any] | None = None


class ServiceCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str = Field(min_length=2, max_length=160)
    summary: str = ""
    system: str = "services"
    component_type: str = "service"
    lifecycle: str = "development"
    owner: str = "marco"
    criticality: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    large_port_space: bool = False
    port_base: int | None = None
    caddy_protection_enabled: bool = False

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().lower() for tag in value if tag.strip()})

    @field_validator("system")
    @classmethod
    def validate_system(cls, value: str) -> str:
        if value not in VALID_SYSTEMS:
            raise ValueError("system must be services or special-purpose")
        return value

    @field_validator("lifecycle")
    @classmethod
    def validate_lifecycle(cls, value: str) -> str:
        if value not in {"experimental", "development", "production", "deprecated"}:
            raise ValueError("lifecycle must be experimental, development, production, or deprecated")
        return value


class ManagedServiceProvisionCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str = Field(min_length=2, max_length=160)
    summary: str = ""
    system: str = "services"
    component_type: str = "service"
    lifecycle: str = "production"
    owner: str = "marco"
    criticality: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    subdomain: str = Field(pattern=SLUG_PATTERN)
    upstream: str
    port: int | None = Field(default=None, ge=1, le=65535)
    runtime_type: str = "docker-compose"
    runtime_path: str = ""
    compose_project: str = ""
    doc_path: str = ""
    doc_title: str = ""
    healthcheck_target: str = ""
    healthcheck_expected_status: int = 200
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    caddy_protection_enabled: bool = False

    @field_validator("tags")
    @classmethod
    def normalize_provision_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().lower() for tag in value if tag.strip()})

    @field_validator("upstream", "healthcheck_target")
    @classmethod
    def validate_optional_urls(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must be absolute http(s)")
        return value


class ServiceUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    system: str | None = None
    component_type: str | None = None
    lifecycle: str | None = None
    owner: str | None = None
    criticality: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    tags: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    large_port_space: bool | None = None
    port_base: int | None = None
    caddy_protection_enabled: bool | None = None

    @field_validator("system")
    @classmethod
    def validate_optional_system(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_SYSTEMS:
            raise ValueError("system must be services or special-purpose")
        return value

    @field_validator("lifecycle")
    @classmethod
    def validate_optional_lifecycle(cls, value: str | None) -> str | None:
        if value is not None and value not in {"experimental", "development", "production", "deprecated"}:
            raise ValueError("lifecycle must be experimental, development, production, or deprecated")
        return value


class ServiceOut(ServiceCreate):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubServiceCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str = Field(min_length=2, max_length=160)
    parent_type: str
    parent_id: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    caddy_protection_enabled: bool | None = None

    @field_validator("parent_type")
    @classmethod
    def validate_parent_type(cls, value: str) -> str:
        if value not in {"service", "subservice"}:
            raise ValueError(f"parent_type must be 'service' or 'subservice', got '{value}'")
        return value


class SubServiceUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    metadata_json: dict[str, Any] | None = None
    caddy_protection_enabled: bool | None = None


class SubServiceOut(BaseModel):
    id: str
    slug: str
    title: str
    parent_type: str
    parent_id: str
    status: str
    metadata_json: dict[str, Any]
    caddy_protection_enabled: bool | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RouteCreate(BaseModel):
    service_slug: str | None = None
    parent_type: str | None = None
    parent_slug: str | None = None
    host: str
    path: str = "/"
    upstream: str
    tls: bool = True
    auth_policy: str = "public"
    caddy_protection_enabled: bool | None = None
    status: str = "active"

    @field_validator("path")
    @classmethod
    def path_starts_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("path must start with /")
        return value

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        clean = value.strip().strip(".").lower()
        if not clean or "/" in clean or ":" in clean or ".." in clean:
            raise ValueError("host must be a hostname or hostname template")
        rendered = clean.replace("{base_domain}", "marcosudau.com")
        if "{" in rendered or "}" in rendered or not HOST_PATTERN.match(rendered):
            raise ValueError("host must be a valid hostname or {base_domain} hostname template")
        return clean

    @field_validator("upstream")
    @classmethod
    def validate_upstream(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("upstream must be an absolute http(s) URL")
        return value

    @field_validator("parent_type")
    @classmethod
    def validate_parent_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {"service", "subservice"}:
            raise ValueError(f"parent_type must be 'service' or 'subservice', got '{value}'")
        return value

    @field_validator("auth_policy")
    @classmethod
    def validate_auth_policy(cls, value: str) -> str:
        if value not in {"public", "caddy_schutz"}:
            raise ValueError("auth_policy must be public or caddy_schutz")
        return value


class RouteUpdate(BaseModel):
    """Change a route without replacing its identity or protection policy."""

    model_config = ConfigDict(extra="forbid")
    upstream: str | None = None
    service_slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    status: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("explicit null is not supported")
        return value

    @field_validator("upstream")
    @classmethod
    def validate_upstream(cls, value: str) -> str:
        return RouteCreate.validate_upstream(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"active", "inactive", "archived"}:
            raise ValueError("status must be active, inactive or archived")
        return value


class PortUpdate(BaseModel):
    """Move or reassign one registered port while preserving its ID."""

    model_config = ConfigDict(extra="forbid")
    number: int | None = Field(default=None, ge=1, le=65535)
    service_slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    purpose: str | None = Field(default=None, max_length=160)
    status: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        return RouteUpdate.reject_null(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        return RouteUpdate.validate_status(value)


class CaddyCertZoneRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    max_new_zones_per_run: int = Field(default=5, ge=0, le=50)
    max_total_zones_per_root: int = Field(default=30, ge=1, le=200)
    exclude_root_zone: bool = False
    no_reload: bool = False


class CaddyProtectionUpdate(BaseModel):
    enabled: bool | None = None


class CaddyProtectionAuthCheck(BaseModel):
    authenticated: bool
    method: str | None = None


class RouteOut(BaseModel):
    id: str
    service_id: str | None = None
    subservice_id: str | None = None
    parent_type: str | None = None
    parent_id: str | None = None
    host: str
    path: str
    upstream: str
    tls: bool
    auth_policy: str
    caddy_protection_enabled: bool | None
    status: str

    model_config = ConfigDict(from_attributes=True)


class PortCreate(BaseModel):
    service_slug: str | None = None
    number: int = Field(ge=1, le=65535)
    protocol: str = "tcp"
    bind: str = "127.0.0.1"
    purpose: str = ""
    status: str = "active"

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value not in {"tcp", "udp"}:
            raise ValueError("protocol must be tcp or udp")
        return value


class RuntimeCreate(BaseModel):
    service_slug: str
    runtime_type: str
    path: str = ""
    compose_project: str = ""
    systemd_unit: str = ""
    restart_policy: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_type")
    @classmethod
    def validate_runtime_type(cls, value: str) -> str:
        if value not in {"docker-compose", "user-systemd", "system-systemd", "external", "manual"}:
            raise ValueError("invalid runtime_type")
        return value


class ResourceCreate(BaseModel):
    service_slug: str | None = None
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str
    resource_type: str
    owner: str = "marco"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ApiEntityCreate(BaseModel):
    service_slug: str
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str
    api_type: str = "openapi"
    definition_path: str = ""


class SkillCreate(BaseModel):
    service_slug: str | None = None
    slug: str = Field(pattern=SLUG_PATTERN)
    title: str
    skill_type: str = "component"
    path: str
    description: str = ""


class SecretRefCreate(BaseModel):
    service_slug: str
    name: str
    provider: str = "bitwarden"
    ref: str
    target_env: str = ""

    @field_validator("ref")
    @classmethod
    def validate_secret_ref(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("secret ref must not be empty")
        if any(marker in value.lower() for marker in ["password=", "token=", "sk-"]):
            raise ValueError("secret ref must not contain secret values")
        return value


class DocCreate(BaseModel):
    service_slug: str
    doc_type: str
    path: str
    title: str


class HealthcheckCreate(BaseModel):
    service_slug: str
    check_type: str = "http"
    target: str
    expected_status: int = 200
    timeout_seconds: int = 5

    @field_validator("check_type")
    @classmethod
    def validate_check_type(cls, value: str) -> str:
        if value not in {"http", "tcp"}:
            raise ValueError("check_type must be http or tcp")
        return value


class CommentCreate(BaseModel):
    entity_kind: str
    entity_id: str
    body: str
    author: str = "marco"


class LifecycleExecuteRequest(BaseModel):
    plan_hash: str = Field(min_length=16, max_length=128)


class LifecycleArchiveInspectRequest(BaseModel):
    archive_id: str | None = None
    archive_dir: str | None = None
    archive_path: str | None = None


class ValidationResultOut(BaseModel):
    severity: str
    code: str
    message: str
    entity_kind: str = ""
    entity_id: str = ""

    model_config = ConfigDict(from_attributes=True)


class ValidationRunOut(BaseModel):
    id: str
    scope: str
    status: str
    results: list[ValidationResultOut]

    model_config = ConfigDict(from_attributes=True)
