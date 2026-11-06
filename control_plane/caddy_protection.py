from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Iterable

from fastapi import Request
from sqlalchemy.orm import Session

from . import models
from .config import get_settings


COOKIE_VERSION = "v1"


@dataclass(frozen=True)
class AuthResult:
    authenticated: bool
    method: str | None = None
    username: str | None = None


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def configured_api_keys() -> list[str]:
    raw = (get_settings().caddy_protection_api_keys or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise ValueError("CP_CADDY_PROTECTION_API_KEYS must be a JSON string list or comma-separated string")
        return [item.strip() for item in data if item.strip()]
    return _split_csv(raw)


def configured_logins() -> dict[str, str]:
    raw = (get_settings().caddy_protection_logins or "").strip()
    if not raw:
        return {}
    if raw.startswith("[") or raw.startswith("{"):
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            result: dict[str, str] = {}
            for item in data:
                if isinstance(item, dict) and "username" in item and "password" in item:
                    result[str(item["username"])] = str(item["password"])
                else:
                    raise ValueError("login list entries must contain username and password")
            return result
        raise ValueError("CP_CADDY_PROTECTION_LOGINS must be JSON object/list or comma-separated user:pass pairs")
    result: dict[str, str] = {}
    for item in _split_csv(raw):
        if ":" not in item:
            raise ValueError("login entries must use user:password")
        username, password = item.split(":", 1)
        username = username.strip()
        if username:
            result[username] = password
    return result


def _constant_time_any(candidate: str, allowed: Iterable[str]) -> bool:
    return any(hmac.compare_digest(candidate, value) for value in allowed)


def verify_api_key(value: str | None) -> bool:
    if not value:
        return False
    return _constant_time_any(value.strip(), configured_api_keys())


def verify_login(username: str, password: str) -> bool:
    stored = configured_logins().get(username)
    return stored is not None and hmac.compare_digest(password, stored)


def _cookie_secret() -> str:
    settings = get_settings()
    secret = settings.caddy_protection_cookie_secret or settings.api_token
    if not secret:
        # Development fallback only; production validation warns when cookie auth is enabled without a stable secret.
        secret = "control-plane-development-cookie-secret"
    return secret


def _sign(payload: str) -> str:
    return hmac.new(_cookie_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_cookie(username: str) -> str:
    settings = get_settings()
    payload = {
        "v": COOKIE_VERSION,
        "u": username,
        "exp": int(time.time()) + settings.caddy_protection_cookie_max_age_seconds,
    }
    payload_text = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return f"{payload_text}.{_sign(payload_text)}"


def verify_session_cookie(value: str | None) -> AuthResult:
    if not value or "." not in value:
        return AuthResult(False)
    payload_text, signature = value.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload_text)):
        return AuthResult(False)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_text.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return AuthResult(False)
    if payload.get("v") != COOKIE_VERSION:
        return AuthResult(False)
    if int(payload.get("exp", 0)) < int(time.time()):
        return AuthResult(False)
    username = str(payload.get("u", ""))
    if not username:
        return AuthResult(False)
    return AuthResult(True, "cookie", username)


def cookie_domain() -> str | None:
    settings = get_settings()
    configured = (settings.caddy_protection_cookie_domain or "").strip()
    if configured:
        return configured
    base = settings.public_base_domain.strip()
    return f".{base}" if base and "." in base else None


def authenticate_request(request: Request) -> AuthResult:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        if verify_api_key(authorization[7:].strip()):
            return AuthResult(True, "api_key")
    api_key = request.headers.get("x-api-key")
    if verify_api_key(api_key):
        return AuthResult(True, "api_key")
    if authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:].strip()).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            username = password = ""
        if username and verify_login(username, password):
            return AuthResult(True, "basic", username)
    if get_settings().caddy_protection_cookie_enabled:
        cookie = request.cookies.get(get_settings().caddy_protection_cookie_name)
        result = verify_session_cookie(cookie)
        if result.authenticated:
            return result
    return AuthResult(False)


def resolve_subservice_protection(db: Session, subservice: models.SubService) -> bool:
    if subservice.caddy_protection_enabled is not None:
        return bool(subservice.caddy_protection_enabled)
    if subservice.parent_type == "service":
        service = db.query(models.Service).filter(models.Service.id == subservice.parent_id).one_or_none()
        return bool(service.caddy_protection_enabled) if service else False
    if subservice.parent_type == "subservice":
        parent = db.query(models.SubService).filter(models.SubService.id == subservice.parent_id).one_or_none()
        return resolve_subservice_protection(db, parent) if parent else False
    return False


def resolve_route_protection(db: Session, route: models.Route) -> bool:
    if route.auth_policy == "caddy_schutz":
        return True
    if route.caddy_protection_enabled is not None:
        return bool(route.caddy_protection_enabled)
    if route.parent_type == "subservice" and route.subservice:
        return resolve_subservice_protection(db, route.subservice)
    if route.service:
        return bool(route.service.caddy_protection_enabled)
    return False
