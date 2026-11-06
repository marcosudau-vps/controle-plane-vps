from pathlib import Path
import pytest
from test_management import plan, execute


def test_current_override_path_and_wildcard_ownership(client):
    from control_plane.config import get_settings

    root = Path(get_settings().selfhost_root)
    d = root / "stacks/services/caddy/overrides"
    d.mkdir(parents=True)
    (d / "manual.caddy").write_text(
        "*.sample-app.marcosudau.com {\n reverse_proxy 127.0.0.1:8080\n}\n"
    )
    client.post("/api/v1/services", json={"slug": "sample-app", "title": "Sample App"})
    client.post(
        "/api/v1/routes",
        json={
            "service_slug": "sample-app",
            "host": "ui.sample-app.{base_domain}",
            "upstream": "http://127.0.0.1:8080",
        },
    )
    result = client.post("/api/v1/validate").json()
    assert result["status"] == "failed"
    assert any(x["code"] == "route.owner.conflict" for x in result["results"])
    assert client.post("/api/v1/generate/caddy").status_code == 409


def test_typed_headers_tls_wildcard_and_manual_owner(client, tmp_path):
    from control_plane.config import get_settings

    client.post("/api/v1/services", json={"slug": "sample-app", "title": "Sample App"})
    route = client.get("/api/v1/services/sample-app").json()["data"]["routes"][0]
    settings = {
        "host_aliases": ["*.sample-app.{base_domain}"],
        "upstream_headers": {"Host": "127.0.0.1:9119"},
        "response_headers": {
            "Access-Control-Allow-Origin": "https://mail.example.test"
        },
        "tls_profile": "cloudflare_dns01",
    }
    r = client.put("/api/v1/routes/" + route["id"] + "/options", json=settings)
    assert r.status_code == 200, r.text
    generated = client.post("/api/v1/generate/caddy")
    assert generated.status_code == 200, generated.text
    text = Path(generated.json()["data"]["path"]).read_text()
    assert 'header_up Host "127.0.0.1:9119"' in text
    assert "dns cloudflare {env.CLOUDFLARE_TOKEN_DNS_EDIT}" in text
    assert "*.sample-app.marcosudau.com" in text
    assert "import caddy_schutz_forward_auth" in text
    settings["upstream_headers"]["Host"] = "good\n} respond hacked"
    assert (
        client.put(
            "/api/v1/routes/" + route["id"] + "/options", json=settings
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/routes",
            json={
                "service_slug": "sample-app",
                "host": "other.example.test",
                "upstream": "http://127.0.0.1:80\n} respond hacked",
            },
        ).status_code
        == 422
    )
    root = Path(get_settings().selfhost_root)
    d = root / "stacks/services/caddy/overrides"
    d.mkdir(parents=True)
    p = d / "sample.caddy"
    p.write_text("sample-app.marcosudau.com {\n reverse_proxy 127.0.0.1:8080\n}\n")
    opts = {"owner_kind": "manual_override", "owner_ref": str(p)}
    assert (
        client.put("/api/v1/routes/" + route["id"] + "/options", json=opts).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/v1/routes/" + route["id"], json={"upstream": "http://127.0.0.1:8080"}
        ).status_code
        == 200
    )
    assert (
        client.put("/api/v1/routes/" + route["id"] + "/options", json=opts).status_code
        == 200
    )
    text = Path(
        client.post("/api/v1/generate/caddy").json()["data"]["path"]
    ).read_text()
    assert "\nsample-app.marcosudau.com {" not in text


def test_symlink_other_service_privileged_config(managed, tmp_path):
    c, rt, f = managed
    original = Path(rt["path"])
    outside = tmp_path / "escape.yaml"
    outside.write_text(original.read_text())
    original.unlink()
    original.symlink_to(outside)
    assert (
        c.post(
            "/api/v1/services/sample-app/operations/plan",
            json={
                "runtime_id": rt["id"],
                "action": "stop",
                "idempotency_key": "symlink-request-01",
            },
        ).status_code
        == 422
    )
    original.unlink()
    original.write_text(
        "services:\n  app:\n    image: example/app:1\n    privileged: true\n"
    )
    assert (
        c.post(
            "/api/v1/services/sample-app/operations/plan",
            json={
                "runtime_id": rt["id"],
                "action": "stop",
                "idempotency_key": "privileged-request-01",
            },
        ).status_code
        == 422
    )


