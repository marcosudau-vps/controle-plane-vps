"""Additive management routes in the existing FastAPI application."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from . import models, runtime
from .access import Principal, principal
from .config import get_settings
from .contracts import (
    AliasInput,
    MetadataInput,
    ProfileUpdate,
    StrictInput,
    metadata_plan,
    object_data,
    profile_data,
    resolve_service,
    service_contract,
    update_profile,
)
from .db import get_session
from .operations import (
    ExecuteInput,
    OperationInput,
    SourceInput,
    create_plan,
    queue_operation,
    run_operation,
    sources_for,
    workflow,
    serialize_registry,
)
from .policies import RuleInput, effective_rules, rule_findings
from .redaction import clean
from .service import commit_or_409, log_activity
from .storage import storage_inventory

from .response_schemas import (
    Envelope,
    TechnicalContract,
    RuntimeObservation,
    OperationOut,
)

router = APIRouter(
    prefix="/api/v1",
    responses={
        401: {"description": "Missing credentials"},
        403: {"description": "Scope, protection or approval denied"},
        404: {"description": "Unknown resource"},
        409: {"description": "State or ownership conflict"},
        412: {"description": "Stale revision or plan"},
        422: {"description": "Invalid schema or policy"},
        503: {"description": "Backend unavailable"},
    },
)


def ok(data):
    return {"ok": True, "data": clean(data), "error": None}


def permitted(db, slug, actor, scope="read"):
    s = resolve_service(db, slug)
    actor.check(scope, s.slug)
    return s


@router.get("/catalog")
def catalog(
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
    offset: int = 0,
    limit: int = 100,
):
    actor.check("read")
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(422, "invalid pagination")
    q = db.query(models.Service).order_by(models.Service.slug)
    if "*" not in actor.services:
        q = q.filter(models.Service.slug.in_(actor.services))
    return ok(
        {
            "items": [object_data(s) for s in q.offset(offset).limit(limit)],
            "total": q.count(),
            "offset": offset,
            "limit": limit,
        }
    )


@router.get("/services/{slug}/contract", response_model=Envelope[TechnicalContract])
def contract(
    slug: str,
    response: Response,
    format: Literal["json", "yaml"] = "json",
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor)
    data = service_contract(db, s)
    response.headers["ETag"] = f'"{data["revision"]}"'
    if format == "yaml":
        return Response(
            yaml.safe_dump(json.loads(json.dumps(data, default=str)), sort_keys=False),
            media_type="application/yaml",
            headers={"ETag": response.headers["ETag"]},
        )
    return ok(data)


@router.get("/services/{slug}/profile")
def profile(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    return ok(profile_data(db, permitted(db, slug, actor)))


@router.put("/services/{slug}/profile")
def profile_put(
    slug: str,
    payload: ProfileUpdate,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    row = update_profile(db, s, payload)
    log_activity(
        db,
        "profile.update",
        "service",
        s.id,
        {"revision": row.revision},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(object_data(row))


@router.post("/services/{slug}/aliases")
@serialize_registry
def alias_add(
    slug: str,
    payload: AliasInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    if db.query(models.Service).filter_by(slug=payload.alias).first():
        raise HTTPException(409, "alias conflicts with a canonical slug")
    row = models.ServiceAlias(alias=payload.alias, service_id=s.id)
    db.add(row)
    log_activity(
        db, "alias.create", "service", s.id, {"alias": payload.alias}, actor=actor.actor
    )
    commit_or_409(db)
    return ok(object_data(row))


@router.post("/services/{slug}/metadata/plan")
def import_plan(
    slug: str,
    payload: MetadataInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    return ok(metadata_plan(db, s, payload))


@router.post("/services/{slug}/metadata/import")
def metadata_import(
    slug: str,
    payload: MetadataInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    plan = metadata_plan(db, s, payload)
    if plan["plan_hash"] != payload.plan_hash:
        raise HTTPException(412, "metadata plan changed")
    if plan["conflicts"] or plan["unmapped_profile_fields"]:
        raise HTTPException(
            409, "resolve conflicts and unmapped fields before importing"
        )
    values = dict(plan["values"])
    from .schemas import ServiceUpdate

    service_changes = {
        k: values.pop(k)
        for k in list(values)
        if k
        not in {"description", "category", "paths", "archivable", "snapshot_supported"}
    }
    from pydantic import ValidationError

    try:
        validated = ServiceUpdate(**service_changes)
    except ValidationError:
        raise HTTPException(
            422, "imported service fields do not match the registry schema"
        ) from None
    values["protected"] = profile_data(db, s)["protected"]
    row = update_profile(
        db, s, ProfileUpdate(expected_revision=plan["revision"], **values)
    )
    for key, value in validated.model_dump(exclude_unset=True).items():
        setattr(s, key, value)
    log_activity(
        db,
        "metadata.import",
        "service",
        s.id,
        {"plan_hash": plan["plan_hash"]},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(object_data(row))


class DependencyInput(StrictInput):
    target_slug: str
    kind: Literal["hard", "optional"] = "hard"


@router.post("/services/{slug}/dependencies")
def add_dependency(
    slug: str,
    payload: DependencyInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    target = permitted(db, payload.target_slug, actor, "read")
    if target.id == s.id:
        raise HTTPException(409, "self dependency")
    kind = "hard_dependency" if payload.kind == "hard" else "optional_dependency"
    if (
        db.query(models.Relation)
        .filter_by(
            source_kind="service",
            source_id=s.id,
            target_kind="service",
            target_id=target.id,
            relation_type=kind,
        )
        .first()
    ):
        raise HTTPException(409, "dependency already registered")
    row = models.Relation(
        source_kind="service",
        source_id=s.id,
        target_kind="service",
        target_id=target.id,
        relation_type=kind,
    )
    db.add(row)
    db.flush()
    # Graph validation without requiring Docker availability.
    from .operations import hard_dependencies

    def walk(node, seen):
        if node.id in seen:
            raise HTTPException(409, "hard dependency cycle")
        for i in hard_dependencies(db, node):
            walk(db.get(models.Service, i), seen | {node.id})

    walk(s, set())
    log_activity(
        db,
        "dependency.create",
        "service",
        s.id,
        {"target_id": target.id, "kind": kind},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(object_data(row))


@router.get("/registry/reconcile")
def registry_reconcile(
    actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    actor.check("configure")
    if "*" not in actor.services:
        raise HTTPException(403, "global inventory requires global scope")
    return ok(runtime.reconcile(db))


@router.get(
    "/services/{slug}/runtime/status", response_model=Envelope[list[RuntimeObservation]]
)
def status(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    return ok(runtime.runtime_status(db, permitted(db, slug, actor)))


@router.get("/services/{slug}/runtime/logs")
def logs(
    slug: str,
    runtime_id: str,
    tail: int = Query(default=100, ge=1, le=500),
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "runtime")
    rt, path, project, config = runtime.runtime_config(db, s, runtime_id)
    try:
        text = runtime.backend.compose(
            path, project, ["logs", "--no-color", "--tail", str(tail)]
        )[-64000:]
        # Values in known environment files are removed even if logged without a key.
        secret_values = []
        for definition in config["services"].values():
            entries = definition.get("env_file", [])
            entries = entries if isinstance(entries, list) else [entries]
            for entry in entries:
                if isinstance(entry, dict):
                    entry = entry.get("path")
                p = Path(entry)
                p = p if p.is_absolute() else path.parent / p
                from .contracts import safe_path

                p = safe_path(str(p), Path(get_settings().selfhost_root), exists=True)
                for line in p.read_text().splitlines():
                    if "=" in line and not line.lstrip().startswith("#"):
                        v = line.split("=", 1)[1].strip().strip("\"'")
                        if len(v) >= 4:
                            secret_values.append(v)
            env = definition.get("environment", {})
            if isinstance(env, dict):
                secret_values.extend(
                    str(v) for v in env.values() if v is not None and len(str(v)) >= 4
                )
        for value in sorted(set(secret_values), key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return ok(
            {
                "text": text,
                "tail": tail,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except runtime.DockerUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.post("/services/{slug}/operations/plan", response_model=Envelope[OperationOut])
def operations_plan(
    slug: str,
    payload: OperationInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor)
    return ok(object_data(create_plan(db, s, payload, actor)))


@router.post(
    "/operations/{operation_id}/execute",
    status_code=202,
    response_model=Envelope[OperationOut],
)
def operations_execute(
    operation_id: str,
    payload: ExecuteInput,
    tasks: BackgroundTasks,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    run = db.get(models.OperationRun, operation_id)
    if run is None:
        raise HTTPException(404, "operation not found")
    if queue_operation(db, run, payload, actor):
        tasks.add_task(run_operation, run.id)
    return ok(object_data(run))


@router.get("/operations", response_model=Envelope[list[OperationOut]])
def operations(
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
    limit: int = 50,
):
    actor.check("read")
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    q = db.query(models.OperationRun).join(models.Service)
    if "*" not in actor.services:
        q = q.filter(models.Service.slug.in_(actor.services))
    return ok(
        [
            object_data(r)
            for r in q.order_by(models.OperationRun.created_at.desc()).limit(limit)
        ]
    )


@router.get("/operations/{operation_id}", response_model=Envelope[OperationOut])
def operation(
    operation_id: str,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    run = db.get(models.OperationRun, operation_id)
    if run is None:
        raise HTTPException(404, "operation not found")
    actor.check("read", db.get(models.Service, run.service_id).slug)
    return ok(object_data(run))


@router.get("/services/{slug}/deployments/sources")
def sources(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    s = permitted(db, slug, actor)
    return ok([source for r in s.runtimes for source in sources_for(db, r.id)])


@router.put("/services/{slug}/deployments/sources")
def source_put(
    slug: str,
    payload: SourceInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor, "configure")
    rt, path, project, config = runtime.runtime_config(db, s, payload.runtime_id)
    definition = config["services"].get(payload.compose_service)
    if not definition or definition.get("image") != payload.image_ref:
        raise HTTPException(
            409, "source must match registered Compose service and image"
        )
    if payload.source_kind == "compose_build" and not definition.get("build"):
        raise HTTPException(422, "Compose build missing")
    if payload.source_kind == "external_build":
        workflow(payload.workflow_id)
    row = (
        db.query(models.DeploymentSource)
        .filter_by(runtime_id=rt.id, compose_service=payload.compose_service)
        .one_or_none()
    )
    if row is None:
        row = models.DeploymentSource(**payload.model_dump())
        db.add(row)
    else:
        for k, v in payload.model_dump().items():
            setattr(row, k, v)
    log_activity(
        db,
        "source.update",
        "service",
        s.id,
        {"compose_service": payload.compose_service},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(object_data(row))


@router.get("/services/{slug}/deployments/releases")
def releases(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    s = permitted(db, slug, actor)
    ids = [r.id for r in s.runtimes]
    return ok(
        [
            object_data(r)
            for r in db.query(models.DeploymentRelease)
            .filter(models.DeploymentRelease.runtime_id.in_(ids))
            .order_by(models.DeploymentRelease.created_at.desc())
            .limit(100)
        ]
    )


@router.get("/services/{slug}/policies")
def rules(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    return ok(effective_rules(db, permitted(db, slug, actor)))


@router.post("/policies")
def add_policy(
    payload: RuleInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    actor.check("policy")
    s = (
        permitted(db, payload.service_slug, actor, "policy")
        if payload.service_slug
        else None
    )
    if s is None and "*" not in actor.services:
        raise HTTPException(403, "global policies require global scope")
    if db.query(models.PolicyRule).filter_by(rule_id=payload.rule_id).first():
        last = (
            db.query(models.PolicyRule)
            .filter_by(rule_id=payload.rule_id)
            .order_by(models.PolicyRule.version.desc())
            .first()
        )
        if payload.version <= last.version or last.service_id != (s.id if s else None):
            raise HTTPException(
                409, "policy versions must increase within the original scope"
            )
    row = models.PolicyRule(
        **payload.model_dump(exclude={"service_slug"}),
        service_id=s.id if s else None,
        owner=actor.actor,
    )
    db.add(row)
    log_activity(
        db,
        "policy.create",
        "service",
        s.id if s else "",
        {"rule_id": payload.rule_id, "version": payload.version},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(object_data(row))


class PolicyCheck(StrictInput):
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


@router.post("/services/{slug}/policies/validate")
def policy_check(
    slug: str,
    payload: PolicyCheck,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    s = permitted(db, slug, actor)
    actor.check(
        "deploy"
        if payload.action in {"pull", "build", "deploy", "update", "rollback"}
        else "runtime",
        s.slug,
    )
    from .contracts import protected

    findings = rule_findings(db, s, payload.action)
    blocked = protected(db, s) or any(r["severity"] == "block" for r in findings)
    return ok(
        {
            "allowed": not blocked,
            "protected": protected(db, s),
            "rules": effective_rules(db, s),
            "findings": findings,
            "enforcement": "API only; host Docker/sudo permissions are unchanged",
        }
    )


@router.get("/docker/storage")
@router.post("/docker/storage/cleanup/plan")
def storage(actor: Principal = Depends(principal), db: Session = Depends(get_session)):
    actor.check("configure")
    if "*" not in actor.services:
        raise HTTPException(403, "global inventory requires global scope")
    try:
        return ok(storage_inventory(db))
    except runtime.DockerUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.get("/caddy/cert-zones/status")
def cert_status(actor: Principal = Depends(principal)):
    actor.check("read")
    if "*" not in actor.services:
        raise HTTPException(403, "global scope required")
    settings = get_settings()
    p = Path(settings.caddy_auto_cert_state_file)
    if not p.exists():
        return ok(
            {"state": "unknown", "observed_at": datetime.now(timezone.utc).isoformat()}
        )
    try:
        state = json.loads(p.read_text())
    except (OSError, ValueError):
        raise HTTPException(503, "certificate state is unavailable") from None
    return ok(
        {
            "state": "recorded",
            "managed": state,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "renewal_health": "not inferred from zone registry",
        }
    )


@router.get("/management/context")
def management_context(actor: Principal = Depends(principal)):
    return ok(
        {
            "actor": actor.actor,
            "role": actor.role,
            "services": actor.services,
            "execution_enabled": get_settings().runtime_apply_enabled,
        }
    )


@router.get("/management/activities")
def activities(
    actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    actor.check("read")
    q = db.query(models.ActivityLog)
    if "*" not in actor.services:
        ids = [
            s.id
            for s in db.query(models.Service).filter(
                models.Service.slug.in_(actor.services)
            )
        ]
        q = q.filter(
            models.ActivityLog.entity_kind == "service",
            models.ActivityLog.entity_id.in_(ids),
        )
    return ok(
        [
            object_data(r)
            for r in q.order_by(models.ActivityLog.created_at.desc()).limit(100)
        ]
    )


from .routing import RouteOptionsInput, options_for, ownership_findings, override_files


@router.get("/caddy/ownership")
def route_ownership(
    actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    actor.check("read")
    if "*" not in actor.services:
        raise HTTPException(403, "global scope required")
    return ok(
        {
            "routes": [
                {"host": r.host, **options_for(db, r)} for r in db.query(models.Route)
            ],
            "findings": ownership_findings(db),
        }
    )


@router.put("/routes/{route_id}/options")
def route_options(
    route_id: str,
    payload: RouteOptionsInput,
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    route = db.get(models.Route, route_id)
    if route is None:
        raise HTTPException(404, "route not found")
    service = db.get(models.Service, route.service_id)
    if service is None:
        raise HTTPException(422, "assign route to a service before configuring options")
    actor.check("configure", service.slug)
    if payload.owner_kind == "manual_override":
        allowed = {str(p.resolve()) for p in override_files()}
        if str(Path(payload.owner_ref).resolve()) not in allowed:
            raise HTTPException(
                422, "override must already exist in configured override directory"
            )
    elif payload.owner_ref:
        raise HTTPException(422, "generated routes do not accept an override reference")
    row = db.get(models.RouteOptions, route_id)
    if row is None:
        row = models.RouteOptions(route_id=route_id)
        db.add(row)
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    db.flush()
    findings = ownership_findings(db)
    if findings:
        raise HTTPException(
            409, {"message": "ownership conflict", "findings": findings}
        )
    log_activity(
        db,
        "route.options",
        "service",
        service.id,
        {"route_id": route.id},
        actor=actor.actor,
    )
    commit_or_409(db)
    return ok(options_for(db, route))


@router.get("/management/system")
def system_status(actor: Principal = Depends(principal)):
    import os

    actor.check("read")
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            memory[key] = int(value.split()[0]) // 1024
    return ok(
        {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "host procfs",
            "memory_total_mib": memory.get("MemTotal"),
            "memory_available_mib": memory.get("MemAvailable"),
            "swap_free_mib": memory.get("SwapFree"),
            "load": os.getloadavg(),
        }
    )


@router.get("/services/{slug}/metadata/export")
def metadata_export(
    slug: str,
    format: Literal["json", "yaml"] = "json",
    actor: Principal = Depends(principal),
    db: Session = Depends(get_session),
):
    from .contracts import compatibility_metadata

    data = compatibility_metadata(db, permitted(db, slug, actor))
    if format == "yaml":
        return Response(
            yaml.safe_dump(data, sort_keys=False), media_type="application/yaml"
        )
    return ok(data)


@router.get("/services/{slug}/deployments/images")
def inspect_images(
    slug: str, actor: Principal = Depends(principal), db: Session = Depends(get_session)
):
    s = permitted(db, slug, actor)
    try:
        return ok(
            [
                {
                    "compose_service": source["compose_service"],
                    **runtime.backend.image(source["image_ref"]),
                }
                for r in s.runtimes
                for source in sources_for(db, r.id)
            ]
        )
    except runtime.DockerUnavailable as e:
        raise HTTPException(503, str(e)) from None
