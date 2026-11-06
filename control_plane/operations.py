"""Durable plan/execute records using the existing SQLAlchemy session and audit log."""

import fcntl
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import yaml
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from . import db as database, models, runtime
from .config import get_settings
from .contracts import (
    StrictInput,
    digest,
    object_data,
    protected,
    safe_path,
    service_contract,
)
from .policies import rule_findings
from .service import log_activity

DEPLOY_ACTIONS = {"pull", "build", "deploy", "update", "rollback"}


class OperationInput(StrictInput):
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
    runtime_id: str
    idempotency_key: str = Field(
        min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    autostart_policy: Literal["always", "on_demand", "disabled"] | None = None
    release_id: str | None = None


class ExecuteInput(StrictInput):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool = False


class SourceInput(StrictInput):
    runtime_id: str
    compose_service: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}$")
    source_kind: Literal["registry_image", "compose_build", "external_build"]
    image_ref: str = Field(
        min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/@:-]*$"
    )
    workflow_id: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9_.-]*$")


def operation_dir():
    p = Path(
        get_settings().operations_dir
        or str(Path(get_settings().lifecycle_archive_root) / ".operations")
    )
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


@contextmanager
def operation_lock(key, *, wait=False):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", key):
        raise HTTPException(422, "invalid operation lock")
    # Same kernel flock survives multiple API workers and is released on process death.
    with (operation_dir() / f"{key}.lock").open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(409, "operation is already executing") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def hard_dependencies(db, service):
    ids = []
    for r in db.query(models.Relation).filter_by(
        source_kind="service", source_id=service.id, target_kind="service"
    ):
        if r.relation_type in {"depends_on", "hard_dependency"}:
            ids.append(r.target_id)
    manifest = (
        Path(get_settings().selfhost_root)
        / "stacks/services"
        / service.slug
        / "service.yaml"
    )
    if manifest.exists():
        safe_path(
            str(manifest),
            Path(get_settings().selfhost_root) / "stacks/services",
            exists=True,
        )
        try:
            document = yaml.safe_load(manifest.read_text()) or {}
            legacy = document.get("dependencies", {}).get("hard", [])
            from .contracts import resolve_service

            for item in legacy:
                slug = item.get("service") if isinstance(item, dict) else item
                if slug:
                    ids.append(resolve_service(db, slug).id)
        except (ValueError, TypeError, yaml.YAMLError, HTTPException):
            raise HTTPException(
                409, "legacy hard dependencies require registry reconciliation"
            ) from None
    return sorted(set(ids))


def dependency_findings(db, service, action):
    findings = []
    services = db.query(models.Service).all()
    visiting = set()
    visited = set()

    def visit(s):
        if s.id in visiting:
            raise HTTPException(409, "hard dependency cycle")
        if s.id in visited:
            return
        visiting.add(s.id)
        for i in hard_dependencies(db, s):
            target = db.get(models.Service, i)
            if target is None:
                raise HTTPException(409, "hard dependency is missing")
            visit(target)
        visiting.remove(s.id)
        visited.add(s.id)

    visit(service)
    if action in {"start", "restart", "deploy", "update", "rollback"}:
        targets = [db.get(models.Service, i) for i in hard_dependencies(db, service)]
        for s in targets:
            states = runtime.runtime_status(db, s)
            if not states or any(r["observed_state"] != "running" for r in states):
                findings.append(f"dependency {s.slug} is not running")
    if action in {"stop", "restart", "autostart", "deploy", "update", "rollback"}:
        for s in services:
            if service.id in hard_dependencies(db, s):
                states = runtime.runtime_status(db, s)
                if any(
                    r["observed_state"]
                    in {"running", "partial", "unavailable", "unknown"}
                    for r in states
                ):
                    findings.append(
                        f"dependent service {s.slug} is running or unavailable"
                    )
    return findings


def sources_for(db, rid):
    return [
        object_data(s)
        for s in db.query(models.DeploymentSource)
        .filter_by(runtime_id=rid)
        .order_by(models.DeploymentSource.compose_service)
    ]