def test_dependency_cycle_and_live_stop_guard(managed):
    c, rt, f = managed
    c.post("/api/v1/services", json={"slug": "dependent-app", "title": "Dependent App"})
    assert (
        c.post(
            "/api/v1/services/dependent-app/dependencies",
            json={"target_slug": "sample-app"},
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/api/v1/services/sample-app/dependencies",
            json={"target_slug": "dependent-app"},
        ).status_code
        == 409
    )
    from control_plane.config import get_settings

    stack = Path(get_settings().selfhost_root) / "stacks/services/dependent-app"
    stack.mkdir(parents=True)
    p = stack / "compose.yaml"
    p.write_text("services:\n  app:\n    image: example/app:1\n")
    c.post(
        "/api/v1/runtimes",
        json={
            "service_slug": "dependent-app",
            "runtime_type": "docker-compose",
            "path": str(p),
            "compose_project": "dependent-app",
        },
    )
    p = plan(c, rt)
    assert any("dependent service" in s for s in p["plan"]["dependency_findings"])
    assert execute(c, p).status_code == 409


def test_no_signing_fallback_or_open_admin_api(managed):
    c, rt, f = managed
    from control_plane.config import get_settings
    from control_plane.caddy_protection import (
        create_session_cookie,
        verify_session_cookie,
    )

    settings = get_settings()
    settings.api_token = None
    settings.caddy_protection_cookie_secret = ""
    assert c.get("/api/v1/services").status_code == 503
    with pytest.raises(ValueError):
        create_session_cookie("marco")
    assert not verify_session_cookie("payload.signature").authenticated
    assert (
        c.get(
            "/api/v1/catalog", headers={"Authorization": "Bearer viewer-key"}
        ).status_code
        == 200
    )


