import re
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from . import models
from .caddy_protection import configured_api_keys, configured_logins
from .config import get_settings
from .domains import is_domain_template, render_domain_value

SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,253}[a-z0-9]$")
CADDY_SITE_RE = re.compile(r"^\s*([A-Za-z0-9_.*{}$., -]+)\s*\{")
CADDY_DIRECTIVE_PREFIXES = {
    "@",
    "basicauth",
    "basic_auth",
    "encode",
    "handle",
    "header",
    "import",
    "log",
    "redir",
    "respond",
    "reverse_proxy",
    "rewrite",
    "root",
    "tls",
}


def _result(severity: str, code: str, message: str, entity_kind: str = "", entity_id: str = "") -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
    }


def _render_caddy_host(raw_host: str) -> str:
    legacy_token = "{$" + "SELFHOST" + "_CONTROL_PUBLIC_BASE_DOMAIN}"
    return raw_host.strip().replace(legacy_token, render_domain_value("{base_domain}"))


def _caddy_hosts_from_file(path: Path) -> set[str]:
    hosts: set[str] = set()
    if not path.exists():
        return hosts
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("("):
            continue
        match = CADDY_SITE_RE.match(line)
        if not match:
            continue
        first_token = match.group(1).split()[0].strip(",")
        if first_token.startswith(":") or first_token in CADDY_DIRECTIVE_PREFIXES:
            continue
        for host in match.group(1).split(","):
            rendered = _render_caddy_host(host).strip()
            if rendered.startswith("*."):
                continue
            if rendered and "." in rendered and "{" not in rendered and "$" not in rendered:
                hosts.add(rendered)
    return hosts


def configured_caddy_hosts() -> set[str]:
    settings = get_settings()
    files: list[Path] = []
    files.extend(path for path in Path(settings.generated_caddy_dir).glob("*.caddy") if path.name != "auto_cert_zones.caddy")
    override_dir = Path(settings.selfhost_root) / "infra" / "caddy" / "overrides"
    files.extend(path for path in override_dir.glob("*.caddy") if ".bak" not in path.name and not path.name.startswith("."))
    hosts: set[str] = set()
    for path in files:
        hosts.update(_caddy_hosts_from_file(path))
    return hosts


