"""Stage the full existing Caddy configuration and publish only after validation."""

import hashlib
from pathlib import Path
import subprocess
from fastapi import HTTPException
from .config import get_settings
from .contracts import digest, object_data
from . import models
from .generators import generate_caddy, _write
from .operations import operation_lock, operation_dir
from .routing import override_files
from .service import log_activity
from .validators import persist_validation_run


def configuration_hash(db):
    settings = get_settings()
    paths = [
        Path(settings.caddyfile_path),
        *override_files(),
    ]
    if settings.caddy_auto_cert_enabled:
        paths.append(Path(settings.caddy_auto_cert_state_file))
    paths.extend(
        p
        for p in Path(settings.generated_caddy_dir).glob("*.caddy")
        if p.name != "routes.caddy"
    )
    files = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        for p in paths
    }
    return digest(
        {
            "routes": [
                object_data(r) for r in db.query(models.Route).order_by(models.Route.id)
            ],
            "options": [
                object_data(r)
                for r in db.query(models.RouteOptions).order_by(
                    models.RouteOptions.route_id
                )
            ],
            "files": files,
            "service_protection": [
                (r.id, r.caddy_protection_enabled)
                for r in db.query(models.Service).order_by(models.Service.id)
            ],
            "subservice_protection": [
                (r.id, r.caddy_protection_enabled, r.parent_type, r.parent_id)
                for r in db.query(models.SubService).order_by(models.SubService.id)
            ],
            "settings": {
                key: getattr(settings, key)
                for key in [
                    "public_base_domain",
                    "caddy_protection_enabled",
                    "caddy_reload_enabled",
                ]
            },
        }
    )


def staged_config(candidate):
    settings = get_settings()
    source = Path(settings.caddyfile_path)
    if not source.is_file():
        raise HTTPException(409, "full Caddyfile is required for candidate validation")
    expected = {
        str(Path(settings.generated_caddy_dir) / "*.caddy"),
        "/etc/caddy/generated/*.caddy",
    }
    lines = []
    found = False
    for line in source.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[0] == "import":
            value = parts[1].strip('"')
            resolved = (
                str(source.parent / value) if not Path(value).is_absolute() else value
            )
            if value in expected or resolved in expected:
                others = sorted(
                    p
                    for p in Path(settings.generated_caddy_dir).glob("*.caddy")
                    if p.name != "routes.caddy"
                )
                lines.extend(f'import "{p}"' for p in [*others, Path(candidate)])
                found = True
                continue
            if not Path(value).is_absolute() and (
                "/" in value or ".caddy" in value or "*" in value
            ):
                line = f'import "{source.parent / value}"'
        lines.append(line)
    if not found:
        raise HTTPException(
            409, "Caddyfile must import the configured generated directory"
        )
    target = operation_dir() / "candidate.Caddyfile"
    target.write_text("\n".join(lines) + "\n")
    return target


def plan_caddy(db, certificates):
    with operation_lock("caddy-config"):
        run = persist_validation_run(db, "caddy-apply")
        artifact = generate_caddy(db, staging=True)
        return {
            "validation_status": run.status,
            "artifact": artifact,
            "cert_zone_plans": certificates(),
            "apply_allowed": run.status == "passed",
            "plan_hash": configuration_hash(db),
        }


def apply_caddy(db, validate, certificates, expected_hash=None):
    settings = get_settings()
    with operation_lock("caddy-config"):
        current_hash = configuration_hash(db)
        if expected_hash and expected_hash != current_hash:
            raise HTTPException(412, "Caddy plan changed")
        run = persist_validation_run(db, "caddy-apply", commit=False)
        if run.status != "passed":
            raise HTTPException(409, "fatal validation errors block Caddy apply")
        protected_paths = [Path(settings.generated_caddy_dir) / "routes.caddy"]
        if settings.caddy_auto_cert_enabled:
            protected_paths += [
                Path(settings.caddy_auto_cert_state_file),
                Path(settings.caddy_auto_cert_generated_file),
            ]
        before = {p: p.read_bytes() if p.exists() else None for p in protected_paths}
        try:
            candidate = generate_caddy(db, staging=True, commit=False)
            stage = staged_config(candidate["path"])
            if validate(stage).returncode:
                raise HTTPException(409, "full Caddy candidate validation failed")
            cert_zones = certificates()
            # Certificates may alter an imported file; validate the complete candidate again.
            stage = staged_config(candidate["path"])
            if validate(stage).returncode:
                raise HTTPException(
                    409, "Caddy candidate with certificate zones failed validation"
                )
            live = Path(settings.generated_caddy_dir) / "routes.caddy"
            _write(live, Path(candidate["path"]).read_text())
            reloaded = False
            if settings.caddy_reload_enabled:
                reload = subprocess.run(
                    ["sudo", "-n", settings.caddy_apply_command],
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                if reload.returncode:
                    raise HTTPException(
                        409, "Caddy reload failed; previous configuration restored"
                    )
                reloaded = True
            artifact = {**candidate, "path": str(live)}
            db.add(
                models.GeneratedArtifact(
                    artifact_type="caddy",
                    path=str(live),
                    checksum=candidate["checksum"],
                    status="applied",
                )
            )
            log_activity(
                db,
                "caddy.apply",
                "configuration",
                "",
                {"plan_hash": current_hash, "reloaded": reloaded},
            )
            db.commit()
            return {
                "artifact": artifact,
                "cert_zones": cert_zones,
                "caddy_validate": "passed",
                "reloaded": reloaded,
                "plan_hash": current_hash,
            }
        except Exception:
            db.rollback()
            for p, data in before.items():
                if data is None:
                    p.unlink(missing_ok=True)
                elif not p.exists() or p.read_bytes() != data:
                    _write(p, data.decode())
            log_activity(
                db,
                "caddy.apply.failed",
                "configuration",
                "",
                {"plan_hash": current_hash},
            )
            db.commit()
            raise


def provision_safely(func):
    """Compensate file effects if the existing combined provisioning request fails."""
    from functools import wraps
    from .contracts import safe_path

    @wraps(func)
    def wrapped(*args, **kwargs):
        payload = kwargs.get("payload") or args[0]
        db = kwargs.get("db") or args[1]
        settings = get_settings()
        doc = safe_path(
            payload.doc_path
            or f"{settings.selfhost_root}/docs/services/{payload.slug}/overview.{payload.slug}.md",
            Path(settings.selfhost_root) / "docs/services" / payload.slug,
        )
        paths = [doc, Path(settings.generated_caddy_dir) / "routes.caddy"]
        if settings.caddy_auto_cert_enabled:
            paths += [
                Path(settings.caddy_auto_cert_state_file),
                Path(settings.caddy_auto_cert_generated_file),
            ]
        with operation_lock("caddy-config"):
            before = {p: p.read_bytes() if p.exists() else None for p in paths}
            try:
                return func(*args, **kwargs)
            except Exception:
                db.rollback()
                for p, data in before.items():
                    if data is None:
                        p.unlink(missing_ok=True)
                    elif not p.exists() or p.read_bytes() != data:
                        _write(p, data.decode())
                log_activity(
                    db,
                    "managed_service.provision.failed",
                    "service",
                    "",
                    {"slug": payload.slug},
                    actor="legacy-admin",
                )
                db.commit()
                raise

    return wrapped
