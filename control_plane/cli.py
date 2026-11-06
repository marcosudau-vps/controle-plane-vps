import json
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from control_plane.domains import host_template_for_subdomain

app = typer.Typer(help="Control Plane CLI")
service_app = typer.Typer(help="Manage services")
subservice_app = typer.Typer(help="Manage subservices")
route_app = typer.Typer(help="Manage routes")
runtime_app = typer.Typer(help="Manage runtimes")
doc_app = typer.Typer(help="Manage docs")
skill_app = typer.Typer(help="Manage skills")
generate_app = typer.Typer(help="Generate artifacts")
deploy_app = typer.Typer(help="Deploy generated artifacts")
export_app = typer.Typer(help="Export control-plane data")
cert_app = typer.Typer(help="Manage Caddy DNS-01 certificate zones")
lifecycle_app = typer.Typer(help="Manage service lifecycle archives")

app.add_typer(service_app, name="service")
app.add_typer(subservice_app, name="subservice")
app.add_typer(route_app, name="route")
app.add_typer(runtime_app, name="runtime")
app.add_typer(doc_app, name="doc")
app.add_typer(skill_app, name="skill")
app.add_typer(generate_app, name="generate")
app.add_typer(deploy_app, name="deploy")
app.add_typer(export_app, name="export")
app.add_typer(cert_app, name="cert-zones")
app.add_typer(lifecycle_app, name="lifecycle")


def base_url() -> str:
    legacy_prefix = "SELFHOST" + "_CONTROL_"
    direct = os.environ.get("CP_API_URL") or os.environ.get(f"{legacy_prefix}URL")
    if direct:
        return direct

    env_file = Path(os.environ.get("CP_ENV_FILE", "/home/marco/selfhost/secrets/control-plane.env"))
    if env_file.exists():
        values: dict[str, str] = {}
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
        if values.get("CP_API_URL"):
            return values["CP_API_URL"]
        if values.get(f"{legacy_prefix}URL"):
            return values[f"{legacy_prefix}URL"]
        host = values.get("CP_BIND_HOST") or values.get(f"{legacy_prefix}BIND_HOST")
        port = values.get("CP_BIND_PORT") or values.get(f"{legacy_prefix}BIND_PORT") or "8765"
        if host:
            return f"http://{host}:{port}"

    return "http://127.0.0.1:8765"


def token() -> str | None:
    legacy_prefix = "SELFHOST" + "_CONTROL_"
    direct = os.environ.get("CP_API_TOKEN") or os.environ.get(f"{legacy_prefix}API_TOKEN")
    if direct:
        return direct
    env_file = Path(os.environ.get("CP_ENV_FILE", "/home/marco/selfhost/secrets/control-plane.env"))
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in {"CP_API_TOKEN", f"{legacy_prefix}API_TOKEN"}:
                return value.strip().strip('"').strip("'")
    token_file = os.environ.get("CP_TOKEN_FILE", "/home/marco/selfhost/secrets/control-plane-token")
    path = Path(token_file)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {}
    api_token = token()
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    with httpx.Client(base_url=base_url(), headers=headers, timeout=300) as client:
        response = client.request(method, path, json=payload)
    if response.status_code >= 400:
        typer.echo(response.text)
        raise typer.Exit(1)
    data = response.json()
    return data.get("data", data)


def emit(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True, default=str))


@app.command()
def doctor() -> None:
    emit(request("GET", "/health"))
    emit(request("GET", "/api/v1/meta"))


@app.command()
def validate(scope: str = "all") -> None:
    emit(request("POST", f"/api/v1/validate?scope={scope}"))


@app.command("healthchecks-run")
def healthchecks_run(service_slug: str | None = None) -> None:
    path = "/api/v1/healthchecks/run"
    if service_slug:
        path = f"{path}?service_slug={service_slug}"
    emit(request("POST", path))


@service_app.command("list")
def service_list() -> None:
    emit(request("GET", "/api/v1/services"))


@service_app.command("show")
def service_show(slug: str) -> None:
    emit(request("GET", f"/api/v1/services/{slug}"))


@service_app.command("tree")
def service_tree(slug: str) -> None:
    emit(request("GET", f"/api/v1/services/{slug}/tree"))


