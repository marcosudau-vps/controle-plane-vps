"""A small, explicitly named disposable Compose stack; no production container is targeted."""

import os
from pathlib import Path
import subprocess
import pytest


@pytest.mark.skipif(
    not os.environ.get("CP_LIVE_DOCKER_TESTS"),
    reason="enable only on an authorized local test Docker daemon",
)
def test_live_start_stop_autostart_and_identity(client):
    from control_plane.config import get_settings

    settings = get_settings()
    settings.runtime_apply_enabled = True
    slug = "live-sample"
    project = "ctpl-ap001-runtime-test"
    # Never adopt an existing project or container.
    prior = subprocess.check_output(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    ).strip()
    assert not prior, "test project already exists; refusing to adopt it"
    root = Path(settings.selfhost_root) / "stacks/services" / slug
    root.mkdir(parents=True)
    compose = root / "compose.yaml"
    compose.write_text(
        "services:\n  app:\n    image: postgres:16-alpine\n    entrypoint: ['/bin/sh','-c']\n    command: ['sleep 600']\n    network_mode: none\n    mem_limit: 32m\n    cpus: 0.1\n    restart: 'no'\n    healthcheck:\n      test: ['CMD','/bin/true']\n      interval: 1s\n"
    )
    base = ["docker", "compose", "-p", project, "-f", str(compose)]
    try:
        subprocess.run(
            [*base, "up", "-d", "--no-build", "--pull", "never"],
            check=True,
            capture_output=True,
        )
        from control_plane.runtime import backend
        backend.verify(project, ["app"], "running")
        c = client
        c.post("/api/v1/services", json={"slug": slug, "title": "Live test"})
        response = c.post(
            "/api/v1/runtimes",
            json={
                "service_slug": slug,
                "runtime_type": "docker-compose",
                "path": str(compose),
                "compose_project": project,
            },
        )
        assert response.status_code == 200
        rt = response.json()["data"]
        original_id = subprocess.check_output([*base, "ps", "-aq"]).strip()
        for i, action in enumerate(["stop", "start", "autostart"]):
            body = {
                "action": action,
                "runtime_id": rt["id"],
                "idempotency_key": f"live-test-request-{i}",
            }
            if action == "autostart":
                body["autostart_policy"] = "on_demand"
            p = c.post(f"/api/v1/services/{slug}/operations/plan", json=body)
            assert p.status_code == 200, p.text
            plan = p.json()["data"]
            assert not plan["plan"]["dependency_findings"]
            r = c.post(
                "/api/v1/operations/" + plan["id"] + "/execute",
                json={"plan_hash": plan["plan_hash"], "approved": True},
            )
            assert r.status_code == 202, r.text
            result = c.get("/api/v1/operations/" + plan["id"]).json()["data"]
            assert result["status"] == "completed", (
                result["action"],
                result["error"],
                result["events"],
            )
        assert subprocess.check_output([*base, "ps", "-aq"]).strip() == original_id
        status = c.get(f"/api/v1/services/{slug}/runtime/status").json()["data"][0]
        assert (
            status["observed_state"] == "running"
            and status["autostart_policy"] == "on_demand"
        )
    finally:
        subprocess.run([*base, "down", "--volumes"], check=True, capture_output=True)
