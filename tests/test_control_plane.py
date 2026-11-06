from pathlib import Path


def test_service_flow_generators_and_validation(client):
    service = client.post(
        "/api/v1/services",
        json={
            "slug": "litellm",
            "title": "LiteLLM",
            "summary": "LLM gateway",
            "system": "services",
            "component_type": "service",
            "lifecycle": "development",
            "tags": ["ai", "gateway"],
        },
    )
    assert service.status_code == 200, service.text
    assert service.json()["data"]["slug"] == "litellm"

    route = client.post(
        "/api/v1/routes",
        json={"service_slug": "litellm", "host": "api.litellm.{base_domain}", "upstream": "http://127.0.0.1:4000"},
    )
    assert route.status_code == 200, route.text
    service_detail = client.get("/api/v1/services/litellm")
    hosts = {item["host"] for item in service_detail.json()["data"]["routes"]}
    assert "litellm.{base_domain}" in hosts

    runtime = client.post(
        "/api/v1/runtimes",
        json={"service_slug": "litellm", "runtime_type": "docker-compose", "path": "/home/marco/selfhost/stacks/services/litellm"},
    )
    assert runtime.status_code == 200, runtime.text

    doc = client.post(
        "/api/v1/docs",
        json={"service_slug": "litellm", "doc_type": "service", "path": "/home/marco/selfhost/docs/services/litellm/overview.md", "title": "LiteLLM Betrieb"},
    )
    assert doc.status_code == 200, doc.text

    healthcheck = client.post(
        "/api/v1/healthchecks",
        json={"service_slug": "litellm", "check_type": "http", "target": "http://127.0.0.1:1", "expected_status": 200, "timeout_seconds": 1},
    )
    assert healthcheck.status_code == 200, healthcheck.text

    validation = client.post("/api/v1/validate")
    assert validation.status_code == 200, validation.text
    assert validation.json()["status"] == "passed"

    generated = client.post("/api/v1/generate/all")
    assert generated.status_code == 200, generated.text
    data = generated.json()["data"]
    assert Path(data["caddy"]["path"]).read_text(encoding="utf-8").find("litellm.marcosudau.com") >= 0
    assert Path(data["caddy"]["path"]).read_text(encoding="utf-8").find("provisional") >= 0
    assert "backstage" not in data
    assert "docs" not in data


def test_duplicate_route_is_rejected(client):
    client.post("/api/v1/services", json={"slug": "main-site", "title": "Main Site"})
    first = client.post("/api/v1/routes", json={"service_slug": "main-site", "host": "main.{base_domain}", "upstream": "http://127.0.0.1:8080"})
    assert first.status_code == 200
    second = client.post("/api/v1/routes", json={"service_slug": "main-site", "host": "main.{base_domain}", "upstream": "http://127.0.0.1:8081"})
    assert second.status_code == 409