@service_app.command("create")
def service_create(
    slug: str,
    title: str,
    system: str = "services",
    component_type: str = "service",
    lifecycle: str = "development",
    owner: str = "marco",
    criticality: int = 3,
    summary: str = "",
    tag: list[str] = typer.Option(default_factory=list),
) -> None:
    emit(
        request(
            "POST",
            "/api/v1/services",
            {
                "slug": slug,
                "title": title,
                "system": system,
                "component_type": component_type,
                "lifecycle": lifecycle,
                "owner": owner,
                "criticality": criticality,
                "summary": summary,
                "tags": tag,
            },
        )
    )


@subservice_app.command("list")
def subservice_list() -> None:
    emit(request("GET", "/api/v1/subservices"))


@subservice_app.command("show")
def subservice_show(slug: str) -> None:
    emit(request("GET", f"/api/v1/subservices/{slug}"))


@subservice_app.command("tree")
def subservice_tree(slug: str) -> None:
    emit(request("GET", f"/api/v1/subservices/{slug}/tree"))


@subservice_app.command("create")
def subservice_create(slug: str, title: str, parent: str) -> None:
    parts = parent.split(":", 1)
    parent_type = parts[0]
    parent_slug = parts[1] if len(parts) > 1 else ""
    emit(
        request(
            "POST",
            "/api/v1/subservices",
            {
                "slug": slug,
                "title": title,
                "parent_type": parent_type,
                "parent_id": parent_slug,
            },
        )
    )


@subservice_app.command("update")
def subservice_update(slug: str, title: str | None = None, status: str | None = None) -> None:
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if status is not None:
        payload["status"] = status
    emit(request("PATCH", f"/api/v1/subservices/{slug}", payload))


@subservice_app.command("delete")
def subservice_delete(slug: str) -> None:
    emit(request("DELETE", f"/api/v1/subservices/{slug}"))


@route_app.command("add")
def route_add(service_slug: str | None = None, parent: str | None = None, host: str | None = None, upstream: str = "", path: str = "/", auth_policy: str = "public") -> None:
    payload: dict[str, Any] = {"path": path, "upstream": upstream, "auth_policy": auth_policy}
    if host:
        payload["host"] = host
    if parent:
        parts = parent.split(":", 1)
        payload["parent_type"] = parts[0]
        payload["parent_slug"] = parts[1] if len(parts) > 1 else ""
    elif service_slug:
        payload["service_slug"] = service_slug
    emit(request("POST", "/api/v1/routes", payload))


@route_app.command("add-subdomain")
def route_add_subdomain(service_slug: str | None = None, parent: str | None = None, subdomain: str = "", upstream: str = "", path: str = "/", auth_policy: str = "public") -> None:
    host = host_template_for_subdomain(subdomain)
    payload: dict[str, Any] = {"host": host, "path": path, "upstream": upstream, "auth_policy": auth_policy}
    if parent:
        parts = parent.split(":", 1)
        payload["parent_type"] = parts[0]
        payload["parent_slug"] = parts[1] if len(parts) > 1 else ""
    elif service_slug:
        payload["service_slug"] = service_slug
    emit(request("POST", "/api/v1/routes", payload))


@runtime_app.command("add")
def runtime_add(service_slug: str, runtime_type: str, path: str = "", compose_project: str = "", systemd_unit: str = "") -> None:
    emit(
        request(
            "POST",
            "/api/v1/runtimes",
            {
                "service_slug": service_slug,
                "runtime_type": runtime_type,
                "path": path,
                "compose_project": compose_project,
                "systemd_unit": systemd_unit,
            },
        )
    )


@doc_app.command("add")
def doc_add(service_slug: str, doc_type: str, path: str, title: str) -> None:
    emit(request("POST", "/api/v1/docs", {"service_slug": service_slug, "doc_type": doc_type, "path": path, "title": title}))


@skill_app.command("add")
def skill_add(service_slug: str, slug: str, title: str, path: str, skill_type: str = "component", description: str = "") -> None:
    emit(
        request(
            "POST",
            "/api/v1/skills",
            {"service_slug": service_slug, "slug": slug, "title": title, "path": path, "skill_type": skill_type, "description": description},
        )
    )


@generate_app.command("caddy")
def generate_caddy() -> None:
    emit(request("POST", "/api/v1/generate/caddy"))


@generate_app.command("backstage")
def generate_backstage() -> None:
    emit(request("POST", "/api/v1/generate/backstage"))


@generate_app.command("docs")
def generate_docs() -> None:
    emit(request("POST", "/api/v1/generate/docs"))


@generate_app.command("all")
def generate_all() -> None:
    emit(request("POST", "/api/v1/generate/all"))


