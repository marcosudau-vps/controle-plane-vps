"""Regression coverage for API-only port moves and service consolidation."""

import pytest


def create_service(client, slug):
    response = client.post("/api/v1/services", json={"slug": slug, "title": slug})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_move_port_and_upstream_keeps_route_protection_and_records_activity(client):
    create_service(client, "existing-service")
    route = client.post("/api/v1/routes", json={
        "service_slug": "existing-service", "host": "terminal.{base_domain}",
        "upstream": "http://127.0.0.1:8010", "auth_policy": "caddy_schutz",
        "caddy_protection_enabled": True,
    }).json()["data"]
    port = client.post("/api/v1/ports", json={
        "service_slug": "existing-service", "number": 8010,
    }).json()["data"]
    moved = client.patch(f"/api/v1/ports/{port['id']}", json={"number": 8050})
    assert moved.status_code == 200
    assert moved.json()["data"]["id"] == port["id"]
    assert moved.json()["data"]["number"] == 8050
    updated = client.patch(f"/api/v1/routes/{route['id']}", json={"upstream": "http://127.0.0.1:8050"})
    assert updated.status_code == 200
    data = updated.json()["data"]
    for key in ("id", "host", "path", "tls", "auth_policy", "caddy_protection_enabled", "service_id"):
        assert data[key] == route[key]
    assert data["upstream"] == "http://127.0.0.1:8050"
    generated = client.post("/api/v1/generate/caddy").json()["data"]
    from pathlib import Path
    content = Path(generated["path"]).read_text()
    assert "reverse_proxy http://127.0.0.1:8050" in content
    actions = {row["action"] for row in client.get("/api/v1/activity").json()["data"]}
    assert {"route.update", "port.update"} <= actions


def test_reassign_existing_route_and_port_to_new_service(client):
    old = create_service(client, "old-service")
    new = create_service(client, "new-service")
    detail = client.get("/api/v1/services/old-service").json()["data"]
    route = detail["routes"][0]
    port = client.post("/api/v1/ports", json={"service_slug": "old-service", "number": 8020}).json()["data"]
    response = client.patch(f"/api/v1/routes/{route['id']}", json={
        "service_slug": "new-service", "upstream": "https://pro.v2.example.com",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["service_id"] == data["parent_id"] == new["id"]
    assert data["service_id"] != old["id"]
    response = client.patch(f"/api/v1/ports/{port['id']}", json={"service_slug": "new-service"})
    assert response.status_code == 200
    assert response.json()["data"]["service_id"] == new["id"]
    assert client.get("/api/v1/services/old-service").json()["data"]["ports"] == []


def test_port_conflict_rolls_back_existing_record(client):
    create_service(client, "port-service")
    first = client.post("/api/v1/ports", json={"service_slug": "port-service", "number": 8010}).json()["data"]
    client.post("/api/v1/ports", json={"service_slug": "port-service", "number": 8011})
    assert client.patch(f"/api/v1/ports/{first['id']}", json={"number": 8011}).status_code == 409
    ports = client.get("/api/v1/services/port-service").json()["data"]["ports"]
    assert next(p for p in ports if p["id"] == first["id"])["number"] == 8010


@pytest.mark.parametrize("path,payload", [
    ("routes", {"upstream": "http://localhost:9000"}),
    ("ports", {"number": 9000}),
])
def test_update_auth_and_missing_record(client, path, payload):
    assert client.patch(f"/api/v1/{path}/missing", json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.patch(f"/api/v1/{path}/missing", json=payload).status_code == 404


@pytest.mark.parametrize("path,payload", [
    ("routes", {"upstream": "file:///etc/passwd"}),
    ("routes", {"upstream": None}),
    ("routes", {"auth_policy": "public"}),
    ("ports", {"number": 0}),
    ("ports", {"number": 65536}),
    ("ports", {"number": None}),
    ("ports", {"status": "invalid"}),
])
def test_update_rejects_invalid_fields(client, path, payload):
    assert client.patch(f"/api/v1/{path}/missing", json=payload).status_code == 422


def test_missing_owner_does_not_reassign_existing_port(client):
    service = create_service(client, "owner-service")
    port = client.post("/api/v1/ports", json={"service_slug": "owner-service", "number": 8050}).json()["data"]
    response = client.patch(f"/api/v1/ports/{port['id']}", json={"service_slug": "missing-service"})
    assert response.status_code == 404
    assert client.get("/api/v1/services/owner-service").json()["data"]["ports"][0]["service_id"] == service["id"]
