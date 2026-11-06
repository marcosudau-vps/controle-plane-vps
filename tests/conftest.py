import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["CP_DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["CP_API_TOKEN"] = "test-token"
    os.environ["CP_SELFHOST_ROOT"] = tempfile.mkdtemp(prefix="selfhost-root-")
    os.environ["CP_OUTSOURCED_BUILD_AREA_ROOT"] = tempfile.mkdtemp(prefix="build-area-root-")
    os.environ["CP_GENERATED_CADDY_DIR"] = tempfile.mkdtemp(prefix="caddy-")
    os.environ["CP_GENERATED_BACKSTAGE_DIR"] = tempfile.mkdtemp(prefix="backstage-")
    os.environ["CP_GENERATED_DOCS_DIR"] = tempfile.mkdtemp(prefix="docs-")
    os.environ["CP_LIFECYCLE_ARCHIVE_ROOT"] = tempfile.mkdtemp(prefix="lifecycle-archives-")
    os.environ["CP_LIFECYCLE_RUNTIME_APPLY_ENABLED"] = "false"
    os.environ["CP_CADDY_AUTO_CERT_ENABLED"] = "false"
    os.environ["CP_CADDY_PROTECTION_LOGINS"] = '{"marco":"test-pass","apiuser":"api-pass"}'
    os.environ["CP_CADDY_PROTECTION_API_KEYS"] = '["sk-test-one","sk-test-two"]'
    os.environ["CP_CADDY_PROTECTION_COOKIE_SECRET"] = "unit-test-cookie-secret"
    os.environ["CP_CADDY_PROTECTION_COOKIE_DOMAIN"] = ""

    from control_plane.config import get_settings
    from control_plane import db as db_module

    get_settings.cache_clear()
    db_module.engine.dispose()
    db_module.engine = db_module.create_control_engine(get_settings().database_url)
    db_module.SessionLocal.configure(bind=db_module.engine)

    from control_plane.api import app
    from control_plane.db import init_db

    init_db()
    with TestClient(app, base_url="https://protected.marcosudau.com", headers={"Authorization": "Bearer test-token"}) as test_client:
        yield test_client
