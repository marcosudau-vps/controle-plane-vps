import json
from pathlib import Path
import pytest
import yaml


class FakeDocker:
    def __init__(self):
        self.state = "running"
        self.policy = "unless-stopped"
        self.current = "sha256:" + 64 * "a"
        self.latest = self.current
        self.calls = []
        self.fail = False

    def containers(self, project=None):
        if self.fail:
            from control_plane.runtime import DockerUnavailable

            raise DockerUnavailable("unavailable")
        return [
            {
                "id": "container1",
                "name": "sample-app",
                "image_id": self.current,
                "image_ref": "example/app:1",
                "project": project or "sample-app",
                "compose_service": "app",
                "compose_file": self.compose_file,
                "state": self.state,
                "health": "healthy" if self.state == "running" else "none",
                "restart_count": 0,
                "restart_policy": self.policy,
            }
        ]

    def metrics(self, ids):
        return (
            [{"id": "container1", "cpu": "1.0%", "memory": "10MiB / 128MiB"}]
            if ids
            else []
        )

    def image(self, ref):
        return {
            "id": ref if ref.startswith("sha256:") else self.latest,
            "tags": [],
            "digests": [],
            "size": 10,
        }

    def compose(self, path, project, args, override=None):
        self.calls.append(args)
        if self.fail:
            from control_plane.runtime import DockerUnavailable

            raise DockerUnavailable("unavailable")
        if args[0] in {"start", "restart"}:
            self.state = "running"
        if args[0] == "stop":
            self.state = "exited"
        if args[0] in {"pull", "build"}:
            self.latest = "sha256:" + 64 * "b"
        if args[0] == "up":
            self.current = yaml.safe_load(override.read_text())["services"]["app"][
                "image"
            ]
            self.state = "running"
        if args[0] == "logs":
            return "password=hidden logs ready"
        return ""

    def verify(self, project, names, expected):
        assert self.state == expected
        return self.containers(project)

    def run(self, args, timeout=30):
        self.calls.append(args)
        if args[0] == "update":
            self.policy = args[1].split("=", 1)[1]
        return ""

    def json_lines(self, args):
        if args[0] == "system":
            return [{"Type": "Images", "Size": "100MB", "Reclaimable": "10MB"}]
        if args[0] == "volume":
            return [{"Name": "persistent-data"}]
        return [
            {
                "ID": self.current,
                "Tag": "1",
                "Repository": "example/app",
                "Size": "10MB",
            },
            {
                "ID": "sha256:" + 64 * "f",
                "Tag": "<none>",
                "Repository": "<none>",
                "Size": "10MB",
            },
        ]


@pytest.fixture
def managed(client, monkeypatch):
    from control_plane.config import get_settings
    from control_plane import runtime

    settings = get_settings()
    settings.runtime_apply_enabled = True
    settings.scoped_tokens = json.dumps(
        {
            "viewer-key": {
                "actor": "reader",
                "role": "viewer",
                "services": ["sample-app"],
            },
            "operator-key": {
                "actor": "operator",
                "role": "operator",
                "services": ["sample-app"],
            },
        }
    )
    settings.operations_dir = str(Path(settings.selfhost_root) / "operations")
    client.post("/api/v1/services", json={"slug": "sample-app", "title": "Sample App"})
    stack = Path(settings.selfhost_root) / "stacks/services/sample-app"
    stack.mkdir(parents=True)
    compose = stack / "compose.yaml"
    compose.write_text(
        "services:\n  app:\n    image: example/app:1\n    restart: unless-stopped\n"
    )
    rt = client.post(
        "/api/v1/runtimes",
        json={
            "service_slug": "sample-app",
            "runtime_type": "docker-compose",
            "path": str(compose),
            "compose_project": "sample-app",
        },
    ).json()["data"]
    fake = FakeDocker()
    fake.compose_file = str(compose)
    monkeypatch.setattr(runtime, "backend", fake)
    return client, rt, fake