def test_auth_required(client):
    response = client.get("/api/v1/services", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_caddy_cert_zones_endpoint_can_be_disabled(client):
    response = client.post("/api/v1/caddy/cert-zones/plan", json={"domain": "api.admin.workspace.hermes.assistants.agents.service.marcosudau.com"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["skipped"] is True


def test_validation_fails_when_caddy_override_host_is_not_registered(client, monkeypatch, tmp_path):
    import control_plane.validators as validators

    override_dir = tmp_path / "infra" / "caddy" / "overrides"
    generated_dir = tmp_path / "generated" / "caddy"
    override_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    legacy_token = "{$" + "SELFHOST" + "_CONTROL_PUBLIC_BASE_DOMAIN}"
    (override_dir / "missing.caddy").write_text(
        f"missing.{legacy_token} {{\n    reverse_proxy 127.0.0.1:9999\n}}\n",
        encoding="utf-8",
    )

    settings = validators.get_settings()
    monkeypatch.setattr(settings, "selfhost_root", str(tmp_path))
    monkeypatch.setattr(settings, "generated_caddy_dir", str(generated_dir))

    response = client.post("/api/v1/validate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert any(item["code"] == "route.registry.missing" and "missing.marcosudau.com" in item["message"] for item in body["results"])


def test_subservice_crud(client):
    svc = client.post("/api/v1/services", json={"slug": "parent-svc", "title": "Parent"})
    assert svc.status_code == 200
    svc_id = svc.json()["data"]["id"]

    sub = client.post("/api/v1/subservices", json={
        "slug": "child-sub",
        "title": "Child SubService",
        "parent_type": "service",
        "parent_id": "parent-svc",
    })
    assert sub.status_code == 200, sub.text
    sub_data = sub.json()["data"]
    assert sub_data["slug"] == "child-sub"
    assert sub_data["parent_type"] == "service"

    listing = client.get("/api/v1/subservices")
    assert listing.status_code == 200
    slugs = [s["slug"] for s in listing.json()["data"]]
    assert "child-sub" in slugs


def test_route_at_subservice(client):
    svc = client.post("/api/v1/services", json={"slug": "rte-svc", "title": "Route Test"})
    assert svc.status_code == 200

    sub = client.post("/api/v1/subservices", json={
        "slug": "rte-sub",
        "title": "Route Sub",
        "parent_type": "service",
        "parent_id": "rte-svc",
    })
    assert sub.status_code == 200
    sub_id = sub.json()["data"]["id"]

    route = client.post("/api/v1/routes", json={
        "parent_type": "subservice",
        "parent_slug": "rte-sub",
        "host": "app.rte-sub.rte-svc.{base_domain}",
        "upstream": "http://localhost:8080",
    })
    assert route.status_code == 200, route.text
    rendered_host = route.json()["data"]["rendered_host"]
    assert "app.rte-sub.rte-svc.marcosudau.com" in rendered_host


def test_subservice_tree(client):
    svc = client.post("/api/v1/services", json={"slug": "tree-svc", "title": "Tree Test"})
    assert svc.status_code == 200

    client.post("/api/v1/subservices", json={
        "slug": "tree-sub",
        "title": "Tree Sub",
        "parent_type": "service",
        "parent_id": "tree-svc",
    })

    tree = client.get("/api/v1/services/tree-svc/tree")
    assert tree.status_code == 200, tree.text
    assert tree.json()["data"]["slug"] == "tree-svc"
    assert len(tree.json()["data"]["sub_services"]) == 1
    assert tree.json()["data"]["sub_services"][0]["slug"] == "tree-sub"


def test_valid_service_with_optional_fields_and_caddy_schutz_generation(client):
    service = client.post(
        "/api/v1/services",
        json={
            "slug": "secure-app",
            "title": "Secure App",
            "summary": "Protected application",
            "system": "services",
            "component_type": "website",
            "lifecycle": "production",
            "owner": "marco",
            "criticality": 2,
            "tags": [" Secure ", "Web", "secure"],
            "large_port_space": True,
            "metadata_json": {"tier": "internal", "team": "ops"},
            "caddy_protection_enabled": True,
        },
    )
    assert service.status_code == 200, service.text
    data = service.json()["data"]
    assert data["tags"] == ["secure", "web"]
    assert data["caddy_protection_enabled"] is True
    assert data["port_base"] >= 10000

    route = client.post(
        "/api/v1/routes",
        json={
            "service_slug": "secure-app",
            "host": "app.secure-app.{base_domain}",
            "upstream": "http://127.0.0.1:3100",
            "auth_policy": "public",
        },
    )
    assert route.status_code == 200, route.text
    assert route.json()["data"]["caddy_protection_enabled"] is None

    generated = client.post("/api/v1/generate/caddy")
    assert generated.status_code == 200, generated.text
    caddy = Path(generated.json()["data"]["path"]).read_text(encoding="utf-8")
    assert "forward_auth 127.0.0.1:8765" in caddy
    assert "handle /caddy-schutz/*" in caddy
    assert "reverse_proxy http://127.0.0.1:3100" in caddy


def test_caddy_schutz_api_key_login_cookie_and_route_override(client):
    assert client.get("/caddy-schutz/check").status_code == 401
    browser_login = client.get(
        "/caddy-schutz/check",
        headers={"Accept": "text/html", "X-Forwarded-Uri": "/docs"},
        follow_redirects=False,
    )
    assert browser_login.status_code == 303
    assert browser_login.headers["location"] == "/caddy-schutz/login?next=/docs"

    api_auth = client.get("/caddy-schutz/check", headers={"X-API-Key": "sk-test-one"})
    assert api_auth.status_code == 204
    assert api_auth.headers["X-Caddy-Schutz-Auth"] == "api_key"

    bad_login = client.post("/caddy-schutz/login", data={"username": "marco", "password": "wrong", "remember": "1"}, follow_redirects=False)
    assert bad_login.status_code == 401

    login = client.post(
        "/caddy-schutz/login",
        data={"username": "marco", "password": "test-pass", "remember": "1", "next": "/private"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "caddy_schutz_session=" in login.headers["set-cookie"]

    cookie_auth = client.get("/caddy-schutz/check")
    assert cookie_auth.status_code == 204
    assert cookie_auth.headers["X-Caddy-Schutz-Auth"] == "cookie"

    client.post("/api/v1/services", json={"slug": "override-app", "title": "Override", "caddy_protection_enabled": True})
    route = client.post(
        "/api/v1/routes",
        json={
            "service_slug": "override-app",
            "host": "app.override-app.{base_domain}",
            "upstream": "http://127.0.0.1:3200",
            "caddy_protection_enabled": False,
        },
    )
    assert route.status_code == 200, route.text
    route_id = route.json()["data"]["id"]
    status = client.get("/api/v1/caddy-schutz/status")
    assert status.status_code == 200
    route_status = next(item for item in status.json()["data"]["routes"] if item["id"] == route_id)
    assert route_status["configured"] is False
    assert route_status["effective"] is False


def test_invalid_inputs_are_rejected_without_internal_errors(client):
    client.post("/api/v1/services", json={"slug": "valid-parent", "title": "Valid Parent"})
    cases = [
        ("service bad slug", "post", "/api/v1/services", {"slug": "Bad_Slug", "title": "Bad"}),
        ("service bad criticality", "post", "/api/v1/services", {"slug": "bad-criticality", "title": "Bad", "criticality": 99}),
        ("missing service route", "post", "/api/v1/routes", {"service_slug": "missing", "host": "missing.{base_domain}", "upstream": "http://127.0.0.1:1"}),
        ("bad route path", "post", "/api/v1/routes", {"service_slug": "missing", "host": "missing.{base_domain}", "path": "no-slash", "upstream": "http://127.0.0.1:1"}),
        ("bad route upstream", "post", "/api/v1/routes", {"service_slug": "valid-parent", "host": "bad-upstream.{base_domain}", "upstream": "localhost:1"}),
        ("bad route auth policy", "post", "/api/v1/routes", {"service_slug": "valid-parent", "host": "bad-auth.{base_domain}", "upstream": "http://127.0.0.1:1", "auth_policy": "typo"}),
        ("bad parent type", "post", "/api/v1/subservices", {"slug": "child", "title": "Child", "parent_type": "typo", "parent_id": "none"}),
        ("bad runtime type", "post", "/api/v1/runtimes", {"service_slug": "valid-parent", "runtime_type": "dockercompoes"}),
        ("secret contains value", "post", "/api/v1/secret-refs", {"service_slug": "valid-parent", "name": "bad", "ref": "token=sk-test"}),
        ("missing caddy service", "patch", "/api/v1/caddy-schutz/services/missing", {"enabled": True}),
    ]
    for _name, method, path, body in cases:
        response = getattr(client, method)(path, json=body)
        assert 400 <= response.status_code < 500, (_name, response.status_code, response.text)


def test_rendered_duplicate_routes_are_rejected(client):
    client.post("/api/v1/services", json={"slug": "dup-render", "title": "Duplicate Render"})
    first = client.post(
        "/api/v1/routes",
        json={"service_slug": "dup-render", "host": "alias.dup-render.{base_domain}", "upstream": "http://127.0.0.1:3400"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/v1/routes",
        json={"service_slug": "dup-render", "host": "alias.dup-render.marcosudau.com", "upstream": "http://127.0.0.1:3401"},
    )
    assert second.status_code == 409


def test_subservice_route_host_builder_rejects_foreign_hierarchy(client):
    client.post("/api/v1/services", json={"slug": "parent-app", "title": "Parent"})
    client.post(
        "/api/v1/subservices",
        json={"slug": "workspace", "title": "Workspace", "parent_type": "service", "parent_id": "parent-app"},
    )

    short = client.post(
        "/api/v1/routes",
        json={"parent_type": "subservice", "parent_slug": "workspace", "host": "app", "upstream": "http://127.0.0.1:3300"},
    )
    assert short.status_code == 200, short.text
    assert short.json()["data"]["host"] == "app.workspace.parent-app.{base_domain}"

    full = client.post(
        "/api/v1/routes",
        json={
            "parent_type": "subservice",
            "parent_slug": "workspace",
            "host": "admin.workspace.parent-app.{base_domain}",
            "upstream": "http://127.0.0.1:3301",
        },
    )
    assert full.status_code == 200, full.text
    assert full.json()["data"]["host"] == "admin.workspace.parent-app.{base_domain}"

    foreign = client.post(
        "/api/v1/routes",
        json={
            "parent_type": "subservice",
            "parent_slug": "workspace",
            "host": "admin.other-parent.{base_domain}",
            "upstream": "http://127.0.0.1:3302",
        },
    )
    assert foreign.status_code == 400


def test_mcp_caddy_schutz_tools(client):
    from control_plane.mcp_server import handle_mcp_request

    client.post("/api/v1/services", json={"slug": "mcp-app", "title": "MCP App"})
    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "set_service_caddy_schutz", "arguments": {"slug": "mcp-app", "enabled": True}},
        }
    )
    assert "error" not in response
    assert '"caddy_protection_enabled": true' in response["result"]["content"][0]["text"]


def test_legacy_env_prefix_is_supported(monkeypatch):
    from control_plane.config import get_settings

    monkeypatch.delenv("CP_PUBLIC_BASE_DOMAIN", raising=False)
    monkeypatch.setenv("SELFHOST" + "_CONTROL_PUBLIC_BASE_DOMAIN", "legacy.example")
    get_settings.cache_clear()
    try:
        assert get_settings().public_base_domain == "legacy.example"
    finally:
        get_settings.cache_clear()


def test_namespace_route_is_protected_and_doc_path_uses_overview_convention(client, monkeypatch):
    import subprocess

    import control_plane.api as api_module

    monkeypatch.setattr(
        api_module,
        "run_caddy_validate",
        lambda: subprocess.CompletedProcess(args=["caddy"], returncode=0, stdout="ok", stderr=""),
    )

    service = client.post("/api/v1/services", json={"slug": "myservice", "title": "My Service"})
    assert service.status_code == 200, service.text
    detail = client.get("/api/v1/services/myservice").json()["data"]
    ns = [r for r in detail["routes"] if r["host"] == "myservice.{base_domain}"]
    assert len(ns) == 1
    assert ns[0]["upstream"] == "http://127.0.0.1:8765"
    assert ns[0]["auth_policy"] == "caddy_schutz"

    provision = client.post(
        "/api/v1/managed-services/provision",
        json={
            "slug": "provsrv",
            "title": "Prov Service",
            "subdomain": "provsrv",
            "upstream": "http://127.0.0.1:2050",
            "port": 2050,
            "healthcheck_target": "http://127.0.0.1:2050/health",
        },
    )
    assert provision.status_code == 200, provision.text
    data = provision.json()["data"]
    assert data["route"]["upstream"] == "http://127.0.0.1:2050"
    assert data["route"]["auth_policy"] == "public"
    assert data["doc_path"].endswith("/docs/services/provsrv/overview.provsrv.md")
