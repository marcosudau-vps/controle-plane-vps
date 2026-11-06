from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from control_plane import models
from control_plane.config import Settings, get_settings
from control_plane.lifecycle.manifests import load_manifest, manifest_summary


ARCHIVE_EXCLUDES = [
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "dist",
    "build",
    "site-staging",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def object_dict(obj: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[column.name] = value
    return result


def db_inventory(db: Session, slug: str) -> dict[str, Any]:
    service = db.query(models.Service).filter(models.Service.slug == slug).one_or_none()
    if not service:
        return {"service": None, "routes": [], "ports": [], "runtimes": [], "resources": [], "apis": [], "skills": [], "secret_refs": [], "docs": [], "healthchecks": [], "sub_services": []}
    runtime_ids = [r.id for r in service.runtimes]
    route_ids = [r.id for r in service.routes]
    return {
        "profiles": [object_dict(x) for x in db.query(models.ServiceProfile).filter_by(service_id=service.id)],
        "aliases": [object_dict(x) for x in db.query(models.ServiceAlias).filter_by(service_id=service.id)],
        "deployment_sources": [object_dict(x) for x in db.query(models.DeploymentSource).filter(models.DeploymentSource.runtime_id.in_(runtime_ids))],
        "route_options": [object_dict(x) for x in db.query(models.RouteOptions).filter(models.RouteOptions.route_id.in_(route_ids))],
        "policies": [object_dict(x) for x in db.query(models.PolicyRule).filter_by(service_id=service.id)],
        "service": object_dict(service),
        "routes": [object_dict(item) for item in service.routes],
        "ports": [object_dict(item) for item in service.ports],
        "runtimes": [object_dict(item) for item in service.runtimes],
        "resources": [object_dict(item) for item in service.resources],
        "apis": [object_dict(item) for item in service.apis],
        "skills": [object_dict(item) for item in service.skills],
        "secret_refs": [object_dict(item) for item in service.secret_refs],
        "docs": [object_dict(item) for item in service.docs],
        "healthchecks": [object_dict(item) for item in service.healthchecks],
        "sub_services": [object_dict(item) for item in db.query(models.SubService).filter(models.SubService.parent_type == "service", models.SubService.parent_id == service.id).all()],
    }


def _compose_env_files(compose_file: Path) -> list[str]:
    try:
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    env_files: list[str] = []
    for service in (data.get("services") or {}).values():
        raw = service.get("env_file") if isinstance(service, dict) else None
        values = raw if isinstance(raw, list) else [raw] if raw else []
        for value in values:
            if isinstance(value, str) and value.startswith("/home/marco/selfhost/secrets/"):
                env_files.append(value)
    return sorted(set(env_files))


def path_inventory(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    paths = manifest.get("paths") or {}
    runtime = manifest.get("runtime") or {}
    compose_file = Path(str(runtime.get("compose_file") or paths.get("compose_file")))
    entries: list[dict[str, Any]] = []

    def add(role: str, value: str | None, *, quarantine: bool, remove_on_archive: bool, secret: bool = False) -> None:
        if not value:
            return
        path = Path(value)
        entries.append(
            {
                "role": role,
                "path": str(path),
                "exists": path.exists() or path.is_symlink(),
                "kind": "directory" if path.is_dir() else "file" if path.exists() else "missing",
                "archive": True,
                "quarantine": quarantine,
                "remove_on_archive": remove_on_archive,
                "secret": secret,
            }
        )

    add("stack_dir", paths.get("stack_dir"), quarantine=True, remove_on_archive=True)
    add("data_dir", paths.get("data_dir"), quarantine=True, remove_on_archive=True)
    add("app_dir", paths.get("app_dir"), quarantine=True, remove_on_archive=True)
    add("build_area_dir", paths.get("build_area_dir"), quarantine=True, remove_on_archive=True)
    add("docs_dir", paths.get("docs_dir"), quarantine=False, remove_on_archive=False)

    if paths.get("config_file"):
        add("config_file", paths.get("config_file"), quarantine=False, remove_on_archive=False)
    for item in paths.get("config_files") or []:
        add("config_file", item, quarantine=False, remove_on_archive=False)
    for item in paths.get("env_files") or []:
        add("env_file", item, quarantine=False, remove_on_archive=False, secret=True)
    for item in _compose_env_files(compose_file):
        add("env_file", item, quarantine=False, remove_on_archive=False, secret=True)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for entry in entries:
        key = entry["path"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def stable_plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key not in {"created_at", "plan_hash"}}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_service_plan(db: Session, slug: str, action: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    manifest = load_manifest(slug, settings=settings)
    lifecycle = manifest.get("lifecycle") or {}
    compose_check = compose_config_check(Path(manifest["runtime"]["compose_file"]))
    from control_plane.contracts import protected, CORE_SERVICES
    service = db.query(models.Service).filter_by(slug=slug).one_or_none()
    core_protected = slug in CORE_SERVICES or (service is not None and protected(db, service))
    if action == "archive" and core_protected:
        blocked = True
        block_reason = "protected core service cannot be archived"
    elif action == "archive" and not lifecycle.get("archivable"):
        blocked = True
        block_reason = "service is not archivable"
    elif action == "snapshot" and not lifecycle.get("snapshot_supported"):
        blocked = True
        block_reason = "snapshot is not supported"
    elif not compose_check["ok"]:
        blocked = True
        block_reason = "docker compose config failed"
    else:
        blocked = False
        block_reason = ""
    inventory = {
        "manifest": manifest_summary(slug, manifest),
        "paths": path_inventory(manifest),
        "database": db_inventory(db, slug),
    }
    plan = {
        "action": action,
        "service_slug": slug,
        "created_at": utc_now_iso(),
        "blocked": blocked,
        "block_reason": block_reason,
        "compose_check": compose_check,
        "archive_root": str(Path(settings.lifecycle_archive_root)),
        "archive_format": "tar.zst+json",
        "route_handling": "deactivate" if action == "archive" else "preserve",
        "active_path_handling": "quarantine" if action == "archive" else "preserve",
        "excludes": ARCHIVE_EXCLUDES,
        "inventory": inventory,
        "steps": _steps_for(action, blocked),
    }
    plan["plan_hash"] = stable_plan_hash(plan)
    return plan


def compose_config_check(compose_file: Path) -> dict[str, Any]:
    commands: list[list[str]] = []
    if shutil.which("docker"):
        commands.append(["docker", "compose", "-f", str(compose_file), "config", "-q"])
    if shutil.which("docker-compose"):
        commands.append(["docker-compose", "-f", str(compose_file), "config", "-q"])
    if not commands:
        return {"ok": False, "command": "", "stderr": "neither docker compose nor docker-compose is available"}
    result = subprocess.run(commands[0], text=True, capture_output=True, check=False)
    return {"ok": result.returncode == 0, "command": " ".join(commands[0]), "returncode": result.returncode, "stderr": result.stderr[-2000:]}


def _steps_for(action: str, blocked: bool) -> list[str]:
    if blocked:
        return ["refuse-execute"]
    if action == "snapshot":
        return ["collect-inventory", "copy-files", "write-manifests", "create-tar-zst", "record-run"]
    if action == "archive":
        return [
            "collect-inventory",
            "stop-compose",
            "copy-files",
            "write-manifests",
            "create-tar-zst",
            "deactivate-routes-and-ports",
            "set-service-archived",
            "generate-and-validate-caddy",
            "move-active-paths-to-quarantine",
            "record-run",
        ]
    if action == "restore":
        return ["inspect-archive", "restore-files", "restore-db-state", "activate-routes-and-ports", "start-compose", "run-healthchecks", "record-run"]
    return []
