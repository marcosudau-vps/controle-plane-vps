import os
import subprocess
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx
from sqlalchemy.orm import Session

from . import models
from .caddy_protection import (
    authenticate_request,
    configured_api_keys,
    configured_logins,
    cookie_domain,
    create_session_cookie,
    resolve_route_protection,
    verify_login,
)
from .config import get_settings
from .db import get_session, init_db
from .domains import BASE_DOMAIN_TOKEN, build_subservice_host_prefix, build_subservice_route_host, host_template_for_subdomain, render_domain_value
from .generators import export_json, generate_caddy
from .port_allocator import allocate_port_base
from .schemas import (
    ApiEntityCreate,
    ApiResponse,
    CaddyCertZoneRequest,
    CaddyProtectionUpdate,
    CommentCreate,
    DocCreate,
    HealthcheckCreate,
    LifecycleArchiveInspectRequest,
    LifecycleExecuteRequest,
    ManagedServiceProvisionCreate,
    PortCreate,
    PortUpdate,
    ResourceCreate,
    RouteCreate,
    RouteUpdate,
    RuntimeCreate,
    SecretRefCreate,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    SkillCreate,
    SubServiceCreate,
    SubServiceUpdate,
    ValidationRunOut,
)
from .security import require_token
from .service import commit_or_409, flush_or_409, get_service_by_slug, log_activity
from .lifecycle.manifests import ManifestError, load_all_manifests, load_manifest, manifest_summary
from .lifecycle.planner import build_service_plan
from .lifecycle.runner import execute_archive, execute_restore, execute_snapshot, inspect_archive, plan_restore
from .subservice import (
    build_service_tree,
    build_subservice_tree,
    delete_subservice_cascade,
    get_subservice_by_slug,
    get_subservice_children,
    get_subservice_routes,
)
from .validators import persist_validation_run


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Control Plane API", version="0.1.0", lifespan=lifespan)


def ok(data: Any = None) -> ApiResponse:
    return ApiResponse(ok=True, data=data)


def as_dict(obj: Any) -> dict:
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def rendered_route_exists(db: Session, host: str, path: str = "/") -> bool:
    rendered_host = render_domain_value(host)
    for existing in db.query(models.Route).filter(models.Route.path == path).all():
        if render_domain_value(existing.host) == rendered_host:
            return True
    return False


def add_service_namespace_route(db: Session, service: models.Service) -> models.Route:
    host = f"{service.slug}.{BASE_DOMAIN_TOKEN}"
    if rendered_route_exists(db, host):
        raise HTTPException(status_code=409, detail=f"namespace route already exists: {render_domain_value(host)}/")
    route = models.Route(
        service_id=service.id,
        parent_type="service",
        parent_id=service.id,
        host=host,
        path="/",
        upstream=get_settings().namespace_placeholder_upstream,
        tls=True,
        auth_policy="caddy_schutz",
        status="active",
        caddy_protection_enabled=None,
    )
    db.add(route)
    return route


def _html_escape(value: str) -> str:
    import html

    return html.escape(value, quote=True)


