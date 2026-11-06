import yaml
import json


def plan(c, rt, action="stop", key="example-key-0001", **extra):
    r = c.post(
        "/api/v1/services/sample-app/operations/plan",
        json={
            "action": action,
            "runtime_id": rt["id"],
            "idempotency_key": key,
            **extra,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def execute(c, p):
    return c.post(
        f"/api/v1/operations/{p['id']}/execute",
        json={"plan_hash": p["plan_hash"], "approved": True},
    )


def test_profile_alias_contract_yaml(managed):
    c, rt, f = managed
    r = c.put(
        "/api/v1/services/sample-app/profile",
        json={
            "expected_revision": 0,
            "description": "Long description",
            "category": "testing",
            "archivable": True,
        },
    )
    assert r.status_code == 200, r.text
    assert (
        c.put(
            "/api/v1/services/sample-app/profile", json={"expected_revision": 0}
        ).status_code
        == 412
    )
    assert (
        c.post(
            "/api/v1/services/sample-app/aliases", json={"alias": "legacy-app"}
        ).status_code
        == 200
    )
    r = c.get("/api/v1/services/legacy-app/contract")
    assert r.status_code == 200 and r.headers["etag"]
    assert r.json()["data"]["service"]["slug"] == "sample-app"
    assert (
        yaml.safe_load(c.get("/api/v1/services/sample-app/contract?format=yaml").text)[
            "schema_version"
        ]
        == "1.0"
    )
    assert (
        c.post(
            "/api/v1/services", json={"slug": "legacy-app", "title": "Collision"}
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/v1/services/sample-app/aliases", json={"alias": "sample-app"}
        ).status_code
        == 409
    )


def test_metadata_conflict_paths_and_secrets(managed):
    c, rt, f = managed
    assert (
        c.put(
            "/api/v1/services/sample-app/profile",
            json={"expected_revision": 0, "archivable": False},
        ).status_code
        == 200
    )
    payload = {
        "service_yaml": {
            "service": {"slug": "sample-app"},
            "lifecycle": {"archivable": True},
        }
    }
    p = c.post("/api/v1/services/sample-app/metadata/plan", json=payload).json()["data"]
    assert "archivable" in p["conflicts"]
    assert (
        c.post(
            "/api/v1/services/sample-app/metadata/import",
            json={**payload, "plan_hash": p["plan_hash"]},
        ).status_code
        == 409
    )
    payload["resolutions"] = {"archivable": "service_yaml"}
    p = c.post("/api/v1/services/sample-app/metadata/plan", json=payload).json()["data"]
    assert (
        c.post(
            "/api/v1/services/sample-app/metadata/import",
            json={**payload, "plan_hash": p["plan_hash"]},
        ).status_code
        == 200
    )
    assert (
        c.put(
            "/api/v1/services/sample-app/profile",
            json={"expected_revision": 2, "paths": {"data_dir": "/etc"}},
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/api/v1/services/sample-app/profile",
            json={"expected_revision": 2, "description": "password=unsafe"},
        ).status_code
        == 422
    )


def test_stop_start_idempotency_audit(managed):
    c, rt, f = managed
    p = plan(c, rt)
    assert plan(c, rt)["id"] == p["id"]
    assert execute(c, p).status_code == 202
    result = c.get("/api/v1/operations/" + p["id"]).json()["data"]
    assert result["status"] == "completed", result
    assert f.state == "exited"
    assert execute(c, p).status_code == 202
    assert len([x for x in f.calls if x[0] == "stop"]) == 1
    assert (
        c.get("/api/v1/services/sample-app/runtime/status").json()["data"][0][
            "desired_state"
        ]
        == "stopped"
    )
    p = plan(c, rt, action="start", key="example-key-0002")
    assert execute(c, p).status_code == 202
    assert f.state == "running" and not any(
        x[0] in {"up", "pull", "build", "down"} for x in f.calls
    )
    assert "operation.approve" in [
        a["action"] for a in c.get("/api/v1/management/activities").json()["data"]
    ]


def test_stale_approval_disabled_permissions(managed):
    c, rt, f = managed
    p = plan(c, rt)
    assert (
        c.post(
            "/api/v1/operations/" + p["id"] + "/execute",
            json={"plan_hash": p["plan_hash"]},
        ).status_code
        == 403
    )
    f.state = "exited"
    assert execute(c, p).status_code == 412
    f.state = "running"
    for token, action in [("viewer-key", "stop"), ("operator-key", "deploy")]:
        assert (
            c.post(
                "/api/v1/services/sample-app/operations/plan",
                json={
                    "runtime_id": rt["id"],
                    "action": action,
                    "idempotency_key": "reader-request-01",
                },
                headers={"Authorization": "Bearer " + token},
            ).status_code
            == 403
        )
    from control_plane.config import get_settings

    get_settings().runtime_apply_enabled = False
    assert execute(c, p).status_code == 403


def test_policy_version_and_runtime_path(managed):
    c, rt, f = managed
    rule = {
        "rule_id": "maintenance-lock",
        "version": 1,
        "service_slug": "sample-app",
        "severity": "block",
        "actions": ["stop"],
        "message": "Maintenance lock is active",
    }
    assert c.post("/api/v1/policies", json=rule).status_code == 200
    assert c.post("/api/v1/policies", json=rule).status_code == 409
    assert execute(c, plan(c, rt)).status_code == 409
    from control_plane.db import SessionLocal
    from control_plane import models

    with SessionLocal() as db:
        db.get(models.Runtime, rt["id"]).path = "/etc/passwd"
        db.commit()
    assert (
        c.post(
            "/api/v1/services/sample-app/operations/plan",
            json={
                "runtime_id": rt["id"],
                "action": "stop",
                "idempotency_key": "bad-path-request",
            },
        ).status_code
        == 422
    )


def test_database_protection(managed):
    c, rt, f = managed
    from control_plane.db import SessionLocal
    from control_plane import models

    with SessionLocal() as db:
        db.query(models.Service).filter_by(
            slug="sample-app"
        ).one().component_type = "database"
        db.commit()
    assert execute(c, plan(c, rt)).status_code == 409
    assert not c.post(
        "/api/v1/services/sample-app/policies/validate", json={"action": "stop"}
    ).json()["data"]["allowed"]
    assert (
        c.put(
            "/api/v1/services/sample-app/profile",
            json={"expected_revision": 0, "archivable": True},
        ).status_code
        == 403
    )


def test_update_and_rollback(managed):
    c, rt, f = managed
    r = c.put(
        "/api/v1/services/sample-app/deployments/sources",
        json={
            "runtime_id": rt["id"],
            "compose_service": "app",
            "source_kind": "registry_image",
            "image_ref": "example/app:1",
        },
    )
    assert r.status_code == 200, r.text
    old = f.current
    p = plan(c, rt, action="update")
    assert execute(c, p).status_code == 202
    op = c.get("/api/v1/operations/" + p["id"]).json()["data"]
    assert op["status"] == "completed", op
    assert f.current != old
    p = plan(
        c,
        rt,
        action="rollback",
        key="rollback-request-01",
        release_id=op["result"]["release_id"],
    )
    assert execute(c, p).status_code == 202
    assert (
        c.get("/api/v1/operations/" + p["id"]).json()["data"]["status"] == "completed"
    )
    assert f.current == old


def test_failure_locks_recovery_storage(managed, monkeypatch):
    c, rt, f = managed
    p = plan(c, rt)
    from control_plane import operations

    real = operations.run_operation
    monkeypatch.setattr("control_plane.management_api.run_operation", lambda _id: None)
    assert execute(c, p).status_code == 202
    second = plan(c, rt, key="parallel-request-01")
    assert execute(c, second).status_code == 409
    f.fail = True
    real(p["id"])
    assert c.get("/api/v1/operations/" + p["id"]).json()["data"]["status"] == "failed"
    f.fail = False
    assert execute(c, second).status_code == 202
    operations.recover_operations()
    assert (
        c.get("/api/v1/operations/" + second["id"]).json()["data"]["status"]
        == "interrupted"
    )
    s = c.post("/api/v1/docker/storage/cleanup/plan").json()["data"]
    assert (
        all(x["protected"] for x in s["volumes"])
        and f.current in s["protected_image_ids"]
    )
    assert len(s["cleanup_candidates"]) == 1 and not s["cleanup_execution_enabled"]


def test_cookie_csrf_and_redaction(managed):
    c, rt, f = managed
    from control_plane.config import get_settings
    from control_plane.caddy_protection import create_session_cookie

    get_settings().portal_roles = json.dumps(
        {"marco": {"role": "operator", "services": ["sample-app"]}}
    )
    c.cookies.set(
        get_settings().caddy_protection_cookie_name, create_session_cookie("marco")
    )
    c.headers.pop("Authorization")
    assert c.get("/api/v1/catalog").status_code == 200
    body = {
        "runtime_id": rt["id"],
        "action": "stop",
        "idempotency_key": "cookie-request-01",
    }
    assert (
        c.post("/api/v1/services/sample-app/operations/plan", json=body).status_code
        == 403
    )
    assert (
        c.post(
            "/api/v1/services/sample-app/operations/plan",
            json=body,
            headers={"Origin": "https://protected.marcosudau.com", "X-CP-CSRF": "1"},
        ).status_code
        == 200
    )
    assert (
        "hidden"
        not in c.get(
            "/api/v1/services/sample-app/runtime/logs", params={"runtime_id": rt["id"]}
        ).json()["data"]["text"]
    )
    assert c.get("/api/v1/docker/storage").status_code == 403


def test_unavailable_backend_preserves_catalog(managed):
    c, rt, f = managed
    f.fail = True
    assert c.get("/api/v1/catalog").status_code == 200
    s = c.get("/api/v1/services/sample-app/runtime/status").json()["data"][0]
    assert s["observed_state"] == "unavailable" and s["observed_at"]
    assert (
        c.post(
            "/api/v1/services/sample-app/operations/plan",
            json={
                "runtime_id": rt["id"],
                "action": "stop",
                "idempotency_key": "backend-failure-01",
            },
        ).status_code
        == 503
    )


def test_legacy_yaml_profile_summary_maps_to_existing_service(managed):
    c, rt, f = managed
    payload = {
        "profile_yaml": {
            "schema_version": 1,
            "summary": "Imported summary",
            "description": "Imported description",
        },
        "resolutions": {"summary": "profile_yaml"},
    }
    p = c.post("/api/v1/services/sample-app/metadata/plan", json=payload).json()["data"]
    assert not p["conflicts"] and not p["unmapped_profile_fields"]
    assert (
        c.post(
            "/api/v1/services/sample-app/metadata/import",
            json={**payload, "plan_hash": p["plan_hash"]},
        ).status_code
        == 200
    )
    contract = c.get("/api/v1/services/sample-app/contract").json()["data"]
    assert contract["service"]["summary"] == "Imported summary"
    export = c.get("/api/v1/services/sample-app/metadata/export?format=yaml")
    assert yaml.safe_load(export.text)["profile_yaml"]["summary"] == "Imported summary"


def test_registered_external_and_compose_builds(managed, monkeypatch):
    from control_plane.config import get_settings

    c, rt, f = managed
    from pathlib import Path

    path = Path(rt["path"])
    path.write_text("services:\n  app:\n    image: example/app:1\n    build: .\n")
    source = {
        "runtime_id": rt["id"],
        "compose_service": "app",
        "source_kind": "compose_build",
        "image_ref": "example/app:1",
    }
    assert (
        c.put(
            "/api/v1/services/sample-app/deployments/sources", json=source
        ).status_code
        == 200
    )
    p = plan(c, rt, action="build")
    assert execute(c, p).status_code == 202
    assert ["build", "app"] in f.calls
    cwd = Path(get_settings().outsourced_build_area_root) / "services/sample-app"
    cwd.mkdir(parents=True)
    get_settings().build_workflows = json.dumps(
        {"registered": {"argv": ["/usr/bin/true"], "cwd": str(cwd)}}
    )
    source.update(source_kind="external_build", workflow_id="registered")
    assert (
        c.put(
            "/api/v1/services/sample-app/deployments/sources", json=source
        ).status_code
        == 200
    )
    f.calls = []
    p = plan(c, rt, action="build", key="external-build-request")
    assert execute(c, p).status_code == 202
    op = c.get("/api/v1/operations/" + p["id"]).json()["data"]
    assert op["status"] == "completed", op
    assert not any(x[0] in {"build", "pull"} for x in f.calls)
    source["workflow_id"] = "shell;injection"
    assert (
        c.put(
            "/api/v1/services/sample-app/deployments/sources", json=source
        ).status_code
        == 422
    )


def test_mixed_stack_prepares_each_compose_service(managed, monkeypatch):
    c, rt, f = managed
    from pathlib import Path

    Path(rt["path"]).write_text(
        "services:\n  app:\n    image: example/app:1\n    build: .\n  worker:\n    image: example/worker:1\n"
    )
    original = f.containers

    def containers(project=None):
        app = original(project)[0]
        worker = {
            **app,
            "id": "container2",
            "name": "worker",
            "compose_service": "worker",
            "image_ref": "example/worker:1",
        }
        return [app, worker]

    monkeypatch.setattr(f, "containers", containers)
    for name, kind in [("app", "compose_build"), ("worker", "registry_image")]:
        assert (
            c.put(
                "/api/v1/services/sample-app/deployments/sources",
                json={
                    "runtime_id": rt["id"],
                    "compose_service": name,
                    "source_kind": kind,
                    "image_ref": f"example/{name}:1",
                },
            ).status_code
            == 200
        )
    p = plan(c, rt, action="update")
    assert execute(c, p).status_code == 202
    op = c.get("/api/v1/operations/" + p["id"]).json()["data"]
    assert op["status"] == "completed", op
    assert ["build", "app"] in f.calls and ["pull", "worker"] in f.calls


def test_cli_and_mcp_new_tools_use_the_api(managed, monkeypatch):
    c, rt, f = managed
    from control_plane import cli, mcp_server
    from typer.testing import CliRunner

    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"source": "api"}

    monkeypatch.setattr(cli, "request", request)
    r = CliRunner().invoke(cli.app, ["runtime", "status", "sample-app"])
    assert r.exit_code == 0, r.output
    assert calls[-1][1] == "/api/v1/services/sample-app/runtime/status"
    assert json.loads(mcp_server.tool_service_contract("sample-app"))["source"] == "api"
    assert (
        json.loads(
            mcp_server.tool_operation_plan(
                "sample-app", rt["id"], "stop", "mcp-request-001"
            )
        )["source"]
        == "api"
    )
    assert calls[-1][2]["action"] == "stop"


def test_queue_capacity_and_concurrent_profile_revision(managed, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from control_plane.config import get_settings

    c, rt, f = managed

    def put(_):
        return c.put(
            "/api/v1/services/sample-app/profile",
            json={"expected_revision": 0, "description": "Concurrent profile"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(put, [1, 2])) == [200, 412]
    get_settings().max_pending_operations = 1
    monkeypatch.setattr("control_plane.management_api.run_operation", lambda _id: None)
    p = plan(c, rt)
    assert execute(c, p).status_code == 202
    second = plan(c, rt, key="capacity-request-02")
    assert execute(c, second).status_code == 429


def test_extended_contract_rows_survive_snapshot_restore(managed):
    c, rt, f = managed
    c.put(
        "/api/v1/services/sample-app/profile",
        json={"expected_revision": 0, "description": "Stored profile"},
    )
    c.post("/api/v1/services/sample-app/aliases", json={"alias": "old-sample"})
    c.post("/api/v1/services", json={"slug": "dependency-app", "title": "Dependency"})
    c.post(
        "/api/v1/services/sample-app/dependencies",
        json={"target_slug": "dependency-app", "kind": "optional"},
    )
    from control_plane.db import SessionLocal
    from control_plane import models
    from control_plane.lifecycle.planner import db_inventory
    from control_plane.lifecycle.runner import restore_db_state

    with SessionLocal() as db:
        snapshot = db_inventory(db, "sample-app")
        db.query(models.ServiceProfile).delete()
        db.query(models.ServiceAlias).delete()
        db.query(models.Relation).delete()
        db.commit()
        assert restore_db_state(db, snapshot) == "sample-app"
        db.commit()
    restored = c.get("/api/v1/services/old-sample/contract").json()["data"]
    assert (
        restored["profile"]["description"] == "Stored profile" and restored["relations"]
    )


def test_reconcile_detects_unregistered_and_alias_runtime_drift_without_writes(managed):
    c, rt, f = managed
    from pathlib import Path
    from control_plane.config import get_settings

    c.post("/api/v1/services", json={"slug": "redis-canonical", "title": "Redis"})
    c.post("/api/v1/services/redis-canonical/aliases", json={"alias": "redis-stack"})
    for slug in ["opencode", "redis-stack"]:
        p = Path(get_settings().selfhost_root) / "stacks/services" / slug
        p.mkdir(parents=True)
        (p / "compose.yaml").write_text("services:\n  app:\n    image: example/app:1\n")
    before = c.get("/api/v1/catalog").json()["data"]["total"]
    result = c.get("/api/v1/registry/reconcile").json()["data"]
    assert result["applied"] is False
    assert any(
        r["code"] == "stack.unregistered" and r["slug"] == "opencode"
        for r in result["findings"]
    )
    assert any(
        r["code"] == "runtime.missing" and r["slug"] == "redis-stack"
        for r in result["findings"]
    )
    assert c.get("/api/v1/catalog").json()["data"]["total"] == before