@deploy_app.command("caddy-plan")
def caddy_plan() -> None:
    emit(request("POST", "/api/v1/deploy/caddy/plan"))


@deploy_app.command("caddy-apply")
def caddy_apply() -> None:
    emit(request("POST", "/api/v1/deploy/caddy/apply"))


@cert_app.command("plan")
def cert_zones_plan(domain: str, exclude_root_zone: bool = False) -> None:
    emit(request("POST", "/api/v1/caddy/cert-zones/plan", {"domain": domain, "exclude_root_zone": exclude_root_zone}))


@cert_app.command("apply")
def cert_zones_apply(domain: str, exclude_root_zone: bool = False, no_reload: bool = False) -> None:
    emit(request("POST", "/api/v1/caddy/cert-zones/apply", {"domain": domain, "exclude_root_zone": exclude_root_zone, "no_reload": no_reload}))


@lifecycle_app.command("list")
def lifecycle_list() -> None:
    emit(request("GET", "/api/v1/lifecycle/services"))


@lifecycle_app.command("show")
def lifecycle_show(slug: str) -> None:
    emit(request("GET", f"/api/v1/lifecycle/services/{slug}"))


@lifecycle_app.command("plan-archive")
def lifecycle_plan_archive(slug: str) -> None:
    emit(request("POST", f"/api/v1/lifecycle/services/{slug}/plan-archive"))


def resolve_plan_hash(plan_hash: str | None, plan_hash_option: str | None) -> str:
    resolved = plan_hash_option or plan_hash
    if not resolved:
        raise typer.BadParameter("plan hash is required, either as argument or --plan-hash")
    return resolved


@lifecycle_app.command("execute-archive")
def lifecycle_execute_archive(
    slug: str,
    plan_hash: Annotated[str | None, typer.Argument()] = None,
    plan_hash_option: Annotated[str | None, typer.Option("--plan-hash")] = None,
) -> None:
    emit(request("POST", f"/api/v1/lifecycle/services/{slug}/execute-archive", {"plan_hash": resolve_plan_hash(plan_hash, plan_hash_option)}))


@lifecycle_app.command("plan-snapshot")
def lifecycle_plan_snapshot(slug: str) -> None:
    emit(request("POST", f"/api/v1/lifecycle/services/{slug}/plan-snapshot"))


@lifecycle_app.command("execute-snapshot")
def lifecycle_execute_snapshot(
    slug: str,
    plan_hash: Annotated[str | None, typer.Argument()] = None,
    plan_hash_option: Annotated[str | None, typer.Option("--plan-hash")] = None,
) -> None:
    emit(request("POST", f"/api/v1/lifecycle/services/{slug}/execute-snapshot", {"plan_hash": resolve_plan_hash(plan_hash, plan_hash_option)}))


@lifecycle_app.command("snapshot")
def lifecycle_snapshot(slug: str) -> None:
    plan = request("POST", f"/api/v1/lifecycle/services/{slug}/plan-snapshot")
    emit(request("POST", f"/api/v1/lifecycle/services/{slug}/execute-snapshot", {"plan_hash": plan["plan_hash"]}))


@lifecycle_app.command("inspect")
def lifecycle_inspect(archive_id: Annotated[str | None, typer.Argument()] = None, archive_dir: str | None = None, archive_path: str | None = None) -> None:
    emit(request("POST", "/api/v1/lifecycle/archives/inspect", {"archive_id": archive_id, "archive_dir": archive_dir, "archive_path": archive_path}))


@lifecycle_app.command("plan-restore")
def lifecycle_plan_restore(archive_id: str) -> None:
    emit(request("POST", f"/api/v1/lifecycle/archives/{archive_id}/plan-restore"))


@lifecycle_app.command("execute-restore")
def lifecycle_execute_restore(
    archive_id: str,
    plan_hash: Annotated[str | None, typer.Argument()] = None,
    plan_hash_option: Annotated[str | None, typer.Option("--plan-hash")] = None,
) -> None:
    emit(request("POST", f"/api/v1/lifecycle/archives/{archive_id}/execute-restore", {"plan_hash": resolve_plan_hash(plan_hash, plan_hash_option)}))


@export_app.command("json")
def export_json() -> None:
    emit(request("POST", "/api/v1/export/json"))


@app.command("agent-context")
def agent_context(slug: str) -> None:
    emit(request("GET", f"/api/v1/agent-context/{slug}"))


if __name__ == "__main__":
    app()