def validate_all(db: Session, scope: str = "all") -> list[dict]:
    results: list[dict] = []
    settings = get_settings()
    services = db.query(models.Service).all()
    service_slugs = {service.slug for service in services}
    service_ids = {service.id for service in services}
    subservice_ids = {sub.id for sub in db.query(models.SubService).all()}

    if settings.caddy_protection_enabled:
        try:
            login_count = len(configured_logins())
            api_key_count = len(configured_api_keys())
        except ValueError as exc:
            results.append(_result("fatal", "caddy_schutz.config.invalid", str(exc), "config", ""))
            login_count = api_key_count = 0
        if login_count == 0 and api_key_count == 0:
            results.append(_result("warning", "caddy_schutz.credentials.missing", "Caddy-Schutz is enabled but no logins or API keys are configured", "config", ""))
        if settings.caddy_protection_cookie_enabled and not (settings.caddy_protection_cookie_secret or settings.api_token):
            results.append(_result("warning", "caddy_schutz.cookie_secret.missing", "Cookie auth uses the development fallback secret; configure CP_CADDY_PROTECTION_COOKIE_SECRET in production", "config", ""))

    for service in services:
        if not SERVICE_RE.match(service.slug):
            results.append(_result("fatal", "service.slug.invalid", f"Invalid service slug: {service.slug}", "service", service.id))
        if service.lifecycle not in {"experimental", "development", "production", "deprecated"}:
            results.append(_result("error", "service.lifecycle.invalid", f"Invalid lifecycle for {service.slug}", "service", service.id))
        if service.system not in {"services", "special-purpose"}:
            results.append(_result("error", "service.system.invalid", f"Invalid system for {service.slug}", "service", service.id))
        if service.criticality < 1 or service.criticality > 5:
            results.append(_result("error", "service.criticality.invalid", f"Invalid criticality for {service.slug}", "service", service.id))
        if service.status == "active" and not service.docs:
            results.append(_result("warning", "docs.missing", f"No docs registered for active service {service.slug}", "service", service.id))

    for sub in db.query(models.SubService).all():
        if not SERVICE_RE.match(sub.slug):
            results.append(_result("fatal", "subservice.slug.invalid", f"Invalid subservice slug: {sub.slug}", "subservice", sub.id))
        if sub.parent_type not in {"service", "subservice"}:
            results.append(_result("fatal", "subservice.parent_type.invalid", f"Invalid parent_type for subservice {sub.slug}: {sub.parent_type}", "subservice", sub.id))
        if sub.parent_type == "service":
            parent = db.query(models.Service).filter(models.Service.id == sub.parent_id).one_or_none()
            if not parent:
                results.append(_result("fatal", "subservice.parent_id.missing", f"Parent service not found for subservice {sub.slug}", "subservice", sub.id))
        elif sub.parent_type == "subservice":
            parent = db.query(models.SubService).filter(models.SubService.id == sub.parent_id).one_or_none()
            if not parent:
                results.append(_result("fatal", "subservice.parent_id.missing", f"Parent subservice not found for subservice {sub.slug}", "subservice", sub.id))

    route_keys: set[tuple[str, str]] = set()
    registered_hosts: set[str] = set()
    for route in db.query(models.Route).all():
        rendered_host = render_domain_value(route.host)
        registered_hosts.add(rendered_host)
        key = (rendered_host, route.path)
        if key in route_keys:
            results.append(_result("fatal", "route.duplicate", f"Duplicate route {rendered_host}{route.path}", "route", route.id))
        route_keys.add(key)
        if not HOST_RE.match(rendered_host):
            results.append(_result("error", "route.host.invalid", f"Invalid route host: {route.host} -> {rendered_host}", "route", route.id))
        if "." in route.host and not is_domain_template(route.host) and route.host.endswith("marcosudau.com"):
            results.append(_result("warning", "route.host.fixed-target-domain", f"Route uses target domain directly during development: {route.host}", "route", route.id))
        if not route.path.startswith("/"):
            results.append(_result("error", "route.path.invalid", f"Route path must start with / for {route.host}", "route", route.id))
        if route.auth_policy not in {"public", "caddy_schutz"}:
            results.append(_result("error", "route.auth_policy.invalid", f"Invalid auth_policy for {route.host}: {route.auth_policy}", "route", route.id))
        if route.parent_type not in {None, "service", "subservice"}:
            results.append(_result("fatal", "route.parent_type.invalid", f"Invalid parent_type for route {route.host}: {route.parent_type}", "route", route.id))
        if route.parent_type == "service" and route.parent_id not in service_ids:
            results.append(_result("fatal", "route.parent_id.missing", f"Parent service not found for route {route.host}", "route", route.id))
        if route.parent_type == "subservice" and route.parent_id not in subservice_ids:
            results.append(_result("fatal", "route.parent_id.missing", f"Parent subservice not found for route {route.host}", "route", route.id))
        parsed = urlparse(route.upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            results.append(_result("error", "route.upstream.invalid", f"Invalid upstream for {route.host}: {route.upstream}", "route", route.id))

    for caddy_host in sorted(configured_caddy_hosts() - registered_hosts):
        results.append(_result("fatal", "route.registry.missing", f"Caddy host is not registered in Control Plane routes: {caddy_host}", "route", ""))

    port_keys: set[tuple[int, str]] = set()
    for port in db.query(models.Port).all():
        key = (port.number, port.protocol)
        if key in port_keys:
            results.append(_result("fatal", "port.duplicate", f"Duplicate port {port.number}/{port.protocol}", "port", port.id))
        port_keys.add(key)
        if port.number < 1 or port.number > 65535:
            results.append(_result("fatal", "port.invalid", f"Invalid port {port.number}", "port", port.id))
        if port.service:
            block = port.service.port_base
            if block is not None:
                block_size = 1000 if port.service.large_port_space else 100
                if not (block <= port.number < block + block_size):
                    results.append(_result("warning", "port.outside_block", f"Port {port.number} outside {port.service.slug} block ({block}-{block+block_size-1})", "port", port.id))

    root = Path(get_settings().selfhost_root)
    for runtime in db.query(models.Runtime).all():
        if runtime.runtime_type not in {"docker-compose", "user-systemd", "system-systemd", "external", "manual"}:
            results.append(_result("error", "runtime.type.invalid", f"Invalid runtime type {runtime.runtime_type}", "runtime", runtime.id))
        if runtime.path and not Path(runtime.path).is_absolute():
            results.append(_result("error", "runtime.path.relative", f"Runtime path must be absolute: {runtime.path}", "runtime", runtime.id))

    for skill in db.query(models.Skill).all():
        if skill.skill_type == "component" and skill.service_id is None:
            results.append(_result("error", "skill.component.unbound", f"Component skill without service: {skill.slug}", "skill", skill.id))
        skill_path = Path(skill.path)
        if not skill_path.is_absolute():
            results.append(_result("error", "skill.path.relative", f"Skill path must be absolute: {skill.path}", "skill", skill.id))
        elif root in skill_path.parents or skill_path == root:
            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                results.append(_result("warning", "skill.file.missing", f"Skill has no SKILL.md yet: {skill.path}", "skill", skill.id))

    for secret in db.query(models.SecretRef).all():
        if secret.ref.strip() == "" or secret.ref == secret.target_env:
            results.append(_result("error", "secret.ref.invalid", f"Secret ref looks invalid for {secret.name}", "secret_ref", secret.id))
        if any(marker in secret.ref.lower() for marker in ["password=", "token=", "sk-"]):
            results.append(_result("fatal", "secret.ref.contains-secret", f"Secret ref may contain a secret value: {secret.name}", "secret_ref", secret.id))

    for doc in db.query(models.DocRef).all():
        if doc.service.slug not in service_slugs:
            results.append(_result("error", "doc.service.invalid", f"Doc linked to unknown service {doc.service_id}", "doc", doc.id))
        if not doc.path.startswith("/"):
            results.append(_result("warning", "doc.path.relative", f"Doc path is relative: {doc.path}", "doc", doc.id))

    return results


def persist_validation_run(db: Session, scope: str = "all", commit: bool = True) -> models.ValidationRun:
    results = validate_all(db, scope)
    status = "failed" if any(item["severity"] == "fatal" for item in results) else "passed"
    run = models.ValidationRun(scope=scope, status=status)
    db.add(run)
    db.flush()
    for item in results:
        db.add(models.ValidationResult(run_id=run.id, **item))
    db.flush()
    if commit:
        db.commit()
        db.refresh(run)
    return run