@app.get("/caddy-schutz/login", response_class=HTMLResponse)
def caddy_schutz_login_form(next: str = "/") -> HTMLResponse:
    next_value = _html_escape(next if next.startswith("/") else "/")
    return HTMLResponse(
        f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Caddy-Schutz</title></head>
<body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:2rem;max-width:28rem">
  <h1>Caddy-Schutz</h1>
  <form method="post" action="/caddy-schutz/login">
    <input type="hidden" name="next" value="{next_value}">
    <label>Benutzer<br><input name="username" autocomplete="username" required></label><br><br>
    <label>Passwort<br><input name="password" type="password" autocomplete="current-password" required></label><br><br>
    <label><input name="remember" type="checkbox" value="1" checked> 24h angemeldet bleiben</label><br><br>
    <button type="submit">Anmelden</button>
  </form>
</body>
</html>"""
    )


@app.post("/caddy-schutz/login")
def caddy_schutz_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    remember: str | None = Form(None),
) -> Response:
    if not verify_login(username, password):
        raise HTTPException(status_code=401, detail="invalid login")
    target = next if next.startswith("/") else "/"
    response = RedirectResponse(target, status_code=303)
    settings = get_settings()
    if remember and settings.caddy_protection_cookie_enabled:
        domain = cookie_domain()
        request_host = request.url.hostname or ""
        if domain and not request_host.endswith(domain.lstrip(".")):
            domain = None
        response.set_cookie(
            settings.caddy_protection_cookie_name,
            create_session_cookie(username),
            max_age=settings.caddy_protection_cookie_max_age_seconds,
            httponly=True,
            secure=True,
            samesite="lax",
            domain=domain,
        )
    return response


@app.get("/caddy-schutz/check")
def caddy_schutz_check(request: Request) -> Response:
    if not get_settings().caddy_protection_enabled:
        return Response(status_code=204)
    result = authenticate_request(request)
    if result.authenticated:
        response = Response(status_code=204)
        response.headers["X-Caddy-Schutz-Auth"] = result.method or "unknown"
        return response
    accept = request.headers.get("accept", "")
    user_agent = request.headers.get("user-agent", "")
    if "text/html" in accept.lower() or "mozilla" in user_agent.lower():
        next_url = request.headers.get("x-forwarded-uri") or request.headers.get("x-original-uri") or "/"
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        return RedirectResponse(f"/caddy-schutz/login?next={quote(next_url, safe='/?=&%')}", status_code=303)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Bearer realm="caddy-schutz"'})


def load_simple_env_file(path: str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def caddy_command_env() -> dict[str, str]:
    settings = get_settings()
    env = {key: str(value) for key, value in os.environ.items()}
    env.update(load_simple_env_file(f"{settings.selfhost_root}/secrets/control-plane.env"))
    env.update(load_simple_env_file(settings.caddy_auto_cert_env_file))
    if env.get("ENV_LOG_FILE") and not env.get("LOG_FILE"):
        env["LOG_FILE"] = env["ENV_LOG_FILE"]
    return env


def run_caddy_validate() -> subprocess.CompletedProcess[str]:
    settings = get_settings()
    return subprocess.run(["caddy", "validate", "--config", settings.caddyfile_path], text=True, capture_output=True, check=False, env=caddy_command_env())


def run_caddy_cert_zones(
    domain: str,
    *,
    apply: bool,
    no_reload: bool,
    max_new_zones_per_run: int | None = None,
    max_total_zones_per_root: int | None = None,
    exclude_root_zone: bool | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.caddy_auto_cert_enabled:
        return {"enabled": False, "domain": domain, "skipped": True}

    cmd = [
        sys.executable,
        "-m",
        settings.caddy_auto_cert_command,
        "--domain",
        domain,
        "--state-file",
        settings.caddy_auto_cert_state_file,
        "--generated-caddyfile",
        settings.caddy_auto_cert_generated_file,
        "--env-file",
        settings.caddy_auto_cert_env_file,
        "--max-new-zones-per-run",
        str(max_new_zones_per_run if max_new_zones_per_run is not None else settings.caddy_auto_cert_max_new_zones_per_run),
        "--max-total-zones-per-root",
        str(max_total_zones_per_root if max_total_zones_per_root is not None else settings.caddy_auto_cert_max_total_zones_per_root),
        "--caddy-mode",
        "local",
        "--caddy-config",
        settings.caddyfile_path,
    ]
    if settings.caddy_apply_command:
        cmd.extend(["--caddy-apply-command", settings.caddy_apply_command])
    should_exclude_root_zone = exclude_root_zone if exclude_root_zone is not None else settings.caddy_auto_cert_exclude_root_zone
    if should_exclude_root_zone:
        cmd.append("--exclude-root-zone")
    if apply:
        cmd.append("--apply")
    if no_reload:
        cmd.append("--no-reload")

    result = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=180)
    payload = {
        "enabled": True,
        "domain": domain,
        "apply": apply,
        "no_reload": no_reload,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        raise HTTPException(status_code=409, detail={"message": "caddy auto cert zones failed", **payload})
    return payload


def run_caddy_cert_zones_for_routes(db: Session, *, apply: bool, no_reload: bool) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    routes = db.query(models.Route).filter(models.Route.status == "active", models.Route.tls.is_(True)).order_by(models.Route.host).all()
    for route in routes:
        host = render_domain_value(route.host)
        if host in seen:
            continue
        seen.add(host)
        results.append(run_caddy_cert_zones(host, apply=apply, no_reload=no_reload))
    return results


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse("/subdomains", status_code=302)


@app.get("/health")
def health(db: Session = Depends(get_session)) -> dict:
    db.execute(models.Service.__table__.select().limit(1))
    return {"ok": True, "service": "control-plane"}


@app.post("/api/v1/db/init", dependencies=[Depends(require_token)])
def db_init() -> ApiResponse:
    init_db()
    return ok({"initialized": True})


@app.get("/api/v1/lifecycle/services", dependencies=[Depends(require_token)])
def lifecycle_services(db: Session = Depends(get_session)) -> ApiResponse:
    items = []
    for manifest in load_all_manifests():
        slug = manifest["service"]["slug"]
        service = db.query(models.Service).filter(models.Service.slug == slug).one_or_none()
        items.append({**manifest_summary(slug, manifest), "registered": service is not None, "db_status": service.status if service else None})
    return ok(items)


@app.get("/api/v1/lifecycle/services/{slug}", dependencies=[Depends(require_token)])
def lifecycle_service(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    try:
        manifest = load_manifest(slug)
    except ManifestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service = get_service_by_slug(db, slug)
    return ok(
        {
            "manifest": manifest,
            "summary": manifest_summary(slug, manifest),
            "service": as_dict(service),
            "routes": [as_dict(route) for route in service.routes],
            "ports": [as_dict(port) for port in service.ports],
            "runtimes": [as_dict(runtime) for runtime in service.runtimes],
            "docs": [as_dict(doc) for doc in service.docs],
            "healthchecks": [as_dict(check) for check in service.healthchecks],
        }
    )


@app.post("/api/v1/lifecycle/services/{slug}/plan-snapshot", dependencies=[Depends(require_token)])
def lifecycle_plan_snapshot(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    return ok(build_service_plan(db, slug, "snapshot"))


@app.post("/api/v1/lifecycle/services/{slug}/execute-snapshot", dependencies=[Depends(require_token)])
def lifecycle_execute_snapshot(slug: str, payload: LifecycleExecuteRequest, db: Session = Depends(get_session)) -> ApiResponse:
    return ok(execute_snapshot(db, slug, payload.plan_hash))


@app.post("/api/v1/lifecycle/services/{slug}/plan-archive", dependencies=[Depends(require_token)])
def lifecycle_plan_archive(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    return ok(build_service_plan(db, slug, "archive"))


@app.post("/api/v1/lifecycle/services/{slug}/execute-archive", dependencies=[Depends(require_token)])
def lifecycle_execute_archive(slug: str, payload: LifecycleExecuteRequest, db: Session = Depends(get_session)) -> ApiResponse:
    return ok(execute_archive(db, slug, payload.plan_hash))


@app.post("/api/v1/lifecycle/archives/inspect", dependencies=[Depends(require_token)])
def lifecycle_archive_inspect(payload: LifecycleArchiveInspectRequest) -> ApiResponse:
    return ok(inspect_archive(payload.archive_id, archive_dir=payload.archive_dir, archive_path=payload.archive_path))


@app.post("/api/v1/lifecycle/archives/{archive_id:path}/plan-restore", dependencies=[Depends(require_token)])
def lifecycle_plan_restore(archive_id: str) -> ApiResponse:
    return ok(plan_restore(archive_id))


@app.post("/api/v1/lifecycle/archives/{archive_id:path}/execute-restore", dependencies=[Depends(require_token)])
def lifecycle_execute_restore(archive_id: str, payload: LifecycleExecuteRequest, db: Session = Depends(get_session)) -> ApiResponse:
    return ok(execute_restore(db, archive_id, payload.plan_hash))


@app.get("/api/v1/services", dependencies=[Depends(require_token)])
def list_services(db: Session = Depends(get_session)) -> ApiResponse:
    services = db.query(models.Service).order_by(models.Service.slug).all()
    return ok([as_dict(service) for service in services])


@app.post("/api/v1/services", dependencies=[Depends(require_token)])
def create_service(payload: ServiceCreate, db: Session = Depends(get_session)) -> ApiResponse:
    service = models.Service(**payload.model_dump())
    db.add(service)
    if service.port_base is None:
        service.port_base = allocate_port_base(db, large_port_space=service.large_port_space)
    flush_or_409(db)
    namespace_route = add_service_namespace_route(db, service)
    flush_or_409(db)
    log_activity(db, "service.create", "service", service.id, {"slug": service.slug, "namespace_route": namespace_route.host})
    commit_or_409(db)
    db.refresh(service)
    return ok(ServiceOut.model_validate(service).model_dump(mode="json"))


@app.get("/api/v1/services/{slug}", dependencies=[Depends(require_token)])
def show_service(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    data = as_dict(service)
    data["routes"] = [{**as_dict(route), "rendered_host": render_domain_value(route.host)} for route in service.routes]
    data["ports"] = [as_dict(port) for port in service.ports]
    data["runtimes"] = [as_dict(runtime) for runtime in service.runtimes]
    data["docs"] = [as_dict(doc) for doc in service.docs]
    data["skills"] = [as_dict(skill) for skill in service.skills]
    data["healthchecks"] = [as_dict(check) for check in service.healthchecks]
    data["sub_services"] = [
        as_dict(sub) for sub in db.query(models.SubService).filter(
            models.SubService.parent_type == "service",
            models.SubService.parent_id == service.id,
        ).all()
    ]
    return ok(data)


@app.get("/api/v1/services/{slug}/tree", dependencies=[Depends(require_token)])
def service_tree(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    return ok(build_service_tree(db, service))


@app.patch("/api/v1/services/{slug}", dependencies=[Depends(require_token)])
def update_service(slug: str, payload: ServiceUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, key, value)
    log_activity(db, "service.update", "service", service.id, {"slug": service.slug})
    commit_or_409(db)
    db.refresh(service)
    return ok(as_dict(service))


@app.post("/api/v1/services/{slug}/archive", dependencies=[Depends(require_token)])
def archive_service(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    get_service_by_slug(db, slug)
    raise HTTPException(
        status_code=410,
        detail={
            "message": "legacy status-only archive endpoint is disabled; use /api/v1/lifecycle/services/{slug}/plan-archive and execute-archive",
            "slug": slug,
        },
    )


@app.delete("/api/v1/services/{slug}", dependencies=[Depends(require_token)])
def delete_service(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    direct_subs = (
        db.query(models.SubService)
        .filter(models.SubService.parent_type == "service", models.SubService.parent_id == service.id)
        .all()
    )
    for sub in direct_subs:
        delete_subservice_cascade(db, sub)
    log_activity(db, "service.delete", "service", service.id, {"slug": service.slug})
    db.delete(service)
    commit_or_409(db)
    return ok({"slug": slug, "deleted": True})


@app.get("/api/v1/subservices", dependencies=[Depends(require_token)])
def list_subservices(
    parent_type: str | None = None,
    parent_id: str | None = None,
    db: Session = Depends(get_session),
) -> ApiResponse:
    query = db.query(models.SubService)
    if parent_type:
        query = query.filter(models.SubService.parent_type == parent_type)
    if parent_id:
        query = query.filter(models.SubService.parent_id == parent_id)
    items = query.order_by(models.SubService.slug).all()
    return ok([as_dict(sub) for sub in items])


@app.post("/api/v1/subservices", dependencies=[Depends(require_token)])
def create_subservice(payload: SubServiceCreate, db: Session = Depends(get_session)) -> ApiResponse:
    data = payload.model_dump()
    _ = data.pop("parent_id", None)
    if payload.parent_type == "service":
        parent = get_service_by_slug(db, payload.parent_id)
    elif payload.parent_type == "subservice":
        parent = get_subservice_by_slug(db, payload.parent_id)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid parent_type: {payload.parent_type}")
    sub = models.SubService(**data, parent_id=parent.id)
    db.add(sub)
    flush_or_409(db)
    log_activity(db, "subservice.create", "subservice", sub.id, {"slug": sub.slug, "parent_type": sub.parent_type, "parent_id": sub.parent_id})
    commit_or_409(db)
    db.refresh(sub)
    return ok(as_dict(sub))


@app.get("/api/v1/subservices/{slug}", dependencies=[Depends(require_token)])
def show_subservice(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    sub = get_subservice_by_slug(db, slug)
    data = as_dict(sub)
    data["routes"] = [
        {**as_dict(route), "rendered_host": render_domain_value(route.host)}
        for route in get_subservice_routes(db, sub.id)
    ]
    data["sub_services"] = [as_dict(child) for child in get_subservice_children(db, sub.id)]
    return ok(data)


@app.patch("/api/v1/subservices/{slug}", dependencies=[Depends(require_token)])
def update_subservice(slug: str, payload: SubServiceUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    sub = get_subservice_by_slug(db, slug)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(sub, key, value)
    log_activity(db, "subservice.update", "subservice", sub.id, {"slug": sub.slug})
    commit_or_409(db)
    db.refresh(sub)
    return ok(as_dict(sub))


@app.delete("/api/v1/subservices/{slug}", dependencies=[Depends(require_token)])
def delete_subservice(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    sub = get_subservice_by_slug(db, slug)
    delete_subservice_cascade(db, sub)
    log_activity(db, "subservice.delete", "subservice", sub.id, {"slug": sub.slug})
    commit_or_409(db)
    return ok({"slug": slug, "deleted": True})


@app.get("/api/v1/subservices/{slug}/tree", dependencies=[Depends(require_token)])
def subservice_tree(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    sub = get_subservice_by_slug(db, slug)
    return ok(build_subservice_tree(db, sub.id))


@app.post("/api/v1/managed-services/provision", dependencies=[Depends(require_token)])
def provision_managed_service(payload: ManagedServiceProvisionCreate, db: Session = Depends(get_session)) -> ApiResponse:
    settings = get_settings()
    if db.query(models.Service).filter(models.Service.slug == payload.slug).one_or_none():
        raise HTTPException(status_code=409, detail=f"service already exists: {payload.slug}")

    service = models.Service(
        slug=payload.slug,
        title=payload.title,
        summary=payload.summary,
        system=payload.system,
        component_type=payload.component_type,
        lifecycle=payload.lifecycle,
        owner=payload.owner,
        criticality=payload.criticality,
        tags=payload.tags,
        metadata_json=payload.metadata_json,
    )
    db.add(service)
    db.flush()
    namespace_route = add_service_namespace_route(db, service)

    primary_host = f"{payload.subdomain}.{BASE_DOMAIN_TOKEN}"
    if render_domain_value(primary_host) == render_domain_value(namespace_route.host):
        namespace_route.upstream = payload.upstream
        # Die Route dient jetzt dem Service selbst (nicht mehr der CP als Platzhalter)
        # und ist damit die öffentliche Primär-Route des Services.
        namespace_route.auth_policy = "public"
        route = namespace_route
    else:
        route = models.Route(
            service_id=service.id,
            parent_type="service",
            parent_id=service.id,
            host=primary_host,
            path="/",
            upstream=payload.upstream,
            tls=True,
            auth_policy="public",
            status="active",
        )
        db.add(route)

    if payload.port is not None:
        db.add(models.Port(service_id=service.id, number=payload.port, protocol="tcp", bind="127.0.0.1", purpose="web", status="active"))

    runtime_path = payload.runtime_path or f"{settings.selfhost_root}/stacks/services/{payload.slug}/docker-compose.yml"
    db.add(
        models.Runtime(
            service_id=service.id,
            runtime_type=payload.runtime_type,
            path=runtime_path,
            compose_project=payload.compose_project or payload.slug,
            restart_policy="unless-stopped",
        )
    )

    doc_path = payload.doc_path or f"{settings.selfhost_root}/docs/services/{payload.slug}/overview.{payload.slug}.md"
    doc_title = payload.doc_title or f"{payload.title} Betrieb"
    doc_file = Path(doc_path)
    doc_file.parent.mkdir(parents=True, exist_ok=True)
    if not doc_file.exists():
        rendered_host = render_domain_value(f"{payload.subdomain}.{{base_domain}}")
        doc_file.write_text(
            f"# {payload.title}\n\n"
            f"Status: migriert ueber Backstage Template / Control Plane.\n\n"
            f"## Zweck\n\n{payload.summary or payload.title}\n\n"
            f"## Betrieb\n\n"
            f"- Stack: `{runtime_path}`\n"
            f"- Interner Upstream: `{payload.upstream}`\n"
            f"- Externe URL: `https://{rendered_host}/`\n\n"
            f"## Pruefung\n\n"
            f"```bash\ncontrol-plane service show {payload.slug}\ncontrol-plane healthchecks-run {payload.slug}\n```\n",
            encoding="utf-8",
        )
    db.add(models.DocRef(service_id=service.id, doc_type="runbook", path=doc_path, title=doc_title))

    if payload.healthcheck_target:
        db.add(
            models.Healthcheck(
                service_id=service.id,
                check_type="http",
                target=payload.healthcheck_target,
                expected_status=payload.healthcheck_expected_status,
                timeout_seconds=5,
            )
        )

    log_activity(db, "managed_service.provision", "service", service.id, {"slug": service.slug, "subdomain": payload.subdomain})
    flush_or_409(db)
    validation_run = persist_validation_run(db, "managed-service-provision", commit=False)
    if validation_run.status != "passed":
        raise HTTPException(status_code=409, detail={"message": "validation failed", "validation_run_id": validation_run.id})

    caddy_artifact = generate_caddy(db)
    rendered_host = render_domain_value(route.host)
    cert_zones = run_caddy_cert_zones(rendered_host, apply=True, no_reload=True)

    validation = run_caddy_validate()
    if validation.returncode != 0:
        raise HTTPException(status_code=409, detail={"message": "caddy validate failed", "stderr": validation.stderr})
    reloaded = False
    if settings.caddy_reload_enabled:
        reload_cmd = ["sudo", "-n", settings.caddy_apply_command]
        reload = subprocess.run(reload_cmd, text=True, capture_output=True, check=False)
        if reload.returncode != 0:
            raise HTTPException(status_code=409, detail={"message": "caddy reload failed", "stderr": reload.stderr})
        reloaded = True

    db.commit()
    db.refresh(service)
    return ok(
        {
            "service": ServiceOut.model_validate(service).model_dump(mode="json"),
            "route": {**as_dict(route), "rendered_host": render_domain_value(route.host)},
            "doc_path": doc_path,
            "validation_run_id": validation_run.id,
            "artifacts": {"caddy": caddy_artifact},
            "caddy_cert_zones": cert_zones,
            "caddy_validate": "passed",
            "caddy_reloaded": reloaded,
        }
    )


@app.post("/api/v1/routes", dependencies=[Depends(require_token)])
def add_route(payload: RouteCreate, db: Session = Depends(get_session)) -> ApiResponse:
    data = payload.model_dump(exclude={"service_slug", "parent_type", "parent_slug"})
    if payload.parent_type and payload.parent_slug:
        if payload.parent_type == "service":
            service = get_service_by_slug(db, payload.parent_slug)
            data["service_id"] = service.id
            data["parent_type"] = "service"
            data["parent_id"] = service.id
        elif payload.parent_type == "subservice":
            sub = get_subservice_by_slug(db, payload.parent_slug)
            prefix = build_subservice_host_prefix(db, sub.id)
            try:
                data["host"] = build_subservice_route_host(data["host"], prefix)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            data["subservice_id"] = sub.id
            data["parent_type"] = "subservice"
            data["parent_id"] = sub.id
        else:
            raise HTTPException(status_code=400, detail=f"Invalid parent_type: {payload.parent_type}")
        route = models.Route(**data)
    elif payload.service_slug:
        service = get_service_by_slug(db, payload.service_slug)
        data["service_id"] = service.id
        data["parent_type"] = "service"
        data["parent_id"] = service.id
        route = models.Route(**data)
    else:
        raise HTTPException(status_code=400, detail="Either service_slug or parent_type+parent_slug is required")
    rendered_host = render_domain_value(route.host)
    for existing in db.query(models.Route).filter(models.Route.path == route.path).all():
        if render_domain_value(existing.host) == rendered_host:
            raise HTTPException(status_code=409, detail=f"duplicate route: {rendered_host}{route.path}")
    db.add(route)
    flush_or_409(db)
    cert_zones = run_caddy_cert_zones(render_domain_value(route.host), apply=True, no_reload=True) if route.tls and route.status == "active" else None
    log_activity(db, "route.create", "route", route.id, {"host": route.host, "path": route.path})
    commit_or_409(db)
    db.refresh(route)
    return ok({**as_dict(route), "rendered_host": render_domain_value(route.host), "caddy_cert_zones": cert_zones})


@app.patch("/api/v1/routes/{route_id}", dependencies=[Depends(require_token)])
def update_route(route_id: str, payload: RouteUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    route = db.get(models.Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="route not found")
    changes = payload.model_dump(exclude_unset=True)
    service_slug = changes.pop("service_slug", None)
    if service_slug is not None:
        if route.subservice_id is not None or route.parent_type == "subservice":
            raise HTTPException(status_code=409, detail="subservice routes cannot be reassigned to a service")
        service = get_service_by_slug(db, service_slug)
        route.service_id = service.id
        route.parent_type = "service"
        route.parent_id = service.id
    for key, value in changes.items():
        setattr(route, key, value)
    log_activity(db, "route.update", "route", route.id, payload.model_dump(exclude_unset=True))
    commit_or_409(db)
    db.refresh(route)
    return ok({**as_dict(route), "rendered_host": render_domain_value(route.host)})


@app.get("/api/v1/routes", dependencies=[Depends(require_token)])
def list_routes(db: Session = Depends(get_session)) -> ApiResponse:
    items = []
    for route in db.query(models.Route).order_by(models.Route.host, models.Route.path).all():
        item = as_dict(route)
        item["rendered_host"] = render_domain_value(route.host)
        if route.parent_type == "service" and route.service:
            item["parent_slug"] = route.service.slug
            item["parent_title"] = route.service.title
            item["parent_system"] = route.service.system
        elif route.parent_type == "subservice" and route.subservice:
            item["parent_slug"] = route.subservice.slug
            item["parent_title"] = route.subservice.title
        elif route.service:
            item["parent_type"] = "service"
            item["parent_slug"] = route.service.slug
            item["parent_title"] = route.service.title
            item["parent_system"] = route.service.system
        else:
            item["parent_slug"] = None
            item["parent_title"] = None
        items.append(item)
    return ok(items)


@app.get("/routes-ui", response_class=HTMLResponse)
def routes_ui_legacy(db: Session = Depends(get_session)) -> HTMLResponse:
    return subdomains_ui(db)


@app.get("/subdomains", response_class=HTMLResponse)
def subdomains_ui(db: Session = Depends(get_session)) -> HTMLResponse:
    # Bestehendes CSS/Port-Tabelle beibehalten
    ports = db.query(models.Port).outerjoin(models.Service).order_by(models.Port.number, models.Port.protocol).all()

    def esc(value: Any) -> str:
        import html
        return html.escape("" if value is None else str(value), quote=True)

    # ---- Baumstruktur aufbauen ----
    services = db.query(models.Service).order_by(models.Service.slug).all()
    all_subs = {sub.id: sub for sub in db.query(models.SubService).all()}
    routes_by_service: dict[str, list] = {}
    routes_by_sub: dict[str, list] = {}
    for rt in db.query(models.Route).order_by(models.Route.host, models.Route.path).all():
        item = {
            "host": render_domain_value(rt.host),
            "path": rt.path,
            "upstream": rt.upstream,
            "auth_policy": rt.auth_policy,
            "status": rt.status,
            "tls": rt.tls,
        }
        if rt.parent_type == "service":
            routes_by_service.setdefault(rt.parent_id, []).append(item)
        elif rt.parent_type == "subservice":
            routes_by_sub.setdefault(rt.parent_id, []).append(item)

    def render_sub_tree(parent_id: str, depth: int = 1) -> str:
        html_parts: list[str] = []
        children = [s for s in all_subs.values() if s.parent_id == parent_id]
        for sub in sorted(children, key=lambda x: x.slug):
            has_children = any(s.parent_id == sub.id for s in all_subs.values())
            has_routes = bool(routes_by_sub.get(sub.id))
            indent_style = f"style='padding-left:{depth * 24}px'"
            if has_children or has_routes:
                html_parts.append(
                    f"<details {indent_style}>"
                    f"<summary style='cursor:pointer;padding:6px 0'><strong>{esc(sub.slug)}</strong> "
                    f"<span style='color:#5f6b7a;font-size:13px'>{esc(sub.title)}</span></summary>"
                )
                for rt in routes_by_sub.get(sub.id, []):
                    link = f"https://{esc(rt['host'])}{esc(rt['path'])}"
                    html_parts.append(
                        f"<div style='padding-left:{depth * 24 + 20}px;padding-top:4px;padding-bottom:4px'>"
                        f"<a href='{link}'>{esc(rt['host'])}</a> "
                        f"<span style='color:#5f6b7a;font-size:12px'>{esc(rt['path'])} -> {esc(rt['upstream'])}</span>"
                        f"</div>"
                    )
                html_parts.append(render_sub_tree(sub.id, depth + 1))
                html_parts.append("</details>")
            else:
                html_parts.append(
                    f"<div {indent_style} style='padding:6px 0;padding-left:{depth * 24 + 8}px'>"
                    f"<strong>{esc(sub.slug)}</strong> "
                    f"<span style='color:#5f6b7a;font-size:13px'>{esc(sub.title)}</span>"
                    f"</div>"
                )
        return "".join(html_parts)

    tree_html_parts: list[str] = []
    for svc in services:
        svc_routes = routes_by_service.get(svc.id, [])
        svc_subs = [s for s in all_subs.values() if s.parent_type == "service" and s.parent_id == svc.id]
        if not svc_routes and not svc_subs:
            continue
        tree_html_parts.append(f"<details open style='margin-bottom:4px'>")
        tree_html_parts.append(
            f"<summary style='cursor:pointer;padding:10px 0;font-size:16px'>"
            f"<strong>{esc(svc.slug)}</strong> "
            f"<span style='color:#5f6b7a;font-size:13px'>{esc(svc.title or '')}</span>"
            f"</summary>"
        )
        for rt in svc_routes:
            link = f"https://{esc(rt['host'])}{esc(rt['path'])}"
            tree_html_parts.append(
                f"<div style='padding-left:28px;padding-top:4px;padding-bottom:4px'>"
                f"<span style='color:#5f6b7a'>Host:</span> <a href='{link}'>{esc(rt['host'])}</a> "
                f"<span style='color:#5f6b7a;font-size:12px'>{esc(rt['path'])} -> {esc(rt['upstream'])}</span>"
                f"</div>"
            )
        tree_html_parts.append(render_sub_tree(svc.id, 1))
        tree_html_parts.append("</details>")

    tree_html = "".join(tree_html_parts)

    # ---- Ports-Tabelle (wie bisher) ----
    port_rows = "".join(
        "<tr>"
        f"<td>{esc(port.service.slug if port.service else '')}</td>"
        f"<td>{esc(port.bind)}</td>"
        f"<td>{esc(port.number)}</td>"
        f"<td>{esc(port.protocol)}</td>"
        f"<td>{esc(port.purpose)}</td>"
        f"<td>{esc(port.status)}</td>"
        "</tr>"
        for port in ports
    )

    html_doc = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Control Plane - Subdomains</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #1f2933; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .meta {{ color: #5f6b7a; margin-bottom: 18px; }}
    .tree {{ border: 1px solid #d8dde6; border-radius: 8px; background: white; padding: 8px 20px; }}
    details > summary {{ list-style: none; }}
    details > summary::-webkit-details-marker {{ display: none; }}
    details > summary::before {{ content: "+"; margin-right: 6px; font-weight: bold; color: #155eef; }}
    details[open] > summary::before {{ content: "-"; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #d8dde6; border-radius: 8px; background: white; margin-top: 12px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 700px; }}
    th, td {{ border-bottom: 1px solid #e5e9f0; padding: 10px 12px; text-align: left; font-size: 14px; vertical-align: top; }}
    th {{ background: #edf1f5; font-weight: 650; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: #155eef; text-decoration: none; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #101418; color: #e7edf3; }}
      .meta {{ color: #a4afbd; }}
      .tree {{ background: #171c22; border-color: #303945; }}
      .table-wrap {{ background: #171c22; border-color: #303945; }}
      th {{ background: #222a33; }}
      th, td {{ border-color: #303945; }}
      a {{ color: #8ab4ff; }}
      details > summary::before {{ color: #8ab4ff; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>Control Plane - Subdomains</h1>
  <div class="meta">Live aus der Control-Plane-Datenbank. Secrets werden nicht angezeigt.</div>
  <h2>Services / Subdomains</h2>
  <div class="tree">{tree_html}</div>
  <h2>Ports</h2>
  <div class="table-wrap"><table><thead><tr><th>Dienst</th><th>Bind</th><th>Port</th><th>Proto</th><th>Zweck</th><th>Status</th></tr></thead><tbody>{port_rows}</tbody></table></div>
</main>
</body>
</html>
"""
    return HTMLResponse(html_doc)


@app.post("/api/v1/ports", dependencies=[Depends(require_token)])
def add_port(payload: PortCreate, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, payload.service_slug) if payload.service_slug else None
    port = models.Port(service_id=service.id if service else None, **payload.model_dump(exclude={"service_slug"}))
    db.add(port)
    flush_or_409(db)
    log_activity(db, "port.create", "port", port.id, {"number": port.number, "protocol": port.protocol})
    commit_or_409(db)
    return ok(as_dict(port))


@app.patch("/api/v1/ports/{port_id}", dependencies=[Depends(require_token)])
def update_port(port_id: str, payload: PortUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    port = db.get(models.Port, port_id)
    if port is None:
        raise HTTPException(status_code=404, detail="port not found")
    changes = payload.model_dump(exclude_unset=True)
    service_slug = changes.pop("service_slug", None)
    if service_slug is not None:
        port.service_id = get_service_by_slug(db, service_slug).id
    for key, value in changes.items():
        setattr(port, key, value)
    log_activity(db, "port.update", "port", port.id, payload.model_dump(exclude_unset=True))
    commit_or_409(db)
    db.refresh(port)
    return ok(as_dict(port))


def _add_child(
    db: Session,
    payload: Any,
    model: type,
    action: str,
    entity_kind: str,
    exclude: set[str] | None = None,
) -> ApiResponse:
    service = get_service_by_slug(db, payload.service_slug)
    item = model(service_id=service.id, **payload.model_dump(exclude={"service_slug", *(exclude or set())}))
    db.add(item)
    flush_or_409(db)
    log_activity(db, action, entity_kind, item.id, {"service": service.slug})
    commit_or_409(db)
    return ok(as_dict(item))


@app.post("/api/v1/runtimes", dependencies=[Depends(require_token)])
def add_runtime(payload: RuntimeCreate, db: Session = Depends(get_session)) -> ApiResponse:
    return _add_child(db, payload, models.Runtime, "runtime.create", "runtime")


@app.post("/api/v1/resources", dependencies=[Depends(require_token)])
def add_resource(payload: ResourceCreate, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, payload.service_slug) if payload.service_slug else None
    item = models.Resource(service_id=service.id if service else None, **payload.model_dump(exclude={"service_slug"}))
    db.add(item)
    flush_or_409(db)
    log_activity(db, "resource.create", "resource", item.id, {"slug": item.slug})
    commit_or_409(db)
    return ok(as_dict(item))


@app.post("/api/v1/apis", dependencies=[Depends(require_token)])
def add_api(payload: ApiEntityCreate, db: Session = Depends(get_session)) -> ApiResponse:
    return _add_child(db, payload, models.ApiEntity, "api.create", "api")


@app.post("/api/v1/skills", dependencies=[Depends(require_token)])
def add_skill(payload: SkillCreate, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, payload.service_slug) if payload.service_slug else None
    item = models.Skill(service_id=service.id if service else None, **payload.model_dump(exclude={"service_slug"}))
    db.add(item)
    flush_or_409(db)
    log_activity(db, "skill.create", "skill", item.id, {"slug": item.slug})
    commit_or_409(db)
    return ok(as_dict(item))


@app.post("/api/v1/secret-refs", dependencies=[Depends(require_token)])
def add_secret_ref(payload: SecretRefCreate, db: Session = Depends(get_session)) -> ApiResponse:
    return _add_child(db, payload, models.SecretRef, "secret_ref.create", "secret_ref")


@app.post("/api/v1/docs", dependencies=[Depends(require_token)])
def add_doc(payload: DocCreate, db: Session = Depends(get_session)) -> ApiResponse:
    return _add_child(db, payload, models.DocRef, "doc.create", "doc")


@app.post("/api/v1/healthchecks", dependencies=[Depends(require_token)])
def add_healthcheck(payload: HealthcheckCreate, db: Session = Depends(get_session)) -> ApiResponse:
    return _add_child(db, payload, models.Healthcheck, "healthcheck.create", "healthcheck")


@app.post("/api/v1/healthchecks/run", dependencies=[Depends(require_token)])
def run_healthchecks(service_slug: str | None = None, db: Session = Depends(get_session)) -> ApiResponse:
    query = db.query(models.Healthcheck)
    if service_slug:
        service = get_service_by_slug(db, service_slug)
        query = query.filter(models.Healthcheck.service_id == service.id)
    checks = query.order_by(models.Healthcheck.created_at).all()
    results = []
    for check in checks:
        passed = False
        error = ""
        if check.check_type == "http":
            try:
                response = httpx.get(check.target, timeout=check.timeout_seconds)
                passed = response.status_code == check.expected_status
                error = "" if passed else f"expected {check.expected_status}, got {response.status_code}"
            except Exception as exc:  # noqa: BLE001 - diagnostics endpoint must return the concrete error.
                error = str(exc)
        elif check.check_type == "tcp":
            try:
                host, port_text = check.target.rsplit(":", 1)
                with socket.create_connection((host, int(port_text)), timeout=check.timeout_seconds):
                    passed = True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
        else:
            error = f"unsupported check_type {check.check_type}"
        results.append({"id": check.id, "service_id": check.service_id, "target": check.target, "check_type": check.check_type, "passed": passed, "error": error})
    return ok({"passed": all(item["passed"] for item in results), "results": results})


@app.post("/api/v1/validate", response_model=ValidationRunOut, dependencies=[Depends(require_token)])
def validate(scope: str = "all", db: Session = Depends(get_session)) -> models.ValidationRun:
    run = persist_validation_run(db, scope)
    log_activity(db, "validation.run", "validation_run", run.id, {"scope": scope, "status": run.status})
    db.commit()
    return run


@app.post("/api/v1/generate/caddy", dependencies=[Depends(require_token)])
def generate_caddy_endpoint(db: Session = Depends(get_session)) -> ApiResponse:
    data = generate_caddy(db)
    log_activity(db, "generate.caddy", "artifact", "", data)
    db.commit()
    return ok(data)


@app.post("/api/v1/generate/all", dependencies=[Depends(require_token)])
def generate_all_endpoint(db: Session = Depends(get_session)) -> ApiResponse:
    return ok({"caddy": generate_caddy(db)})


@app.post("/api/v1/deploy/caddy/plan", dependencies=[Depends(require_token)])
def caddy_plan(db: Session = Depends(get_session)) -> ApiResponse:
    validation_run = persist_validation_run(db, "caddy")
    artifact = generate_caddy(db)
    cert_zone_plans = run_caddy_cert_zones_for_routes(db, apply=False, no_reload=True)
    return ok({"validation_status": validation_run.status, "artifact": artifact, "cert_zone_plans": cert_zone_plans, "apply_allowed": validation_run.status == "passed"})


@app.post("/api/v1/deploy/caddy/apply", dependencies=[Depends(require_token)])
def caddy_apply(db: Session = Depends(get_session)) -> ApiResponse:
    validation_run = persist_validation_run(db, "caddy")
    if validation_run.status != "passed":
        raise HTTPException(status_code=409, detail="fatal validation errors block caddy apply")
    artifact = generate_caddy(db)
    cert_zones = run_caddy_cert_zones_for_routes(db, apply=True, no_reload=True)
    validation = run_caddy_validate()
    if validation.returncode != 0:
        raise HTTPException(status_code=409, detail={"message": "caddy validate failed", "stderr": validation.stderr})
    reloaded = False
    if get_settings().caddy_reload_enabled:
        reload_cmd = ["sudo", "-n", get_settings().caddy_apply_command]
        reload = subprocess.run(reload_cmd, text=True, capture_output=True, check=False)
        if reload.returncode != 0:
            raise HTTPException(status_code=409, detail={"message": "caddy reload failed", "stderr": reload.stderr})
        reloaded = True
    return ok({"artifact": artifact, "cert_zones": cert_zones, "caddy_validate": "passed", "reloaded": reloaded})


@app.post("/api/v1/caddy/cert-zones/plan", dependencies=[Depends(require_token)])
def caddy_cert_zones_plan(payload: CaddyCertZoneRequest) -> ApiResponse:
    return ok(
        run_caddy_cert_zones(
            payload.domain,
            apply=False,
            no_reload=True,
            max_new_zones_per_run=payload.max_new_zones_per_run,
            max_total_zones_per_root=payload.max_total_zones_per_root,
            exclude_root_zone=payload.exclude_root_zone,
        )
    )


@app.post("/api/v1/caddy/cert-zones/apply", dependencies=[Depends(require_token)])
def caddy_cert_zones_apply(payload: CaddyCertZoneRequest) -> ApiResponse:
    result = run_caddy_cert_zones(
        payload.domain,
        apply=True,
        no_reload=payload.no_reload,
        max_new_zones_per_run=payload.max_new_zones_per_run,
        max_total_zones_per_root=payload.max_total_zones_per_root,
        exclude_root_zone=payload.exclude_root_zone,
    )
    return ok(result)


@app.get("/api/v1/caddy-schutz/status", dependencies=[Depends(require_token)])
def caddy_schutz_status(db: Session = Depends(get_session)) -> ApiResponse:
    routes = db.query(models.Route).order_by(models.Route.host, models.Route.path).all()
    return ok(
        {
            "enabled": get_settings().caddy_protection_enabled,
            "configured_login_count": len(configured_logins()),
            "configured_api_key_count": len(configured_api_keys()),
            "cookie_enabled": get_settings().caddy_protection_cookie_enabled,
            "routes": [
                {
                    "id": route.id,
                    "host": route.host,
                    "rendered_host": render_domain_value(route.host),
                    "path": route.path,
                    "configured": route.caddy_protection_enabled,
                    "effective": resolve_route_protection(db, route),
                }
                for route in routes
            ],
        }
    )


@app.patch("/api/v1/caddy-schutz/services/{slug}", dependencies=[Depends(require_token)])
def set_service_caddy_schutz(slug: str, payload: CaddyProtectionUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    if payload.enabled is None:
        raise HTTPException(status_code=400, detail="enabled must be true or false for services")
    service.caddy_protection_enabled = payload.enabled
    log_activity(db, "caddy_schutz.service.update", "service", service.id, {"slug": service.slug, "enabled": payload.enabled})
    commit_or_409(db)
    return ok(as_dict(service))


@app.patch("/api/v1/caddy-schutz/subservices/{slug}", dependencies=[Depends(require_token)])
def set_subservice_caddy_schutz(slug: str, payload: CaddyProtectionUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    sub = get_subservice_by_slug(db, slug)
    sub.caddy_protection_enabled = payload.enabled
    log_activity(db, "caddy_schutz.subservice.update", "subservice", sub.id, {"slug": sub.slug, "enabled": payload.enabled})
    commit_or_409(db)
    return ok(as_dict(sub))


@app.patch("/api/v1/caddy-schutz/routes/{route_id}", dependencies=[Depends(require_token)])
def set_route_caddy_schutz(route_id: str, payload: CaddyProtectionUpdate, db: Session = Depends(get_session)) -> ApiResponse:
    route = db.query(models.Route).filter(models.Route.id == route_id).one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail=f"route not found: {route_id}")
    route.caddy_protection_enabled = payload.enabled
    log_activity(db, "caddy_schutz.route.update", "route", route.id, {"host": route.host, "enabled": payload.enabled})
    commit_or_409(db)
    return ok({**as_dict(route), "effective_caddy_protection_enabled": resolve_route_protection(db, route)})


@app.post("/api/v1/export/json", dependencies=[Depends(require_token)])
def export_json_endpoint(db: Session = Depends(get_session)) -> ApiResponse:
    return ok(export_json(db))


@app.get("/api/v1/activity", dependencies=[Depends(require_token)])
def activity(db: Session = Depends(get_session)) -> ApiResponse:
    items = db.query(models.ActivityLog).order_by(models.ActivityLog.created_at.desc()).limit(100).all()
    return ok([as_dict(item) for item in items])


@app.post("/api/v1/comments", dependencies=[Depends(require_token)])
def add_comment(payload: CommentCreate, db: Session = Depends(get_session)) -> ApiResponse:
    comment = models.Comment(**payload.model_dump())
    db.add(comment)
    flush_or_409(db)
    log_activity(db, "comment.create", payload.entity_kind, payload.entity_id, {"comment_id": comment.id})
    commit_or_409(db)
    return ok(as_dict(comment))


@app.get("/api/v1/agent-context/{slug}", dependencies=[Depends(require_token)])
def agent_context(slug: str, db: Session = Depends(get_session)) -> ApiResponse:
    service = get_service_by_slug(db, slug)
    return ok(
        {
            "service": as_dict(service),
            "routes": [{**as_dict(route), "rendered_host": render_domain_value(route.host)} for route in service.routes],
            "docs": [as_dict(doc) for doc in service.docs],
            "skills": [as_dict(skill) for skill in service.skills],
            "healthchecks": [as_dict(check) for check in service.healthchecks],
            "rules": [
                "Use control-plane or the Control Plane for changes.",
                "Do not edit generated Caddy or Backstage files manually.",
                "Do not store secret values in docs, Backstage, exports, or git.",
            ],
        }
    )


@app.get("/api/v1/meta", dependencies=[Depends(require_token)])
def meta() -> ApiResponse:
    settings = get_settings()
    return ok(
        {
            "name": "control-plane",
            "version": "0.1.0",
            "public_base_domain": settings.public_base_domain,
            "target_base_domain": settings.target_base_domain,
            "domain_note": "public_base_domain is provisional during development; set it to target_base_domain for final cutover.",
        }
    )