def current_snapshot(db, service, payload):
    rt, path, project, config = runtime.runtime_config(db, service, payload.runtime_id)
    runtime.backend.compose(path, project, ["config", "-q"])
    containers = runtime.backend.containers(project)
    findings = []
    if any(c.get("compose_file") != str(path) for c in containers):
        findings.append("observed containers belong to a different Compose definition")
    if protected(db, service):
        findings.append(
            "protected core service: runtime mutations require a separately reviewed maintenance procedure"
        )
    if service.status != "active":
        findings.append("service is not active")
    if payload.action in {"start", "restart", "build", "update", "deploy", "rollback"}:
        available = next(
            (
                int(line.split()[1]) // 1024
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:")
            ),
            0,
        )
        if available < get_settings().minimum_available_memory_mib:
            findings.append("insufficient available host memory for this operation")
    findings += dependency_findings(db, service, payload.action)
    rules = rule_findings(db, service, payload.action)
    findings += [r["message"] for r in rules if r["severity"] == "block"]
    sources = sources_for(db, rt.id)
    if payload.action in {"start", "stop", "restart", "autostart"} and {
        c["compose_service"] for c in containers
    } != set(config["services"]):
        findings.append(
            "all configured containers must already exist; explicit deployment required"
        )
    if payload.action in DEPLOY_ACTIONS:
        if {s["compose_service"] for s in sources} != set(config["services"]):
            findings.append("register image provenance for every Compose service")
        for s in sources:
            definition = config["services"].get(s["compose_service"], {})
            if definition.get("image") != s["image_ref"]:
                findings.append("registered image differs from Compose source")
            if s["source_kind"] == "compose_build" and not definition.get("build"):
                findings.append("registered Compose build is absent")
            if s["source_kind"] == "external_build" and not s["workflow_id"]:
                findings.append("external build requires registered workflow")
        if payload.action == "pull" and any(
            s["source_kind"] != "registry_image" for s in sources
        ):
            findings.append(
                "pull requires a stack of registry images; use update for mixed stacks"
            )
        if payload.action == "build" and any(
            s["source_kind"] == "registry_image" for s in sources
        ):
            findings.append("build requires build sources; use update for mixed stacks")
    if payload.action == "autostart" and not payload.autostart_policy:
        findings.append("autostart policy required")
    rollback = None
    if payload.action == "rollback":
        release = db.get(models.DeploymentRelease, payload.release_id)
        if not release or release.runtime_id != rt.id:
            findings.append("rollback release does not belong to runtime")
        else:
            rollback = object_data(release)
            if not release.previous_images:
                findings.append("release has no previous images")
            if release.compose_checksum != digest(config):
                findings.append("Compose changed; image rollback alone is unsafe")
            for image in release.previous_images.values():
                runtime.backend.image(image)
    # Include env/config file digests without ever storing their contents in the plan.
    file_digests = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}
    interpolation_env = path.parent / ".env"
    if interpolation_env.exists():
        interpolation_env = safe_path(
            str(interpolation_env), Path(get_settings().selfhost_root), exists=True
        )
        file_digests[str(interpolation_env)] = hashlib.sha256(
            interpolation_env.read_bytes()
        ).hexdigest()
    for definition in config["services"].values():
        for raw in (
            definition.get("env_file", [])
            if isinstance(definition.get("env_file", []), list)
            else [definition["env_file"]]
        ):
            if isinstance(raw, dict):
                raw = raw.get("path")
            if raw:
                p = Path(raw)
                p = p if p.is_absolute() else path.parent / p
                allowed = Path(get_settings().selfhost_root)
                p = safe_path(str(p), allowed, exists=True)
                file_digests[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    if payload.action in {"start", "deploy"}:
        for s in sources:
            runtime.backend.image(s["image_ref"])
    return {
        "request": payload.model_dump(),
        "service_revision": service_contract(db, service)["revision"],
        "project": project,
        "compose_file": str(path),
        "compose_checksum": digest(config),
        "file_digests": file_digests,
        "containers": sorted(containers, key=lambda x: x["id"]),
        "sources": sources,
        "rollback": rollback,
        "dependency_findings": findings,
        "rules": rules,
        "requires_approval": True,
    }


def create_plan(db, service, payload, actor):
    actor.check(
        "deploy" if payload.action in DEPLOY_ACTIONS else "runtime", service.slug
    )
    old = (
        db.query(models.OperationRun)
        .filter_by(actor=actor.actor, idempotency_key=payload.idempotency_key)
        .one_or_none()
    )
    if old:
        if old.service_id != service.id or old.plan["request"] != payload.model_dump():
            raise HTTPException(409, "idempotency key reused with different request")
        return old
    try:
        snapshot = current_snapshot(db, service, payload)
    except runtime.DockerUnavailable as e:
        raise HTTPException(503, str(e)) from None
    run = models.OperationRun(
        service_id=service.id,
        runtime_id=payload.runtime_id,
        actor=actor.actor,
        action=payload.action,
        status="planned",
        idempotency_key=payload.idempotency_key,
        plan_hash=digest(snapshot),
        plan=snapshot,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(run)
    log_activity(
        db,
        "operation.plan",
        "service",
        service.id,
        {"action": payload.action},
        actor=actor.actor,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "idempotency key was concurrently registered"
        ) from None
    return run


def serialize_admission(func):
    from functools import wraps

    @wraps(func)
    def wrapped(*args, **kwargs):
        with operation_lock("queue-admission"):
            return func(*args, **kwargs)

    return wrapped


@serialize_admission
def queue_operation(db, run, payload, actor):
    service = db.get(models.Service, run.service_id)
    actor.check("deploy" if run.action in DEPLOY_ACTIONS else "runtime", service.slug)
    if actor.actor != run.actor:
        raise HTTPException(403, "only the plan owner may execute it")
    if payload.plan_hash != run.plan_hash:
        raise HTTPException(412, "plan hash mismatch")
    if run.status != "planned":
        return False
    pending = (
        db.query(models.OperationRun)
        .filter(models.OperationRun.status.in_(["queued", "running"]))
        .count()
    )
    if pending >= get_settings().max_pending_operations:
        raise HTTPException(429, "operation queue capacity reached")
    if run.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(412, "plan expired")
    if not payload.approved:
        raise HTTPException(403, "explicit plan approval required")
    if run.plan["dependency_findings"]:
        raise HTTPException(
            409,
            {"message": "plan blocked", "findings": run.plan["dependency_findings"]},
        )
    if not get_settings().runtime_apply_enabled:
        raise HTTPException(403, "runtime execution is disabled by configuration")
    try:
        snapshot = current_snapshot(db, service, OperationInput(**run.plan["request"]))
    except runtime.DockerUnavailable as e:
        raise HTTPException(503, str(e)) from None
    if digest(snapshot) != run.plan_hash:
        raise HTTPException(
            412, "runtime, policy, registry or configuration changed; create a new plan"
        )
    # Compare-and-set prevents two HTTP requests enqueueing the same plan.
    try:
        changed = (
            db.query(models.OperationRun)
            .filter_by(id=run.id, status="planned")
            .update(
                {"status": "queued", "active_key": run.plan["project"]},
                synchronize_session=False,
            )
        )
        if not changed:
            db.rollback()
            return False
        log_activity(
            db,
            "operation.approve",
            "service",
            service.id,
            {"operation_id": run.id, "plan_hash": run.plan_hash},
            actor=actor.actor,
        )
        db.commit()
        db.refresh(run)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "another operation owns this Compose project"
        ) from None
    return True


def workflow(workflow_id):
    try:
        w = json.loads(get_settings().build_workflows)[workflow_id]
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "build workflow is not configured") from None
    argv = w.get("argv")
    cwd = w.get("cwd", "")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(x, str) for x in argv)
    ):
        raise HTTPException(422, "invalid registered workflow")
    safe_path(cwd, Path(get_settings().outsourced_build_area_root), exists=True)
    # Workflow argv is administrator-controlled configuration, never API supplied.
    return argv, cwd


