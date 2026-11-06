from pathlib import Path
import urllib.error

import yaml


def write_service_manifest(root: Path, slug: str, *, archivable: bool = True) -> dict:
    from control_plane.config import get_settings

    stack = root / "stacks" / "services" / slug
    data = root / "data" / "services" / slug
    docs = root / "docs" / "services" / slug
    app = root / "apps" / "services" / slug
    build = Path(get_settings().outsourced_build_area_root) / "services" / slug
    for path in [stack, data, docs, app, build]:
        path.mkdir(parents=True, exist_ok=True)
    (data / "state.txt").write_text("runtime-state", encoding="utf-8")
    (docs / "overview.md").write_text(f"# {slug}\n", encoding="utf-8")
    (app / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (build / "build.config.yaml").write_text("name: test\n", encoding="utf-8")
    compose = stack / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        f"  {slug}:\n"
        "    image: alpine:3.20\n"
        "    command: ['sh', '-c', 'sleep 1']\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "service": {"slug": slug, "name": "Test Service", "category": "tests", "status": "active"},
        "lifecycle": {"archivable": archivable, "snapshot_supported": True, "archive_requires_confirmation": True},
        "runtime": {"backend": "docker_compose", "compose_project": slug, "compose_file": str(compose)},
        "paths": {
            "stack_dir": str(stack),
            "compose_file": str(compose),
            "data_dir": str(data),
            "docs_dir": str(docs),
            "app_dir": str(app),
            "build_area_dir": str(build),
        },
        "dependencies": {"hard": [], "optional": []},
    }
    (stack / "service.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest


def current_selfhost_root(client) -> Path:
    from control_plane.config import get_settings

    return Path(get_settings().selfhost_root)


def test_lifecycle_listing_and_snapshot(client):
    root = current_selfhost_root(client)
    write_service_manifest(root, "snap-svc")
    service = client.post("/api/v1/services", json={"slug": "snap-svc", "title": "Snap Service"})
    assert service.status_code == 200, service.text

    listing = client.get("/api/v1/lifecycle/services")
    assert listing.status_code == 200, listing.text
    assert any(item["slug"] == "snap-svc" and item["archivable"] is True for item in listing.json()["data"])

    plan = client.post("/api/v1/lifecycle/services/snap-svc/plan-snapshot")
    assert plan.status_code == 200, plan.text
    plan_data = plan.json()["data"]
    assert plan_data["blocked"] is False
    assert plan_data["plan_hash"]

    snapshot = client.post("/api/v1/lifecycle/services/snap-svc/execute-snapshot", json={"plan_hash": plan_data["plan_hash"]})
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()["data"]
    assert Path(data["archive_path"]).exists()
    assert Path(data["archive_dir"], "manifest.json").exists()
    assert Path(data["archive_dir"], "checksums.json").exists()
    assert Path(data["archive_dir"], "path-metadata.json").exists()


def test_lifecycle_archive_blocks_non_archivable(client):
    root = current_selfhost_root(client)
    write_service_manifest(root, "core-svc", archivable=False)
    service = client.post("/api/v1/services", json={"slug": "core-svc", "title": "Core Service"})
    assert service.status_code == 200, service.text

    plan = client.post("/api/v1/lifecycle/services/core-svc/plan-archive")
    assert plan.status_code == 200, plan.text
    assert plan.json()["data"]["blocked"] is True

    execute = client.post("/api/v1/lifecycle/services/core-svc/execute-archive", json={"plan_hash": plan.json()["data"]["plan_hash"]})
    assert execute.status_code == 409


def test_lifecycle_healthcheck_allows_expected_http_error(client, monkeypatch):
    service = client.post("/api/v1/services", json={"slug": "auth-svc", "title": "Auth Service"})
    assert service.status_code == 200, service.text
    healthcheck = client.post(
        "/api/v1/healthchecks",
        json={"service_slug": "auth-svc", "check_type": "http", "target": "https://auth.example.test/", "expected_status": 401},
    )
    assert healthcheck.status_code == 200, healthcheck.text

    def raise_unauthorized(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://auth.example.test/", 401, "Unauthorized", None, None)

    monkeypatch.setattr("control_plane.lifecycle.runner.urllib.request.urlopen", raise_unauthorized)

    from control_plane.db import SessionLocal
    from control_plane.lifecycle.runner import run_healthchecks_for_service

    with SessionLocal() as db:
        results = run_healthchecks_for_service(db, "auth-svc")

    assert results[0]["passed"] is True
    assert results[0]["error"] == ""


def test_lifecycle_archive_and_restore_roundtrip_without_runtime_apply(client):
    root = current_selfhost_root(client)
    write_service_manifest(root, "roundtrip-svc")
    service = client.post("/api/v1/services", json={"slug": "roundtrip-svc", "title": "Roundtrip Service"})
    assert service.status_code == 200, service.text
    route = client.post(
        "/api/v1/routes",
        json={"service_slug": "roundtrip-svc", "host": "app.roundtrip-svc.{base_domain}", "upstream": "http://127.0.0.1:1234"},
    )
    assert route.status_code == 200, route.text
    port = client.post("/api/v1/ports", json={"service_slug": "roundtrip-svc", "number": 1234, "purpose": "http"})
    assert port.status_code == 200, port.text

    bad_execute = client.post("/api/v1/lifecycle/services/roundtrip-svc/execute-archive", json={"plan_hash": "0" * 64})
    assert bad_execute.status_code == 409

    plan = client.post("/api/v1/lifecycle/services/roundtrip-svc/plan-archive").json()["data"]
    archived = client.post("/api/v1/lifecycle/services/roundtrip-svc/execute-archive", json={"plan_hash": plan["plan_hash"]})
    assert archived.status_code == 200, archived.text
    archive_data = archived.json()["data"]
    assert not (root / "stacks" / "services" / "roundtrip-svc").exists()
    assert Path(archive_data["quarantine_dir"]).exists()

    detail = client.get("/api/v1/services/roundtrip-svc").json()["data"]
    assert detail["status"] == "archived"
    assert {route["status"] for route in detail["routes"]} == {"inactive"}
    assert {port["status"] for port in detail["ports"]} == {"inactive"}

    restore_plan = client.post(f"/api/v1/lifecycle/archives/{archive_data['archive_id']}/plan-restore")
    assert restore_plan.status_code == 200, restore_plan.text
    restore_plan_data = restore_plan.json()["data"]
    assert restore_plan_data["blocked"] is False

    restored = client.post(
        f"/api/v1/lifecycle/archives/{archive_data['archive_id']}/execute-restore",
        json={"plan_hash": restore_plan_data["plan_hash"]},
    )
    assert restored.status_code == 200, restored.text
    assert (root / "stacks" / "services" / "roundtrip-svc" / "service.yaml").exists()
    detail = client.get("/api/v1/services/roundtrip-svc").json()["data"]
    assert detail["status"] == "active"
    assert {route["status"] for route in detail["routes"]} == {"active"}
    assert {port["status"] for port in detail["ports"]} == {"active"}


def test_legacy_archive_endpoint_is_disabled(client):
    root = current_selfhost_root(client)
    write_service_manifest(root, "legacy-svc")
    service = client.post("/api/v1/services", json={"slug": "legacy-svc", "title": "Legacy Service"})
    assert service.status_code == 200, service.text
    response = client.post("/api/v1/services/legacy-svc/archive")
    assert response.status_code == 410
