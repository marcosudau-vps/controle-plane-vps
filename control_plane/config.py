from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ENV_PREFIX = "CP_"
LEGACY_ENV_PREFIX = "SELFHOST" + "_CONTROL_"
DEFAULT_CONFIG_PATH = "/home/marco/selfhost/config/control-plane/config.yaml"

# Typ-Mapping für Env-Var-Konvertierung (String → Typ)
_ENV_TYPES: dict[str, type] = {
    "port_base": int,
    "bind_port": int,
    "caddy_auto_cert_max_new_zones_per_run": int,
    "caddy_auto_cert_max_total_zones_per_root": int,
    "caddy_reload_enabled": bool,
    "caddy_auto_cert_enabled": bool,
    "caddy_auto_cert_exclude_root_zone": bool,
    "caddy_protection_enabled": bool,
    "caddy_protection_cookie_enabled": bool,
    "caddy_protection_cookie_max_age_seconds": int,
    "large_port_space": bool,
    "lifecycle_runtime_apply_enabled": bool,
    "runtime_apply_enabled": bool,
    "operation_timeout_seconds": int,
    "minimum_available_memory_mib": int,
}


class Settings:
    database_url: str = "sqlite:///./control-plane-dev.db"
    db_schema: str = "control_plane"
    api_token: str | None = None
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    selfhost_root: str = "/home/marco/selfhost"
    generated_caddy_dir: str = "/home/marco/selfhost/data/services/control-plane/generated/caddy"
    generated_backstage_dir: str = "/home/marco/selfhost/data/services/backstage/catalog/generated"
    generated_docs_dir: str = "/home/marco/selfhost/data/services/control-plane/generated/docs"
    outsourced_build_area_root: str = "/home/marco/selfhost_outsourced/build_area"
    caddyfile_path: str = "/etc/caddy/Caddyfile"
    caddy_reload_enabled: bool = False
    caddy_apply_command: str = "/usr/local/sbin/control-plane-caddy-apply"
    caddy_auto_cert_enabled: bool = True
    caddy_auto_cert_command: str = "control_plane.auto_cert_zones.caddy_auto_cert_zones"
    caddy_auto_cert_env_file: str = "/home/marco/selfhost/secrets/caddy.env"
    caddy_auto_cert_state_file: str = "/home/marco/selfhost/data/services/control-plane/auto-cert-zones/managed_certificate_zones.json"
    caddy_auto_cert_generated_file: str = "/home/marco/selfhost/data/services/control-plane/generated/caddy/auto_cert_zones.caddy"
    caddy_auto_cert_max_new_zones_per_run: int = 5
    caddy_auto_cert_max_total_zones_per_root: int = 30
    caddy_auto_cert_exclude_root_zone: bool = False
    public_base_domain: str = "marcosudau.com"
    target_base_domain: str = "marcosudau.com"
    subdomains_ui_domain: str = "subdomains.marcosudau.com"
    services_api_domain: str = "services.marcosudau.com"
    namespace_placeholder_upstream: str = "http://127.0.0.1:8765"
    caddy_protection_enabled: bool = True
    caddy_protection_logins: str = ""
    caddy_protection_api_keys: str = ""
    caddy_protection_cookie_enabled: bool = True
    caddy_protection_cookie_name: str = "caddy_schutz_session"
    caddy_protection_cookie_secret: str = ""
    caddy_protection_cookie_max_age_seconds: int = 86400
    caddy_protection_cookie_domain: str = ""
    lifecycle_archive_root: str = "/home/marco/selfhost/backups/service-lifecycle"
    lifecycle_runtime_apply_enabled: bool = True
    runtime_apply_enabled: bool = False
    operation_timeout_seconds: int = 900
    minimum_available_memory_mib: int = 256
    operations_dir: str = ""
    # JSON configured by the administrator, never returned by the API.
    scoped_tokens: str = "{}"
    portal_roles: str = "{}"
    build_workflows: str = "{}"
    caddy_override_dir: str = ""

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        path_obj = Path(path)
        if not path_obj.exists():
            return cls()
        with path_obj.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})

    def apply_env(self) -> Settings:
        for key in dir(self):
            if key.startswith("_"):
                continue
            env_key = f"{ENV_PREFIX}{key.upper()}"
            legacy_env_key = f"{LEGACY_ENV_PREFIX}{key.upper()}"
            raw = os.environ.get(env_key)
            if raw is None:
                raw = os.environ.get(legacy_env_key)
            if raw is None:
                continue
            if raw == "" or raw == "null":
                setattr(self, key, None)
            elif _ENV_TYPES.get(key) is bool:
                setattr(self, key, raw.lower() in {"1", "true", "yes", "on"})
            elif _ENV_TYPES.get(key) is int:
                setattr(self, key, int(raw))
            else:
                setattr(self, key, raw)
        return self

    def copy(self) -> Settings:
        s = Settings()
        for key in dir(self):
            if not key.startswith("_"):
                setattr(s, key, getattr(self, key))
        return s


def _find_config_path() -> str:
    explicit = os.environ.get(f"{ENV_PREFIX}CONFIG_PATH")
    if explicit:
        return explicit
    return DEFAULT_CONFIG_PATH


@lru_cache
def get_settings() -> Settings:
    settings = Settings.from_yaml(_find_config_path())
    settings.apply_env()
    return settings