def execute_workflow(workflow_id):
    argv, cwd = workflow(workflow_id)
    p = subprocess.run(
        argv,
        cwd=cwd,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=get_settings().operation_timeout_seconds,
        check=False,
    )
    if p.returncode:
        raise runtime.DockerUnavailable(
            f"registered workflow failed (exit {p.returncode})"
        )


def add_event(db, run, step):
    run.events = [
        *run.events,
        {"at": datetime.now(timezone.utc).isoformat(), "step": step},
    ]
    db.commit()


def run_operation(operation_id):
    with database.SessionLocal() as db:
        run = db.get(models.OperationRun, operation_id)
        if run is None or run.status != "queued":
            return
        release = None
        try:
            with (
                operation_lock("execution-slot", wait=True),
                operation_lock(run.plan["project"]),
            ):
                db.refresh(run)
                if run.status != "queued":
                    return
                if run.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
                    timezone.utc
                ):
                    raise RuntimeError("queued plan expired")
                service = db.get(models.Service, run.service_id)
                payload = OperationInput(**run.plan["request"])
                # Recheck after queue delay, before the first side effect.
                current = current_snapshot(db, service, payload)
                if digest(current) != run.plan_hash:
                    changed = [
                        k
                        for k in current
                        if digest(current[k]) != digest(run.plan.get(k))
                    ]
                    raise RuntimeError(
                        "queued plan became stale: " + ", ".join(changed)
                    )
                if not get_settings().runtime_apply_enabled:
                    raise RuntimeError("execution was disabled")
                run.status = "running"
                add_event(db, run, "validated")
                rt, path, project, config = runtime.runtime_config(
                    db, service, run.runtime_id
                )
                names = sorted(config["services"])
                sources = run.plan["sources"]
                action = run.action
                if action in {"start", "stop", "restart"}:
                    add_event(db, run, action)
                    runtime.backend.compose(path, project, [action, *names])
                    rows = runtime.backend.verify(
                        project, names, "exited" if action == "stop" else "running"
                    )
                    rt.desired_state = "stopped" if action == "stop" else "running"
                    run.result = {"containers": rows}
                elif action == "autostart":
                    policy = (
                        "unless-stopped"
                        if payload.autostart_policy == "always"
                        else "no"
                    )
                    ids = [c["id"] for c in run.plan["containers"]]
                    runtime.backend.run(["update", f"--restart={policy}", *ids])
                    rows = runtime.backend.containers(project)
                    if any(c["restart_policy"] != policy for c in rows):
                        raise RuntimeError("restart policy verification failed")
                    rt.autostart_policy = payload.autostart_policy
                    rt.restart_policy = policy
                    run.result = {
                        "restart_policy": policy,
                        "compose_drift": "Runtime policy changed. Compose restart definitions must be reconciled before the next deploy.",
                    }
                else:
                    previous = {
                        c["compose_service"]: c["image_id"]
                        for c in run.plan["containers"]
                    }
                    if action in {"deploy", "update", "rollback"}:
                        release = models.DeploymentRelease(
                            operation_id=run.id,
                            runtime_id=rt.id,
                            previous_images=previous,
                            compose_checksum=digest(config),
                        )
                        db.add(release)
                        db.commit()
                    if action in {"pull", "build", "update"}:
                        for source in sources:
                            kind = source["source_kind"]
                            name = source["compose_service"]
                            if kind == "registry_image":
                                runtime.backend.compose(path, project, ["pull", name])
                            elif kind == "compose_build":
                                runtime.backend.compose(path, project, ["build", name])
                            else:
                                execute_workflow(source["workflow_id"])
                            add_event(db, run, f"prepared:{name}")
                    images = (
                        run.plan["rollback"]["previous_images"]
                        if action == "rollback"
                        else {
                            s["compose_service"]: runtime.backend.image(s["image_ref"])[
                                "id"
                            ]
                            for s in sources
                        }
                    )
                    if action in {"deploy", "update", "rollback"}:
                        override = operation_dir() / f"{run.id}.yaml"
                        override.write_text(
                            yaml.safe_dump(
                                {
                                    "services": {
                                        n: {
                                            "image": image,
                                            "pull_policy": "never",
                                            "restart": rt.restart_policy
                                            or config["services"][n].get(
                                                "restart", "no"
                                            ),
                                        }
                                        for n, image in images.items()
                                    }
                                }
                            )
                        )
                        try:
                            add_event(db, run, "recreate")
                            runtime.backend.compose(
                                path,
                                project,
                                [
                                    "up",
                                    "-d",
                                    "--no-build",
                                    "--pull",
                                    "never",
                                    "--no-deps",
                                    *names,
                                ],
                                override=override,
                            )
                            rows = runtime.backend.verify(project, names, "running")
                            if any(
                                c["image_id"] != images.get(c["compose_service"])
                                for c in rows
                            ):
                                raise RuntimeError("image identity verification failed")
                            release.images = images
                            release.status = "completed"
                            rt.desired_state = "running"
                        finally:
                            override.unlink(missing_ok=True)
                    run.result = {
                        "images": images,
                        "release_id": release.id if release else None,
                    }
                if action in {"start", "restart", "deploy", "update", "rollback"}:
                    from .lifecycle.runner import run_healthchecks_for_service

                    checks = [
                        {
                            "id": c["id"],
                            "passed": c["passed"],
                            "check_type": c["check_type"],
                        }
                        for c in run_healthchecks_for_service(db, service.slug)
                    ]
                    run.result = {**run.result, "healthchecks": checks}
                    if any(not c["passed"] for c in checks):
                        raise RuntimeError(
                            "registered service healthcheck verification failed"
                        )
                run.status = "completed"
                run.active_key = None
                log_activity(
                    db,
                    "operation.completed",
                    "service",
                    run.service_id,
                    {"operation_id": run.id, "action": action},
                    actor=run.actor,
                )
                add_event(db, run, "verified")
        except Exception as exc:
            db.rollback()
            run = db.get(models.OperationRun, operation_id)
            # Never serialize arbitrary exception strings, SQL parameters or command output.
            from .redaction import clean

            reason = (
                str(exc)
                if isinstance(exc, (RuntimeError, runtime.DockerUnavailable))
                else "execution or verification failed; review operation steps"
            )
            run.status = "failed"
            run.active_key = None
            run.error = clean(f"{type(exc).__name__}: {reason}")
            if release:
                saved = db.get(models.DeploymentRelease, release.id)
                if saved:
                    saved.status = "failed"
            log_activity(
                db,
                "operation.failed",
                "service",
                run.service_id,
                {"operation_id": run.id, "error_type": type(exc).__name__},
                actor=run.actor,
            )
            add_event(db, run, "failed")


def recover_operations():
    with database.SessionLocal() as db:
        for run in db.query(models.OperationRun).filter(
            models.OperationRun.status.in_(["queued", "running"])
        ):
            try:
                with operation_lock(run.plan["project"]):
                    run.status = "interrupted"
                    run.active_key = None
                    run.error = (
                        "API worker interrupted; verify runtime and create a fresh plan"
                    )
                    log_activity(
                        db,
                        "operation.interrupted",
                        "service",
                        run.service_id,
                        {"operation_id": run.id},
                        actor="recovery",
                    )
            except HTTPException:
                continue
        db.commit()


def serialize_registry(func):
    from functools import wraps

    @wraps(func)
    def wrapped(*args, **kwargs):
        with operation_lock("registry-names"):
            return func(*args, **kwargs)

    return wrapped
