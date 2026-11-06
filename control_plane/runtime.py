"""Bounded Docker CLI adapter. All methods use argv and safe output projections."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import yaml
from fastapi import HTTPException
from . import models
from .config import get_settings
from .contracts import safe_path, CORE_SERVICES

NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}$")
COMPOSE_NAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
)


class DockerUnavailable(RuntimeError):
    pass


class DockerBackend:
    def run(self, args, timeout=30):
        # Do not inherit Docker/Compose context or interpolation switches from the API process.
        env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "HOME", "LANG", "SSL_CERT_FILE"}
        }
        try:
            p = subprocess.run(
                ["docker", "--host", "unix:///var/run/docker.sock", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DockerUnavailable("Docker command unavailable or timed out") from None
        if p.returncode:
            # Compose/build stderr can include credentials; do not put it in DB/API/logs.
            raise DockerUnavailable(f"Docker command failed (exit {p.returncode})")
        return p.stdout

    def json_lines(self, args):
        raw = self.run(args)
        try:
            data = json.loads(raw) if raw.strip() else []
            return data if isinstance(data, list) else [data]
        except ValueError:
            try:
                return [json.loads(x) for x in raw.splitlines() if x.strip()]
            except ValueError:
                raise DockerUnavailable("invalid Docker response") from None

    def containers(self, project=None):
        args = ["ps", "-aq"]
        if project:
            args += ["--filter", f"label=com.docker.compose.project={project}"]
        ids = self.run(args).split()
        rows = []
        for i in range(0, len(ids), 50):
            for item in self.json_lines(["inspect", *ids[i : i + 50]]):
                config = item.get("Config") or {}
                state = item.get("State") or {}
                labels = config.get("Labels") or {}
                rows.append(
                    {
                        "id": item["Id"],
                        "name": item.get("Name", "").lstrip("/"),
                        "image_id": item.get("Image"),
                        "image_ref": config.get("Image"),
                        "project": labels.get("com.docker.compose.project"),
                        "compose_service": labels.get("com.docker.compose.service"),
                        "compose_file": labels.get(
                            "com.docker.compose.project.config_files"
                        ),
                        "state": state.get("Status", "unknown"),
                        "health": (state.get("Health") or {}).get("Status", "none"),
                        "restart_count": item.get("RestartCount", 0),
                        "restart_policy": (
                            item.get("HostConfig", {}).get("RestartPolicy") or {}
                        ).get("Name", "no"),
                    }
                )
        return rows

    def metrics(self, ids):
        if not ids:
            return []
        rows = self.json_lines(["stats", "--no-stream", "--format", "{{json .}}", *ids])
        return [
            {
                "id": x.get("ID"),
                "name": x.get("Name"),
                "cpu": x.get("CPUPerc"),
                "memory": x.get("MemUsage"),
                "memory_percent": x.get("MemPerc"),
            }
            for x in rows
        ]

    def image(self, reference):
        rows = self.json_lines(["image", "inspect", reference])
        if not rows:
            raise DockerUnavailable("required image is unavailable")
        obj = rows[0]
        return {
            "id": obj["Id"],
            "tags": obj.get("RepoTags", []),
            "digests": obj.get("RepoDigests", []),
            "size": obj.get("Size"),
        }

    def compose(self, path, project, args, *, override=None):
        argv = [
            "compose",
            "--project-directory",
            str(path.parent),
            "-p",
            project,
            "-f",
            str(path),
        ]
        if override:
            argv += ["-f", str(override)]
        return self.run(
            [*argv, *args], timeout=get_settings().operation_timeout_seconds
        )

    def verify(self, project, names, expected):
        import time

        for _ in range(30):
            rows = self.containers(project)
            targets = [r for r in rows if r["compose_service"] in names]
            found = {r["compose_service"] for r in targets}
            if found == set(names) and all(
                r["state"] == expected
                and (
                    expected == "exited" or r["health"] not in {"unhealthy", "starting"}
                )
                for r in targets
            ):
                return targets
            if expected == "exited" or any(r["health"] == "unhealthy" for r in targets):
                break
            time.sleep(1)
        raise DockerUnavailable(
            "runtime verification failed; inspect service health before retrying"
        )


backend = DockerBackend()


def runtime_config(db, service, runtime_id):
    runtime = db.get(models.Runtime, runtime_id)
    if not runtime or runtime.service_id != service.id:
        raise HTTPException(404, "runtime not found for this service")
    if runtime.runtime_type != "docker-compose":
        raise HTTPException(
            422, "runtime operations support registered docker-compose runtimes"
        )
    root = Path(get_settings().selfhost_root) / "stacks" / "services"
    p = safe_path(runtime.path, root, exists=True)
    aliases = [
        a.alias for a in db.query(models.ServiceAlias).filter_by(service_id=service.id)
    ]
    owned = [(root / slug).resolve() for slug in [service.slug, *aliases]]
    if not any(p == directory or directory in p.parents for directory in owned):
        raise HTTPException(422, "runtime path belongs to another service")
    if p.is_dir():
        candidates = [p / n for n in COMPOSE_NAMES if (p / n).is_file()]
        if len(candidates) != 1:
            raise HTTPException(422, "exactly one registered Compose file required")
        p = safe_path(str(candidates[0]), root, exists=True)
    if not p.is_file() or p.suffix not in {".yml", ".yaml"}:
        raise HTTPException(422, "registered path must be a Compose YAML file")
    project = runtime.compose_project or service.slug
    if project in CORE_SERVICES and service.slug not in CORE_SERVICES:
        raise HTTPException(403, "reserved infrastructure project")
    if not NAME.fullmatch(project) or project.startswith("-"):
        raise HTTPException(422, "invalid registered Compose project name")
    # Reject shared project ownership: commands affect a whole project, not only its registry row.
    for other in db.query(models.Runtime).filter(models.Runtime.id != runtime.id):
        other_service = db.get(models.Service, other.service_id)
        if (other.compose_project or other_service.slug) == project:
            raise HTTPException(409, "Compose project has multiple runtime owners")
    try:
        raw = p.read_bytes()
        config = yaml.safe_load(raw) or {}
        services = config["services"]
        if not isinstance(services, dict) or not services:
            raise ValueError()
        if any(
            not NAME.fullmatch(n) or not isinstance(s, dict)
            for n, s in services.items()
        ):
            raise ValueError()
        # Multi-file extension semantics cannot be hashed by a single-file planner.
        if config.get("include") or any(s.get("extends") for s in services.values()):
            raise HTTPException(
                422,
                "register a flattened Compose definition for include/extends projects",
            )
    except (KeyError, ValueError, TypeError, yaml.YAMLError, OSError):
        raise HTTPException(422, "invalid registered Compose file") from None
    owned_roots = [p.parent.resolve()]
    for slug in [service.slug, *aliases]:
        owned_roots.extend(
            (
                Path(get_settings().selfhost_root) / category / "services" / slug
            ).resolve()
            for category in ["apps", "data", "stacks"]
        )
        owned_roots.append(
            (
                Path(get_settings().outsourced_build_area_root) / "services" / slug
            ).resolve()
        )
    explicit_secrets = {
        str(Path(ref.ref).resolve())
        for ref in service.secret_refs
        if ref.provider == "file" and Path(ref.ref).is_absolute()
    }

    def owned_file(raw, *, readonly=False):
        candidate = Path(str(raw))
        candidate = candidate if candidate.is_absolute() else p.parent / candidate
        resolved = candidate.resolve()
        if any(resolved == base or base in resolved.parents for base in owned_roots):
            return
        secrets_root = (Path(get_settings().selfhost_root) / "secrets").resolve()
        own_secret = resolved.parent == secrets_root and any(
            resolved.name == slug + ".env" or resolved.name.startswith(slug + "-")
            for slug in [service.slug, *aliases]
        )
        if readonly and (
            own_secret
            or str(resolved) in explicit_secrets
            or str(resolved) in {"/etc/localtime", "/etc/timezone"}
        ):
            return
        raise HTTPException(
            422,
            "Compose path is outside service ownership or registered secret references",
        )

    for definition in services.values():
        build = definition.get("build")
        if build:
            context = build.get("context", ".") if isinstance(build, dict) else build
            owned_file(context)
            if isinstance(build, dict) and build.get("dockerfile"):
                base = Path(str(context))
                base = base if base.is_absolute() else p.parent / base
                owned_file(str(base / build["dockerfile"]))
        env_files = definition.get("env_file", [])
        for entry in env_files if isinstance(env_files, list) else [env_files]:
            owned_file(
                entry.get("path") if isinstance(entry, dict) else entry, readonly=True
            )
        for volume in definition.get("volumes", []):
            if isinstance(volume, dict):
                if volume.get("type") == "bind":
                    owned_file(
                        volume.get("source"), readonly=bool(volume.get("read_only"))
                    )
            elif isinstance(volume, str):
                parts = volume.split(":")
                if len(parts) > 1 and (
                    parts[0].startswith(("/", ".")) or "/" in parts[0]
                ):
                    owned_file(
                        parts[0],
                        readonly=len(parts) > 2 and "ro" in parts[2].split(","),
                    )
        if (
            definition.get("privileged")
            or definition.get("network_mode") == "host"
            or definition.get("pid") == "host"
            or definition.get("ipc") == "host"
            or definition.get("devices")
            or definition.get("cap_add")
        ):
            raise HTTPException(
                422,
                "privileged Compose configuration requires a separate maintenance procedure",
            )
        if any("docker.sock" in str(v) for v in definition.get("volumes", [])):
            raise HTTPException(
                422, "Docker socket mounts require a separate maintenance procedure"
            )
    return runtime, p, project, config


def runtime_status(db, service):
    now = datetime.now(timezone.utc).isoformat()
    result = []
    for runtime in service.runtimes:
        row = {
            "runtime_id": runtime.id,
            "runtime_type": runtime.runtime_type,
            "desired_state": runtime.desired_state,
            "autostart_policy": runtime.autostart_policy,
            "observed_at": now,
            "source": "docker",
            "containers": [],
            "metrics": [],
        }
        if runtime.runtime_type != "docker-compose":
            row.update(
                observed_state="unknown",
                error="No runtime adapter registered for this type",
            )
        else:
            try:
                _, p, project, config = runtime_config(db, service, runtime.id)
                containers = backend.containers(project)
                expected = set(config["services"])
                found = {c["compose_service"] for c in containers}
                if not containers:
                    state = "stopped"
                elif any(c["health"] == "unhealthy" for c in containers):
                    state = "unhealthy"
                elif (
                    all(c["state"] == "running" for c in containers)
                    and expected <= found
                ):
                    state = "running"
                elif all(c["state"] in {"exited", "created"} for c in containers):
                    state = "stopped"
                else:
                    state = "partial"
                metrics = backend.metrics(
                    [c["id"] for c in containers if c["state"] == "running"]
                )
                row.update(
                    observed_state=state,
                    containers=containers,
                    metrics=metrics,
                    project=project,
                    compose_services=sorted(expected),
                    drift=runtime.desired_state in {"running", "stopped"}
                    and runtime.desired_state != state,
                )
            except DockerUnavailable as e:
                row.update(observed_state="unavailable", error=str(e))
            except HTTPException as e:
                row.update(observed_state="unknown", error=e.detail)
        result.append(row)
    return result


def reconcile(db):
    registered = {s.slug: s for s in db.query(models.Service)}
    aliases = {a.alias: a.service_id for a in db.query(models.ServiceAlias)}
    root = Path(get_settings().selfhost_root) / "stacks" / "services"
    findings = []
    for p in sorted(root.iterdir() if root.exists() else []):
        if p.is_dir() and any((p / n).exists() for n in COMPOSE_NAMES):
            s = registered.get(p.name)
            if not s and p.name not in aliases:
                findings.append(
                    {
                        "code": "stack.unregistered",
                        "slug": p.name,
                        "suggestion": "review service registration or an explicit alias",
                    }
                )
            elif s and not s.runtimes:
                findings.append(
                    {
                        "code": "runtime.missing",
                        "slug": p.name,
                        "suggestion": "register existing Compose runtime",
                    }
                )
    try:
        projects = sorted({x["project"] for x in backend.containers() if x["project"]})
        owners = {
            r.compose_project or registered_slug
            for registered_slug, s in registered.items()
            for r in s.runtimes
        }
        for p in projects:
            if p not in owners:
                findings.append(
                    {
                        "code": "project.unregistered",
                        "project": p,
                        "suggestion": "review runtime ownership",
                    }
                )
        available = True
    except DockerUnavailable:
        projects = []
        available = False
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "docker_available": available,
        "projects": projects,
        "findings": findings,
        "applied": False,
    }
