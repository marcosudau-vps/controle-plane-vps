from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from control_plane import models
from control_plane.config import Settings, get_settings
from control_plane.generators import generate_caddy
from control_plane.lifecycle.manifests import load_manifest
from control_plane.lifecycle.planner import build_service_plan, db_inventory, object_dict, path_inventory, stable_plan_hash
from control_plane.service import log_activity


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive_root(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.lifecycle_archive_root)


def archive_dir_for(slug: str, action: str, settings: Settings | None = None) -> Path:
    return archive_root(settings) / slug / f"{run_id()}-{action}-{uuid4().hex[:8]}"


def compose_command(compose_file: Path, *args: str) -> list[str]:
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], text=True, capture_output=True, check=False)
        if probe.returncode == 0:
            return ["docker", "compose", "-f", str(compose_file), *args]
    if shutil.which("docker-compose"):
        return ["docker-compose", "-f", str(compose_file), *args]
    raise HTTPException(status_code=500, detail="neither 'docker compose' nor 'docker-compose' is available")


@contextmanager
def lifecycle_lock(slug: str, settings: Settings | None = None):
    from control_plane.operations import operation_lock
    with operation_lock(slug):
        yield


def ensure_hash(current_plan: dict[str, Any], plan_hash: str) -> None:
    if current_plan.get("plan_hash") != plan_hash:
        raise HTTPException(status_code=409, detail={"message": "plan_hash does not match current plan", "current_plan_hash": current_plan.get("plan_hash")})
    if current_plan.get("blocked"):
        raise HTTPException(status_code=409, detail=current_plan.get("block_reason") or "lifecycle operation blocked")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_entry(source: Path, target: Path, *, apply_excludes: bool = True) -> None:
    if not (source.exists() or source.is_symlink()):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        ignore = ignore_build_artifacts if apply_excludes else None
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True, ignore=ignore)
    elif source.is_symlink():
        target.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, target, follow_symlinks=False)


def collect_path_metadata(source: Path) -> list[dict[str, Any]]:
    if not (source.exists() or source.is_symlink()):
        return []
    paths = [source]
    if source.is_dir() and not source.is_symlink():
        paths.extend(sorted(source.rglob("*")))
    metadata: list[dict[str, Any]] = []
    for path in paths:
        stat = path.lstat()
        if path == source:
            rel = "."
        else:
            rel = str(path.relative_to(source))
        metadata.append(
            {
                "path": rel,
                "uid": stat.st_uid,
                "gid": stat.st_gid,
                "mode": stat.st_mode & 0o7777,
                "kind": "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file",
            }
        )
    return metadata


def apply_path_metadata(target: Path, metadata: list[dict[str, Any]]) -> None:
    if not metadata:
        return
    for item in sorted(metadata, key=lambda row: str(row["path"]).count("/"), reverse=True):
        rel = item["path"]
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise HTTPException(status_code=409, detail="invalid archive path metadata")
        path = target if rel == "." else target / rel
        if target.resolve() != path.resolve() and target.resolve() not in path.resolve().parents:
            raise HTTPException(status_code=409, detail="archive metadata symlink escape")
        if not (path.exists() or path.is_symlink()):
            continue
        os.chown(path, int(item["uid"]), int(item["gid"]), follow_symlinks=False)
        if item.get("kind") != "symlink":
            os.chmod(path, int(item["mode"]) & 0o777)


def ignore_build_artifacts(_dir: str, names: list[str]) -> set[str]:
    excluded = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "dist", "build", "site-staging"}
    return {name for name in names if name in excluded}