def test_ui_auth_assets_no_credentials(managed):
    c, rt, f = managed
    r = c.get("/management")
    assert (
        r.status_code == 200
        and "script-src 'self'" in r.headers["content-security-policy"]
    )
    assert "test-token" not in r.text and "Service-Katalog" in r.text
    js = c.get("/management/assets/management.js")
    assert js.status_code == 200 and "innerHTML" not in js.text
    assert c.get("/management/assets/not-found").status_code == 404
    assert (
        c.get(
            "/management",
            headers={"Authorization": "Bearer wrong"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert c.get("/subdomains").status_code == 200
    assert c.get("/api/v1/catalog").headers["x-request-id"]


def test_autostart_and_configuration_stale(managed):
    c, rt, f = managed
    p = plan(c, rt, action="autostart", autostart_policy="on_demand")
    assert execute(c, p).status_code == 202
    assert f.policy == "no"
    p = plan(c, rt, key="changed-compose-request")
    Path(rt["path"]).write_text(
        Path(rt["path"]).read_text() + "\n# changed after approval\n"
    )
    # Byte changes, including comments, must invalidate an approved configuration.
    assert execute(c, p).status_code == 412


def test_canonical_name_race_and_scoped_read(managed):
    c, rt, f = managed
    c.post("/api/v1/services", json={"slug": "outside-app", "title": "Outside App"})
    assert (
        c.get(
            "/api/v1/services/outside-app/contract",
            headers={"Authorization": "Bearer viewer-key"},
        ).status_code
        == 403
    )
    rows = c.get(
        "/api/v1/catalog", headers={"Authorization": "Bearer viewer-key"}
    ).json()["data"]["items"]
    assert [x["slug"] for x in rows] == ["sample-app"]
    c.post("/api/v1/services/sample-app/aliases", json={"alias": "legacy-name"})
    assert (
        c.post(
            "/api/v1/services/sample-app/aliases", json={"alias": "legacy-name"}
        ).status_code
        == 409
    )


def test_legacy_archive_integrity_and_traversal(client):
    from test_lifecycle import write_service_manifest, current_selfhost_root

    root = current_selfhost_root(client)
    write_service_manifest(root, "integrity-svc")
    client.post(
        "/api/v1/services", json={"slug": "integrity-svc", "title": "Integrity Service"}
    )
    plan = client.post("/api/v1/lifecycle/services/integrity-svc/plan-snapshot").json()[
        "data"
    ]
    snap = client.post(
        "/api/v1/lifecycle/services/integrity-svc/execute-snapshot",
        json={"plan_hash": plan["plan_hash"]},
    )
    assert snap.status_code == 200, snap.text
    d = Path(snap.json()["data"]["archive_dir"])
    (next((d / "payload").rglob("state.txt"))).write_text("tampered")
    assert (
        client.post(
            "/api/v1/lifecycle/archives/inspect", json={"archive_dir": str(d)}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/lifecycle/archives/inspect", json={"archive_dir": "/etc"}
        ).status_code
        == 422
    )
    manifest = write_service_manifest(root, "boundary-svc")
    manifest["paths"]["data_dir"] = str(root)
    import yaml

    (root / "stacks/services/boundary-svc/service.yaml").write_text(
        yaml.safe_dump(manifest)
    )
    from control_plane.lifecycle.manifests import load_manifest, ManifestError

    with pytest.raises(ManifestError):
        load_manifest("boundary-svc")


def test_cert_zone_derivation_is_deterministic_and_validates_domains():
    from control_plane.auto_cert_zones.caddy_auto_cert_zones import (
        derive_certificate_zones,
        validate_domain,
        render_caddyfile_from_state,
    )

    zones = derive_certificate_zones("api.admin.example.test", "example.test")
    assert "example.test" in zones and "admin.example.test" in zones
    state = {"roots": {"example.test": {"zones": zones}}}
    assert render_caddyfile_from_state(state) == render_caddyfile_from_state(state)
    with pytest.raises(Exception):
        validate_domain("bad domain\nrespond hacked")


@pytest.mark.skipif(
    not __import__("os").environ.get("CP_TEST_CADDY_BINARY"),
    reason="requires isolated Caddy with Cloudflare plugin",
)
def test_real_caddy_accepts_typed_routing(client, tmp_path):
    import os, subprocess

    client.post(
        "/api/v1/services", json={"slug": "typed-caddy", "title": "Typed Caddy"}
    )
    route = client.get("/api/v1/services/typed-caddy").json()["data"]["routes"][0]
    result = client.put(
        "/api/v1/routes/" + route["id"] + "/options",
        json={
            "host_aliases": ["*.typed-caddy.{base_domain}"],
            "upstream_headers": {"Host": "127.0.0.1:9119"},
            "response_headers": {
                "Access-Control-Allow-Origin": "https://mail.example.test"
            },
            "tls_profile": "cloudflare_dns01",
        },
    )
    assert result.status_code == 200, result.text
    generated = client.post("/api/v1/generate/caddy").json()["data"]["path"]
    config = tmp_path / "Caddyfile"
    config.write_text("{\n admin off\n}\nimport " + generated + "\n")
    result = subprocess.run(
        [
            os.environ["CP_TEST_CADDY_BINARY"],
            "validate",
            "--config",
            str(config),
            "--adapter",
            "caddyfile",
        ],
        env={**os.environ, "CLOUDFLARE_TOKEN_DNS_EDIT": "x" * 40},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_database_failure_is_sanitized_and_core_delete_is_blocked(managed):
    from control_plane.api import app
    from control_plane.db import get_session
    from sqlalchemy.exc import OperationalError

    c, rt, f = managed
    c.post("/api/v1/services", json={"slug": "caddy", "title": "Core proxy"})
    assert c.delete("/api/v1/services/caddy").status_code == 403
    assert c.delete("/api/v1/services/sample-app").status_code == 409

    def unavailable():
        raise OperationalError(
            "SQL", {}, Exception("password=synthetic-sensitive-value")
        )
        yield

    app.dependency_overrides[get_session] = unavailable
    try:
        r = c.get("/api/v1/catalog")
        assert r.status_code == 503
        assert "synthetic-sensitive-value" not in r.text
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_caddy_apply_stages_complete_config_and_preserves_active_file(
    client, monkeypatch, tmp_path
):
    import subprocess
    import control_plane.api as api
    from control_plane.config import get_settings

    settings = get_settings()
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("import " + settings.generated_caddy_dir + "/*.caddy\n")
    settings.caddyfile_path = str(caddyfile)
    settings.caddy_auto_cert_state_file = str(tmp_path / "state.json")
    settings.caddy_auto_cert_generated_file = str(
        Path(settings.generated_caddy_dir) / "auto_cert_zones.caddy"
    )
    live = Path(settings.generated_caddy_dir) / "routes.caddy"
    live.write_text("# original active configuration\n")
    client.post(
        "/api/v1/services", json={"slug": "staged-caddy", "title": "Staged Caddy"}
    )

    def fail(candidate=None):
        assert live.read_text() == "# original active configuration\n"
        assert "staging/routes.caddy" in Path(candidate).read_text()
        return subprocess.CompletedProcess([], 1, "", "synthetic failure")

    monkeypatch.setattr(api, "run_caddy_validate", fail)
    p = client.post("/api/v1/deploy/caddy/plan").json()["data"]
    assert p["apply_allowed"]
    assert live.read_text() == "# original active configuration\n"
    r = client.post("/api/v1/deploy/caddy/apply", params={"plan_hash": p["plan_hash"]})
    assert r.status_code == 409
    assert live.read_text() == "# original active configuration\n"
    monkeypatch.setattr(
        api,
        "run_caddy_validate",
        lambda candidate=None: subprocess.CompletedProcess([], 0, "", ""),
    )
    client.patch("/api/v1/services/staged-caddy", json={"title": "Changed"})
    # Caddy plans depend on routing/configuration, rather than unrelated profile text.
    r = client.post("/api/v1/deploy/caddy/apply", params={"plan_hash": p["plan_hash"]})
    assert r.status_code == 200, r.text
    assert "staged-caddy.marcosudau.com" in live.read_text()
    route = client.get("/api/v1/services/staged-caddy").json()["data"]["routes"][0]
    client.patch(
        "/api/v1/routes/" + route["id"], json={"upstream": "http://127.0.0.1:1234"}
    )
    assert (
        client.post(
            "/api/v1/deploy/caddy/apply", params={"plan_hash": p["plan_hash"]}
        ).status_code
        == 412
    )


def test_secret_fields_and_helper_output_do_not_leak(managed):
    from control_plane.redaction import command_text

    c, rt, f = managed
    r = c.post(
        "/api/v1/services",
        json={
            "slug": "secret-sample",
            "title": "Secret sample",
            "metadata_json": {"secret": "synthetic-sensitive-value"},
        },
    )
    assert r.status_code == 422 and "synthetic-sensitive-value" not in r.text
    text = command_text(
        "failure for synthetic-key-value and synthetic-password-value",
        {
            "CLOUDFLARE_TOKEN_DNS_EDIT": "synthetic-key-value",
            "CP_CADDY_PROTECTION_LOGINS": '{"user":"synthetic-password-value"}',
        },
    )
    assert "synthetic-key-value" not in text and "synthetic-password-value" not in text
    assert "secret_refs" in c.get("/api/v1/services/sample-app/contract").json()["data"]


def test_existing_container_ownership_and_host_mounts_are_enforced(managed):
    c, rt, f = managed
    f.compose_file = "/other/registered/compose.yaml"
    p = plan(c, rt)
    assert "different Compose definition" in " ".join(p["plan"]["dependency_findings"])
    assert execute(c, p).status_code == 409
    Path(rt["path"]).write_text(
        'services:\n  app:\n    image: example/app:1\n    volumes: ["/etc:/host:ro"]\n'
    )
    r = c.post(
        "/api/v1/services/sample-app/operations/plan",
        json={
            "runtime_id": rt["id"],
            "action": "deploy",
            "idempotency_key": "host-mount-request",
        },
    )
    assert r.status_code == 422


def test_functional_healthcheck_failure_prevents_operation_success(
    managed, monkeypatch
):
    c, rt, f = managed
    p = plan(c, rt, action="restart")
    monkeypatch.setattr(
        "control_plane.lifecycle.runner.run_healthchecks_for_service",
        lambda *_: [{"id": "functional-check", "passed": False, "check_type": "http"}],
    )
    assert execute(c, p).status_code == 202
    result = c.get("/api/v1/operations/" + p["id"]).json()["data"]
    assert result["status"] == "failed" and "healthcheck" in result["error"]


def test_combined_provision_failure_rolls_back_registry_and_files(
    client, monkeypatch, tmp_path
):
    import subprocess
    import control_plane.api as api
    from control_plane.config import get_settings

    settings = get_settings()
    routefile = Path(settings.generated_caddy_dir) / "routes.caddy"
    routefile.write_text("# unchanged active routes\n")
    state = tmp_path / "disabled-state.json"
    state.write_text("disabled module canary")
    settings.caddy_auto_cert_state_file = str(state)
    before = state.stat().st_mtime_ns
    monkeypatch.setattr(
        api,
        "run_caddy_validate",
        lambda: subprocess.CompletedProcess([], 1, "", "synthetic failure"),
    )
    r = client.post(
        "/api/v1/managed-services/provision",
        json={
            "slug": "failed-service",
            "title": "Failed Service",
            "subdomain": "failed-service",
            "upstream": "http://127.0.0.1:2090",
        },
    )
    assert r.status_code == 409
    assert client.get("/api/v1/services/failed-service").status_code == 404
    assert routefile.read_text() == "# unchanged active routes\n"
    assert not (
        Path(settings.selfhost_root)
        / "docs/services/failed-service/overview.failed-service.md"
    ).exists()
    assert state.stat().st_mtime_ns == before


def test_actual_cp_domain_variable_in_current_overrides(client):
    from control_plane.config import get_settings

    root = Path(get_settings().selfhost_root) / "stacks/services/caddy/overrides"
    root.mkdir(parents=True)
    (root / "current-domain.caddy").write_text(
        "missing.{$CP_PUBLIC_BASE_DOMAIN} {\n reverse_proxy 127.0.0.1:9999\n}\n"
    )
    response = client.post("/api/v1/validate").json()
    assert response["status"] == "failed"
    assert any(
        r["code"] == "route.registry.missing"
        and "missing.marcosudau.com" in r["message"]
        for r in response["results"]
    )


def test_path_routes_require_their_host_and_keep_root_fallback(client, tmp_path):
    import os, json, subprocess

    client.post(
        "/api/v1/services", json={"slug": "path-sample", "title": "Path sample"}
    )
    for path, port in [("/api", 9001), ("/", 9002)]:
        r = client.post(
            "/api/v1/routes",
            json={
                "service_slug": "path-sample",
                "host": "scoped.example.test",
                "path": path,
                "upstream": f"http://127.0.0.1:{port}",
            },
        )
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/generate/caddy")
    assert r.status_code == 200, r.text
    generated = Path(r.json()["data"]["path"])
    text = generated.read_text()
    assert "scoped.example.test /api* {" not in text
    assert "host scoped.example.test" in text and 'path "/api*"' in text
    binary = os.environ.get("CP_TEST_CADDY_BINARY")
    if binary:
        result = subprocess.run(
            [binary, "adapt", "--config", str(generated), "--adapter", "caddyfile"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        adapted = json.loads(result.stdout)
        found = False
        for server in adapted["apps"]["http"]["servers"].values():
            for route in server.get("routes", []):
                for match in route.get("match", []):
                    assert "path" not in match, (
                        "a top-level path-only alternative would match foreign hosts"
                    )
                    if "scoped.example.test" in match.get("host", []):
                        found = True
        assert found
