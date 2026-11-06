"""Scoped access alongside the existing administrator bearer token."""

from dataclasses import dataclass
import hmac
import json

from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyCookie
from .config import get_settings
from .caddy_protection import authenticate_request

ROLE_SCOPES = {
    "viewer": {"read"},
    "operator": {"read", "runtime"},
    "deployer": {"read", "runtime", "deploy"},
    "maintainer": {"read", "runtime", "deploy", "configure"},
    "administrator": {"read", "runtime", "deploy", "configure", "policy"},
}


@dataclass(frozen=True)
class Principal:
    actor: str
    role: str
    services: tuple[str, ...] = ("*",)

    def check(self, scope: str, slug: str | None = None):
        if scope not in ROLE_SCOPES.get(self.role, set()) or (
            slug is not None and "*" not in self.services and slug not in self.services
        ):
            raise HTTPException(403, "permission denied")


def principal(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False, scheme_name="ScopedBearer")
    ),
    session: str | None = Depends(
        APIKeyCookie(
            name="caddy_schutz_session", auto_error=False, scheme_name="PortalSession"
        )
    ),
) -> Principal:
    settings = get_settings()
    auth = request.headers.get("authorization", "")
    if settings.api_token and hmac.compare_digest(auth, f"Bearer {settings.api_token}"):
        request.state.actor = "legacy-admin"
        return Principal("legacy-admin", "administrator")
    try:
        tokens = json.loads(settings.scoped_tokens)
        for token, item in tokens.items():
            if hmac.compare_digest(auth, f"Bearer {token}"):
                p = Principal(
                    item["actor"], item["role"], tuple(item.get("services", []))
                )
                if p.role not in ROLE_SCOPES:
                    break
                request.state.actor = p.actor
                return p
        result = authenticate_request(request)
        if result.authenticated and result.method == "cookie" and result.username:
            item = json.loads(settings.portal_roles).get(result.username)
            if item:
                p = Principal(
                    result.username, item["role"], tuple(item.get("services", []))
                )
                if p.role not in ROLE_SCOPES:
                    raise HTTPException(403, "unconfigured role")
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    origin = str(request.base_url).rstrip("/")
                    if (
                        request.headers.get("origin") != origin
                        or request.headers.get("x-cp-csrf") != "1"
                    ):
                        raise HTTPException(403, "same-origin CSRF check failed")
                request.state.actor = p.actor
                return p
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "invalid access configuration") from None
    raise HTTPException(401, "invalid or missing credentials")
