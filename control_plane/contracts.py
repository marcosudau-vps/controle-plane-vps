"""Technical profiles and projections of the existing registry, without a second registry."""

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import models
from .config import get_settings
from .redaction import clean, reject_secret_fields
from .service import get_service_by_slug

CORE_SERVICES = frozenset(
    {
        "control-plane",
        "control-plane-postgres",
        "caddy",
        "caddy-docker",
        "docs-site",
        "vps-server-docs",
        "bulwark",
        "stalwart",
        "redis-stack",
        "postgres",
        "postgresql",
    }
)
PATH_KEYS = {
    "stack_dir",
    "compose_file",
    "data_dir",
    "data_dirs",
    "docs_dir",
    "app_dir",
    "build_area_dir",
    "config_file",
    "config_files",
}


def digest(data) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def object_data(obj):
    return clean(
        {
            c.name: (
                (
                    getattr(obj, c.name).replace(tzinfo=timezone.utc)
                    if getattr(obj, c.name).tzinfo is None
                    else getattr(obj, c.name)
                ).isoformat()
                if isinstance(getattr(obj, c.name), datetime)
                else getattr(obj, c.name)
            )
            for c in obj.__table__.columns
        }
    )


def safe_path(value: str, root: Path, *, exists=False) -> Path:
    p = Path(value)
    if not p.is_absolute() or ".." in p.parts:
        raise HTTPException(422, "absolute path without traversal required")
    resolved = p.resolve()
    root = root.resolve()
    if resolved == root or root not in resolved.parents:
        raise HTTPException(422, "path outside permitted service directory")
    if exists and not resolved.exists():
        raise HTTPException(422, "registered path does not exist")
    return resolved


def resolve_service(db, slug):
    alias = db.get(models.ServiceAlias, slug)
    return (
        db.get(models.Service, alias.service_id)
        if alias
        else get_service_by_slug(db, slug)
    )


def profile_data(db, service):
    row = db.get(models.ServiceProfile, service.id)
    if row:
        return object_data(row)
    return {
        "service_id": service.id,
        "revision": 0,
        "description": "",
        "category": "",
        "protected": service.slug in CORE_SERVICES
        or service.component_type == "database",
        "archivable": False,
        "snapshot_supported": True,
        "paths": {},
    }


def protected(db, service):
    return (
        service.slug in CORE_SERVICES
        or service.component_type == "database"
        or profile_data(db, service)["protected"]
    )


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*")
    @classmethod
    def no_secrets(cls, value):
        reject_secret_fields(value)
        return value


class ProfileUpdate(StrictInput):
    expected_revision: int = Field(ge=0)
    description: str = Field(default="", max_length=20000)
    category: str = Field(default="", max_length=80)
    protected: bool = False
    archivable: bool = False
    snapshot_supported: bool = True
    paths: dict[str, str | list[str]] = Field(default_factory=dict)


class AliasInput(StrictInput):
    alias: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)


class MetadataInput(StrictInput):
    service_yaml: dict = Field(default_factory=dict)
    profile_yaml: dict = Field(default_factory=dict)
    resolutions: dict[str, Literal["database", "service_yaml", "profile_yaml"]] = Field(
        default_factory=dict
    )
    plan_hash: str | None = None


def update_profile(db, service, payload: ProfileUpdate):
    old = profile_data(db, service)
    if old["revision"] != payload.expected_revision:
        raise HTTPException(412, "profile revision changed")
    data = payload.model_dump(exclude={"expected_revision"})
    if protected(db, service) and (not data["protected"] or data["archivable"]):
        raise HTTPException(
            403, "core protection cannot be removed through profile updates"
        )
    root = Path(get_settings().selfhost_root)
    for key, raw in data["paths"].items():
        if key not in PATH_KEYS:
            raise HTTPException(422, "unknown technical path type")
        values = raw if isinstance(raw, list) else [raw]
        for path in values:
            allowed = (
                Path(get_settings().outsourced_build_area_root)
                / "services"
                / service.slug
                if key == "build_area_dir"
                else root
            )
            safe_path(path, allowed.parent if key == "build_area_dir" else allowed)
    row = db.get(models.ServiceProfile, service.id)
    if row is None:
        row = models.ServiceProfile(service_id=service.id, revision=1, **data)
        db.add(row)
        db.flush()
    else:
        changed = (
            db.query(models.ServiceProfile)
            .filter_by(service_id=service.id, revision=payload.expected_revision)
            .update(
                {**data, "revision": payload.expected_revision + 1},
                synchronize_session=False,
            )
        )
        if not changed:
            raise HTTPException(412, "profile revision changed")
        db.refresh(row)
    return row


def service_contract(db, service):
    def rows(values):
        return [object_data(v) for v in sorted(values, key=lambda x: x.id)]

    profile = profile_data(db, service)
    runtimes = rows(service.runtimes)
    runtime_ids = [r["id"] for r in runtimes]
    relations = (
        db.query(models.Relation)
        .filter(
            (models.Relation.source_id == service.id)
            | (models.Relation.target_id == service.id)
        )
        .all()
    )
    from .policies import effective_rules

    data = {
        "schema_version": "1.0",
        "service": object_data(service),
        "profile": profile,
        "aliases": sorted(
            x.alias
            for x in db.query(models.ServiceAlias).filter_by(service_id=service.id)
        ),
        "routes": rows(service.routes),
        "ports": rows(service.ports),
        "runtimes": runtimes,
        "resources": rows(service.resources),
        "apis": rows(service.apis),
        "docs": rows(service.docs),
        "skills": rows(service.skills),
        "secret_refs": rows(service.secret_refs),
        "healthchecks": rows(service.healthchecks),
        "subservices": rows(
            db.query(models.SubService)
            .filter_by(parent_type="service", parent_id=service.id)
            .all()
        ),
        "route_options": [
            object_data(r)
            for r in db.query(models.RouteOptions).filter(
                models.RouteOptions.route_id.in_([r.id for r in service.routes])
            )
        ],
        "relations": rows(relations),
        "deployment_sources": rows(
            db.query(models.DeploymentSource)
            .filter(models.DeploymentSource.runtime_id.in_(runtime_ids))
            .all()
        )
        if runtime_ids
        else [],
        "lifecycle": {
            "protected": protected(db, service),
            "archivable": profile["archivable"],
            "snapshot_supported": profile["snapshot_supported"],
            "yaml_compatibility": True,
        },
        "policies": effective_rules(db, service),
    }
    data["revision"] = digest(data)
    return clean(data)