def checksums(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            result[rel] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            result[rel] = sha256_file(path)
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def create_archive_bundle(db: Session, slug: str, action: str, plan: dict[str, Any], target_dir: Path, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    manifest = load_manifest(slug, settings=settings)
    payload = target_dir / "payload"
    payload.mkdir(parents=True, exist_ok=True, mode=0o700)
    target_dir.chmod(0o700)
    copied: list[dict[str, str]] = []
    path_metadata: dict[str, list[dict[str, Any]]] = {}
    for entry in path_inventory(manifest):
        source = Path(entry["path"])
        if not (source.exists() or source.is_symlink()):
            continue
        dest = payload / entry["role"] / source.name
        metadata = collect_path_metadata(source)
        copy_entry(source, dest, apply_excludes=entry["role"] != "data_dir")
        payload_path = str(dest.relative_to(target_dir))
        copied.append({"role": entry["role"], "source": str(source), "payload_path": payload_path})
        path_metadata[payload_path] = metadata
    db_export = db_inventory(db, slug)
    archive_id = str(target_dir.relative_to(archive_root(settings)))
    restore_plan = build_restore_plan_from_metadata(archive_id, target_dir, copied, db_export)
    write_json(target_dir / "manifest.json", {"archive_id": archive_id, "service_slug": slug, "action": action, "created_at": run_id(), "format": "tar.zst+json"})
    write_json(target_dir / "service.yaml.json", manifest)
    shutil.copy2(Path(settings.selfhost_root) / "stacks" / "services" / slug / "service.yaml", target_dir / "service.yaml")
    write_json(target_dir / "inventory.json", plan["inventory"])
    write_json(target_dir / "db-export.json", db_export)
    write_json(target_dir / "plan.json", plan)
    write_json(target_dir / "restore-plan.json", restore_plan)
    write_json(target_dir / "path-metadata.json", path_metadata)
    write_json(target_dir / "checksums.json", checksums(payload))
    archive_path = target_dir / "archive.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive_path), "-C", str(target_dir), "payload"], check=True)
    archive_path.chmod(0o600)
    return {"archive_id": archive_id, "archive_dir": str(target_dir), "archive_path": str(archive_path), "copied": copied}


def build_restore_plan_from_metadata(archive_id: str, target_dir: Path, copied: list[dict[str, str]], db_export: dict[str, Any]) -> dict[str, Any]:
    targets = []
    for item in copied:
        targets.append({"role": item["role"], "target": item["source"], "payload_path": item["payload_path"]})
    plan = {
        "action": "restore",
        "archive_id": archive_id,
        "archive_dir": str(target_dir),
        "service_slug": (db_export.get("service") or {}).get("slug") or target_dir.parent.name,
        "targets": targets,
        "database": {"service_slug": (db_export.get("service") or {}).get("slug"), "objects": {k: len(v) for k, v in db_export.items() if isinstance(v, list)}},
        "steps": ["restore-files", "restore-db-state", "activate-routes-and-ports", "start-compose", "run-healthchecks"],
    }
    plan["plan_hash"] = stable_plan_hash(plan)
    return plan


def record_run(db: Session, *, slug: str, action: str, status: str, plan_hash: str, result: dict[str, Any], error: str = "") -> models.LifecycleRun:
    run = models.LifecycleRun(
        service_slug=slug,
        action=action,
        status=status,
        plan_hash=plan_hash,
        archive_dir=result.get("archive_dir", ""),
        archive_path=result.get("archive_path", ""),
        quarantine_dir=result.get("quarantine_dir", ""),
        request_json={"plan_hash": plan_hash},
        result_json=result,
        error=error,
    )
    db.add(run)
    log_activity(db, f"lifecycle.{action}.{status}", "service", "", {"slug": slug, **result})
    db.commit()
    return run


def execute_snapshot(db: Session, slug: str, plan_hash: str) -> dict[str, Any]:
    with lifecycle_lock(slug):
        plan = build_service_plan(db, slug, "snapshot")
        ensure_hash(plan, plan_hash)
        target_dir = archive_dir_for(slug, "snapshot")
        result = create_archive_bundle(db, slug, "snapshot", plan, target_dir)
        run = record_run(db, slug=slug, action="snapshot", status="completed", plan_hash=plan_hash, result=result)
        return {**result, "run_id": run.id}


def execute_archive(db: Session, slug: str, plan_hash: str) -> dict[str, Any]:
    settings = get_settings()
    with lifecycle_lock(slug, settings):
        plan = build_service_plan(db, slug, "archive", settings=settings)
        ensure_hash(plan, plan_hash)
        manifest = load_manifest(slug, settings=settings)
        compose_file = Path(manifest["runtime"]["compose_file"])
        if settings.lifecycle_runtime_apply_enabled:
            subprocess.run(compose_command(compose_file, "down"), check=True)
        target_dir = archive_dir_for(slug, "archive", settings=settings)
        result = create_archive_bundle(db, slug, "archive", plan, target_dir, settings=settings)
        service = db.query(models.Service).filter(models.Service.slug == slug).one_or_none()
        if service:
            service.status = "archived"
            for route in service.routes:
                route.status = "inactive"
            for port in service.ports:
                port.status = "inactive"
        db.flush()
        generate_caddy(db)
        validate_caddy_if_enabled(settings)
        quarantine_dir = target_dir / "quarantine"
        moved = quarantine_paths(manifest, quarantine_dir)
        result["quarantine_dir"] = str(quarantine_dir)
        result["quarantined"] = moved
        run = record_run(db, slug=slug, action="archive", status="completed", plan_hash=plan_hash, result=result)
        return {**result, "run_id": run.id}


def quarantine_paths(manifest: dict[str, Any], quarantine_dir: Path) -> list[dict[str, str]]:
    moved: list[dict[str, str]] = []
    for entry in path_inventory(manifest):
        if not entry.get("quarantine"):
            continue
        source = Path(entry["path"])
        if not (source.exists() or source.is_symlink()):
            continue
        target = quarantine_dir / entry["role"] / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append({"role": entry["role"], "source": str(source), "quarantine_path": str(target)})
    return moved


def resolve_archive_dir(identifier: str | None = None, *, archive_dir: str | None = None, archive_path: str | None = None) -> Path:
    if archive_dir:
        candidate = Path(archive_dir)
    elif archive_path:
        candidate = Path(archive_path).parent
    elif identifier:
        candidate = archive_root() / identifier
    else:
        raise HTTPException(status_code=400, detail="archive identifier required")
    root = archive_root().resolve()
    if ".." in candidate.parts or root not in candidate.resolve().parents:
        raise HTTPException(status_code=422, detail="archive path outside configured archive root")
    return candidate.resolve()


def verify_archive_payload(directory: Path) -> None:
    expected = json.loads((directory / "checksums.json").read_text())
    root = (directory / "payload").resolve()
    for rel in expected:
        candidate = root / rel
        if Path(rel).is_absolute() or ".." in Path(rel).parts or root not in candidate.resolve().parents:
            raise HTTPException(status_code=409, detail="archive payload path or symlink escapes payload")
    if (directory / "payload").exists() and checksums(directory / "payload") != expected:
        raise HTTPException(status_code=409, detail="archive payload checksum mismatch")


def extract_verified_payload(directory: Path) -> None:
    # Two passes: reject unsafe members before any write, then extract using Python's data filter.
    for extract in [False, True]:
        process = subprocess.Popen(["zstd", "-dc", str(directory / "archive.tar.zst")], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    path = Path(member.name)
                    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "payload" or not (member.isfile() or member.isdir()):
                        raise HTTPException(status_code=409, detail="unsafe archive member")
                    if extract:
                        archive.extract(member, path=directory, filter="data")
            if process.wait() != 0:
                raise HTTPException(status_code=409, detail="archive decompression failed")
        finally:
            if process.poll() is None:process.kill()
            process.wait()
    verify_archive_payload(directory)


def inspect_archive(identifier: str | None = None, *, archive_dir: str | None = None, archive_path: str | None = None) -> dict[str, Any]:
    directory = resolve_archive_dir(identifier, archive_dir=archive_dir, archive_path=archive_path)
    if not directory.exists():
        raise HTTPException(status_code=404, detail=f"archive not found: {directory}")
    payload = {}
    for name in ["manifest.json", "plan.json", "restore-plan.json", "checksums.json"]:
        path = directory / name
        if path.exists():
            payload[name.removesuffix(".json").replace("-", "_")] = json.loads(path.read_text(encoding="utf-8"))
    if "restore_plan" not in payload or "checksums" not in payload:
        raise HTTPException(status_code=409, detail="archive metadata is incomplete")
    verify_archive_payload(directory)
    slug = payload.get("manifest", {}).get("service_slug", "")
    from control_plane.contracts import CORE_SERVICES
    if slug in CORE_SERVICES or not slug or "/" in slug or ".." in slug:
        raise HTTPException(status_code=409, detail="invalid or protected restore identity")
    role_roots = {k: Path(get_settings().selfhost_root) / folder / "services" / slug for k,folder in {"stack_dir":"stacks", "data_dir":"data", "app_dir":"apps", "docs_dir":"docs", "config_file":"stacks"}.items()}
    role_roots["build_area_dir"] = Path(get_settings().outsourced_build_area_root) / "services" / slug
    role_roots["env_file"] = Path(get_settings().selfhost_root) / "secrets"
    for item in payload["restore_plan"].get("targets", []):
        target = Path(item["target"]).resolve()
        allowed = role_roots.get(item.get("role"))
        source = directory / item["payload_path"]
        if allowed is None or not (target == allowed.resolve() or allowed.resolve() in target.parents):
            raise HTTPException(status_code=409, detail="restore target outside service ownership")
        if ".." in Path(item["payload_path"]).parts or (directory / "payload").resolve() not in source.resolve().parents:
            raise HTTPException(status_code=409, detail="restore payload path escape")
    payload["archive_dir"] = str(directory)
    payload["archive_path"] = str(directory / "archive.tar.zst")
    return payload


def plan_restore(identifier: str) -> dict[str, Any]:
    archive = inspect_archive(identifier)
    plan = archive.get("restore_plan") or {}
    conflicts = []
    for target in plan.get("targets", []):
        path = Path(target["target"])
        if path.exists():
            if target.get("role") in {"docs_dir", "env_file", "config_file"}:
                continue
            if path.is_dir() and not any(path.iterdir()):
                continue
            conflicts.append(str(path))
    plan["blocked"] = bool(conflicts)
    plan["conflicts"] = conflicts
    plan["plan_hash"] = stable_plan_hash(plan)
    return plan


def restore_db_state(db: Session, export: dict[str, Any]) -> str:
    service_data = export.get("service")
    if not service_data:
        return ""
    service = db.query(models.Service).filter(models.Service.slug == service_data["slug"]).one_or_none()
    service_fields = {k: service_data[k] for k in ["id", "slug", "title", "summary", "system", "component_type", "lifecycle", "owner", "criticality", "tags", "metadata_json", "port_base", "large_port_space", "caddy_protection_enabled"] if k in service_data}
    service_fields["status"] = "active"
    if service:
        for key, value in service_fields.items():
            setattr(service, key, value)
    else:
        service = models.Service(**service_fields)
        db.add(service)
        db.flush()

    for row in export.get("sub_services", []):
        row = dict(row)
        row.pop("created_at", None)
        row.pop("updated_at", None)
        row["parent_type"] = "service"
        row["parent_id"] = service.id
        obj = db.query(models.SubService).filter(models.SubService.id == row["id"]).one_or_none()
        if obj:
            for key, value in row.items():
                setattr(obj, key, value)
        else:
            db.add(models.SubService(**row))

    for model, rows, key_field in [
        (models.Route, export.get("routes", []), "id"),
        (models.Port, export.get("ports", []), "id"),
        (models.Runtime, export.get("runtimes", []), "id"),
        (models.DocRef, export.get("docs", []), "id"),
        (models.Healthcheck, export.get("healthchecks", []), "id"),
        (models.Resource, export.get("resources", []), "id"),
        (models.ApiEntity, export.get("apis", []), "id"),
        (models.Skill, export.get("skills", []), "id"),
        (models.SecretRef, export.get("secret_refs", []), "id"),
        (models.ServiceProfile, export.get("profiles", []), "service_id"),
        (models.ServiceAlias, export.get("aliases", []), "alias"),
        (models.DeploymentSource, export.get("deployment_sources", []), "id"),
        (models.RouteOptions, export.get("route_options", []), "route_id"),
        (models.PolicyRule, export.get("policies", []), "id"),
    ]:
        for row in rows:
            row = dict(row)
            row.pop("created_at", None)
            row.pop("updated_at", None)
            if "service_id" in row:
                row["service_id"] = service.id
            if model in {models.Route, models.Port}:
                row["status"] = "active"
            obj = db.query(model).filter(getattr(model, key_field) == row[key_field]).one_or_none()
            if obj:
                for key, value in row.items():
                    setattr(obj, key, value)
            else:
                db.add(model(**row))
    return service.slug


def _execute_restore(db: Session, archive_id: str, plan_hash: str) -> dict[str, Any]:
    settings = get_settings()
    plan = plan_restore(archive_id)
    if plan["plan_hash"] != plan_hash:
        raise HTTPException(status_code=409, detail={"message": "plan_hash does not match current restore plan", "current_plan_hash": plan["plan_hash"]})
    if plan.get("blocked"):
        raise HTTPException(status_code=409, detail={"message": "restore target conflicts", "conflicts": plan.get("conflicts", [])})
    archive = inspect_archive(archive_id)
    directory = Path(archive["archive_dir"])
    if not (directory / "payload").exists() and (directory / "archive.tar.zst").exists():
        extract_verified_payload(directory)
    for target in plan.get("targets", []):
        source = directory / target["payload_path"]
        destination = Path(target["target"])
        if destination.exists() and not (destination.is_dir() and not any(destination.iterdir())):
            continue
        copy_entry(source, destination, apply_excludes=False)
        metadata_path = directory / "path-metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")).get(target["payload_path"], [])
            apply_path_metadata(destination, metadata)
    export = json.loads((directory / "db-export.json").read_text(encoding="utf-8"))
    slug = restore_db_state(db, export)
    db.flush()
    generate_caddy(db)
    validate_caddy_if_enabled(settings)
    manifest = load_manifest(slug, settings=settings)
    compose_file = Path(manifest["runtime"]["compose_file"])
    if settings.lifecycle_runtime_apply_enabled:
        subprocess.run(compose_command(compose_file, "up", "-d", "--no-build", "--pull", "never"), check=True)
    healthcheck_results = run_healthchecks_for_service(db, slug) if settings.lifecycle_runtime_apply_enabled else []
    if any(not item["passed"] for item in healthcheck_results):
        raise HTTPException(status_code=409, detail="restored runtime failed health verification")
    result = {"archive_id": archive_id, "archive_dir": str(directory), "service_slug": slug, "restored_targets": [item["target"] for item in plan.get("targets", [])], "healthchecks": healthcheck_results}
    run = record_run(db, slug=slug, action="restore", status="completed", plan_hash=plan_hash, result=result)
    return {**result, "run_id": run.id}


def validate_caddy_if_enabled(settings: Settings) -> None:
    if not settings.lifecycle_runtime_apply_enabled:
        return
    result = subprocess.run(["caddy", "validate", "--config", settings.caddyfile_path], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise HTTPException(status_code=409, detail={"message": "caddy validate failed", "stderr": result.stderr})


def run_healthchecks_for_service(db: Session, slug: str) -> list[dict[str, Any]]:
    service = db.query(models.Service).filter(models.Service.slug == slug).one_or_none()
    if not service:
        return []
    results: list[dict[str, Any]] = []
    for check in service.healthchecks:
        passed = False
        error = ""
        if check.check_type == "http":
            try:
                with urllib.request.urlopen(check.target, timeout=check.timeout_seconds) as response:
                    passed = response.status == check.expected_status
                    if not passed:
                        error = f"expected {check.expected_status}, got {response.status}"
            except urllib.error.HTTPError as exc:
                passed = exc.code == check.expected_status
                if not passed:
                    error = f"expected {check.expected_status}, got {exc.code}"
            except Exception as exc:
                error = str(exc)
        elif check.check_type == "tcp":
            error = "tcp healthcheck execution is not implemented in lifecycle restore v1"
        results.append({"id": check.id, "target": check.target, "check_type": check.check_type, "passed": passed, "error": error})
    return results


def execute_restore(db: Session, archive_id: str, plan_hash: str) -> dict[str, Any]:
    archive = inspect_archive(archive_id)
    slug = archive['manifest']['service_slug']
    with lifecycle_lock(slug):
        return _execute_restore(db, archive_id, plan_hash)
