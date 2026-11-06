from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from control_plane.config import Settings, get_settings


class ManifestError(ValueError):
    pass


def manifest_path(slug: str, settings: Settings | None = None) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,78}[a-z0-9]", slug):
        raise ManifestError("invalid service slug")
    settings = settings or get_settings()
    return Path(settings.selfhost_root) / "stacks" / "services" / slug / "service.yaml"


def list_manifest_paths(settings: Settings | None = None) -> list[Path]:
    settings = settings or get_settings()
    root = Path(settings.selfhost_root) / "stacks" / "services"
    if not root.exists():
        return []
    return sorted(root.glob("*/service.yaml"))


def load_manifest(slug: str, settings: Settings | None = None) -> dict[str, Any]:
    path = manifest_path(slug, settings)
    if not path.exists():
        raise ManifestError(f"service manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    validate_manifest(slug, data, path, settings=settings)
    return data


def load_all_manifests(settings: Settings | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in list_manifest_paths(settings):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        slug = path.parent.name
        validate_manifest(slug, data, path, settings=settings)
        items.append(data)
    return items


def validate_manifest(slug: str, data: dict[str, Any], path: Path, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    service = data.get("service") or {}
    lifecycle = data.get("lifecycle") or {}
    runtime = data.get("runtime") or {}
    paths = data.get("paths") or {}

    if service.get("slug") != slug:
        raise ManifestError(f"manifest slug mismatch in {path}: expected {slug}, got {service.get('slug')}")
    if not service.get("name"):
        raise ManifestError(f"manifest service.name missing: {path}")
    if not service.get("category"):
        raise ManifestError(f"manifest service.category missing: {path}")
    if not isinstance(lifecycle.get("archivable"), bool):
        raise ManifestError(f"manifest lifecycle.archivable must be boolean: {path}")
    if not isinstance(lifecycle.get("snapshot_supported"), bool):
        raise ManifestError(f"manifest lifecycle.snapshot_supported must be boolean: {path}")
    if runtime.get("backend") != "docker_compose":
        raise ManifestError(f"only docker_compose lifecycle backend is supported in v1: {path}")
    if runtime.get("compose_project") != slug:
        raise ManifestError(f"runtime.compose_project must equal slug {slug}: {path}")

    compose_file = Path(str(runtime.get("compose_file") or paths.get("compose_file") or ""))
    stack_root = (Path(settings.selfhost_root) / "stacks" / "services" / slug).resolve()
    if stack_root not in compose_file.resolve().parents:
        raise ManifestError("compose file outside service stack directory")
    if not compose_file.exists():
        raise ManifestError(f"compose file not found: {compose_file}")

    allowed_roots = [
        Path(settings.selfhost_root).resolve(),
        Path(settings.outsourced_build_area_root).resolve(),
    ]
    expected = {k: Path(settings.selfhost_root) / folder / "services" / slug for k,folder in {"stack_dir":"stacks", "compose_file":"stacks", "data_dir":"data", "docs_dir":"docs", "app_dir":"apps", "config_file":"stacks", "config_files":"stacks"}.items()}
    expected["build_area_dir"] = Path(settings.outsourced_build_area_root) / "services" / slug
    expected["env_files"] = Path(settings.selfhost_root) / "secrets"
    for key, value in paths.items():
        if key not in expected:
            raise ManifestError("unknown lifecycle path role")
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is None:
                continue
            candidate = Path(str(item)).expanduser()
            if not candidate.is_absolute():
                raise ManifestError(f"manifest path must be absolute for paths.{key}: {item}")
            resolved = candidate.resolve(strict=False)
            role_root = expected[key].resolve()
            if not (resolved == role_root or role_root in resolved.parents):
                raise ManifestError(f"path escapes service ownership: {key}")
            if not any(resolved == root or root in resolved.parents for root in allowed_roots):
                raise ManifestError(f"manifest path outside allowed roots for paths.{key}: {item}")


def manifest_summary(slug: str, data: dict[str, Any]) -> dict[str, Any]:
    service = data.get("service") or {}
    lifecycle = data.get("lifecycle") or {}
    runtime = data.get("runtime") or {}
    return {
        "slug": slug,
        "name": service.get("name"),
        "category": service.get("category"),
        "status": service.get("status"),
        "archivable": lifecycle.get("archivable"),
        "snapshot_supported": lifecycle.get("snapshot_supported"),
        "compose_project": runtime.get("compose_project"),
        "compose_file": runtime.get("compose_file"),
    }