def metadata_plan(db, service, payload):
    current = profile_data(db, service)
    sy = payload.service_yaml
    sm = sy.get("service") or {}
    cp = sy.get("cp_metadata") or {}
    if (
        sm.get("slug", service.slug) != service.slug
        or cp.get("id", service.id) != service.id
    ):
        raise HTTPException(
            409, "manifest identity differs; review an explicit alias mapping"
        )
    profile_fields = [
        "description",
        "category",
        "paths",
        "archivable",
        "snapshot_supported",
    ]
    service_fields = [
        "title",
        "summary",
        "system",
        "component_type",
        "lifecycle",
        "owner",
        "criticality",
        "tags",
        "large_port_space",
        "caddy_protection_enabled",
    ]
    candidates = {k: {"database": current.get(k)} for k in profile_fields}
    candidates.update({k: {"database": getattr(service, k)} for k in service_fields})
    life = sy.get("lifecycle") or {}
    if "name" in sm:
        candidates["title"]["service_yaml"] = sm["name"]
    if "category" in sm:
        candidates["category"]["service_yaml"] = sm["category"]
    for k in service_fields:
        source_key = "lifecycle_stage" if k == "lifecycle" else k
        if source_key in cp:
            candidates[k]["service_yaml"] = cp[source_key]
    for k in ["archivable", "snapshot_supported"]:
        if k in life:
            candidates[k]["service_yaml"] = life[k]
    if "paths" in sy:
        candidates["paths"]["service_yaml"] = {
            k: v for k, v in sy["paths"].items() if k in PATH_KEYS
        }
    for k in ["description", "category", "summary", "title"]:
        if k in payload.profile_yaml:
            candidates[k]["profile_yaml"] = payload.profile_yaml[k]
    unknown = sorted(
        set(payload.profile_yaml)
        - {"description", "category", "summary", "title", "schema_version"}
    )
    conflicts = []
    values = {}
    for k, sources in candidates.items():
        meaningful = {
            origin: v
            for origin, v in sources.items()
            if origin != "database" or current["revision"] > 0 or k in service_fields
        }
        choice = payload.resolutions.get(k)
        if choice and choice not in sources:
            raise HTTPException(422, "resolution source missing")
        if len({digest(v) for v in meaningful.values()}) > 1 and not choice:
            conflicts.append(k)
        values[k] = (
            sources[choice]
            if choice
            else next(iter(meaningful.values()), sources["database"])
        )
    result = {
        "service_id": service.id,
        "service_revision": digest(object_data(service)),
        "revision": current["revision"],
        "candidates": candidates,
        "conflicts": conflicts,
        "unmapped_profile_fields": unknown,
        "values": values,
        "resolutions": payload.resolutions,
        "reference_sections": {
            k: "compare through the canonical registry API; this import does not replace live resources"
            for k in ["runtime", "dependencies", "routes", "operator_permissions"]
            if k in sy
        },
    }
    result["plan_hash"] = digest(result)
    return result


def compatibility_metadata(db, service):
    profile = profile_data(db, service)
    runtimes = service.runtimes
    rt = runtimes[0] if len(runtimes) == 1 else None
    dependencies = {"hard": [], "optional": []}
    for relation in db.query(models.Relation).filter_by(
        source_kind="service", source_id=service.id, target_kind="service"
    ):
        target = db.get(models.Service, relation.target_id)
        if target and relation.relation_type in {
            "hard_dependency",
            "depends_on",
            "optional_dependency",
        }:
            dependencies[
                "optional"
                if relation.relation_type == "optional_dependency"
                else "hard"
            ].append({"service": target.slug})
    return {
        "service_yaml": {
            "schema_version": 1,
            "service": {
                "slug": service.slug,
                "name": service.title,
                "category": profile["category"],
                "status": service.status,
            },
            "lifecycle": {
                "archivable": profile["archivable"],
                "snapshot_supported": profile["snapshot_supported"],
                "archive_requires_confirmation": True,
            },
            "paths": profile["paths"],
            "runtime": {
                "backend": "docker_compose"
                if rt and rt.runtime_type == "docker-compose"
                else "external",
                "compose_project": rt.compose_project if rt else None,
                "compose_file": rt.path if rt else None,
            },
            "dependencies": dependencies,
            "cp_metadata": {
                k: getattr(service, k)
                for k in [
                    "id",
                    "summary",
                    "system",
                    "component_type",
                    "owner",
                    "criticality",
                    "tags",
                ]
            },
        },
        "profile_yaml": {
            "schema_version": 1,
            "summary": service.summary,
            "description": profile["description"],
        },
        "generated": True,
        "source": "Control Plane API",
        "lifecycle_compatible": bool(rt and profile["paths"] and profile["category"]),
    }
