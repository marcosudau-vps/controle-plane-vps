"""Typed Caddy exceptions and ownership validation; override files remain untouched."""

import json
import re
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, field_validator
from . import models
from .config import get_settings
from .contracts import StrictInput, object_data
from .domains import render_domain_value
from .schemas import RouteCreate

HEADERS_UP = {"Host", "X-Forwarded-Host", "X-Forwarded-Proto"}
HEADERS_RESPONSE = {
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
    "Access-Control-Allow-Credentials",
    "Access-Control-Expose-Headers",
    "Access-Control-Max-Age",
    "Vary",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
}


class RouteOptionsInput(StrictInput):
    host_aliases: list[str] = Field(default_factory=list, max_length=30)
    upstream_headers: dict[str, str] = Field(default_factory=dict)
    response_headers: dict[str, str] = Field(default_factory=dict)
    tls_profile: Literal["default", "cloudflare_dns01"] = "default"
    owner_kind: Literal["generated", "manual_override"] = "generated"
    owner_ref: str = ""

    @field_validator("host_aliases")
    @classmethod
    def hosts(cls, values):
        return sorted({RouteCreate.validate_host(v) for v in values})

    @field_validator("upstream_headers", "response_headers")
    @classmethod
    def headers(cls, values, info):
        allowed = (
            HEADERS_UP if info.field_name == "upstream_headers" else HEADERS_RESPONSE
        )
        for key, value in values.items():
            if (
                key not in allowed
                or len(value) > 2000
                or any(ord(c) < 32 for c in value)
                or "\\" in value
            ):
                raise ValueError(
                    "header is not permitted or contains control characters"
                )
            if key == "Host" and not (
                value == "{host}" or re.fullmatch(r"[A-Za-z0-9.:-]+", value)
            ):
                raise ValueError("invalid upstream Host header")
        return values


def override_files():
    settings = get_settings()
    root = Path(settings.selfhost_root)
    dirs = (
        [Path(settings.caddy_override_dir)]
        if settings.caddy_override_dir
        else [root / "stacks/services/caddy/overrides", root / "infra/caddy/overrides"]
    )
    return sorted(
        {
            p
            for d in dirs
            for p in d.glob("*.caddy")
            if not p.name.startswith(".") and ".bak" not in p.name
        }
    )


def overlaps(a, b):
    a = render_domain_value(a).lower()
    b = render_domain_value(b).lower()
    if a == b:
        return True

    def covers(wild, host):
        return (
            wild.startswith("*.")
            and host.endswith(wild[1:])
            and len(host.split(".")) == len(wild.split("."))
        )

    return covers(a, b) or covers(b, a)


def route_hosts(db, route):
    opts = db.get(models.RouteOptions, route.id)
    return (
        [
            render_domain_value(route.host),
            *[render_domain_value(h) for h in opts.host_aliases],
        ]
        if opts
        else [render_domain_value(route.host)]
    )


def ownership_findings(db):
    from .validators import _caddy_hosts_from_file

    manual = {str(p.resolve()): _caddy_hosts_from_file(p) for p in override_files()}
    routes = db.query(models.Route).filter_by(status="active").all()
    findings = []
    for i, route in enumerate(routes):
        opts = db.get(models.RouteOptions, route.id)
        hosts = route_hosts(db, route)
        if opts and opts.owner_kind == "manual_override":
            if not opts.owner_ref or not set(hosts) <= manual.get(
                str(Path(opts.owner_ref).resolve()), set()
            ):
                findings.append(
                    {
                        "code": "route.override.missing",
                        "route_id": route.id,
                        "message": "declared manual route is absent from its registered override",
                    }
                )
            continue
        for host in hosts:
            for filename, owned in manual.items():
                if any(overlaps(host, h) for h in owned):
                    findings.append(
                        {
                            "code": "route.owner.conflict",
                            "route_id": route.id,
                            "message": f"generated host overlaps a manual override: {host}",
                        }
                    )
        for other in routes[i + 1 :]:
            if other.path != route.path:
                continue
            if any(overlaps(a, b) for a in hosts for b in route_hosts(db, other)):
                findings.append(
                    {
                        "code": "route.owner.conflict",
                        "route_id": route.id,
                        "message": "active route hosts overlap another route",
                    }
                )
    return findings


def options_for(db, route):
    row = db.get(models.RouteOptions, route.id)
    return (
        object_data(row)
        if row
        else {
            "route_id": route.id,
            "host_aliases": [],
            "upstream_headers": {},
            "response_headers": {},
            "tls_profile": "default",
            "owner_kind": "generated",
            "owner_ref": "",
        }
    )


def proxy_lines(route, opts, indent):
    if not opts["upstream_headers"]:
        return [f"{indent}reverse_proxy {route.upstream}"]
    return [
        f"{indent}reverse_proxy {route.upstream} {{",
        *[
            f"{indent}    header_up {k} {json.dumps(v)}"
            for k, v in sorted(opts["upstream_headers"].items())
        ],
        f"{indent}}}",
    ]


def render_path_site(db, routes, settings):
    """One host group with explicit host AND path matchers, ordered before the fallback."""
    from .caddy_protection import resolve_route_protection

    if len({r.tls for r in routes}) != 1:
        raise HTTPException(409, "TLS settings must agree for routes sharing a host")
    hosts = sorted({h for route in routes for h in route_hosts(db, route)})
    if not routes[0].tls:
        hosts = ["http://" + h for h in hosts]
    lines = [", ".join(hosts) + " {"]
    options = {r.id: options_for(db, r) for r in routes}
    if routes[0].tls and any(
        o["tls_profile"] == "cloudflare_dns01" for o in options.values()
    ):
        lines += [
            "    tls {",
            "        dns cloudflare {env.CLOUDFLARE_TOKEN_DNS_EDIT}",
            "    }",
        ]
    ordered = sorted(routes, key=lambda r: (r.path == "/", -len(r.path), r.path, r.id))
    for route in ordered:
        matcher = "route_" + route.id.replace("-", "")
        lines += [
            f"    @{matcher} {{",
            "        host " + " ".join(route_hosts(db, route)),
        ]
        if route.path != "/":
            lines.append("        path " + json.dumps(route.path + "*"))
        lines.append("    }")
    lines.append("    route {")
    if settings.caddy_protection_enabled and any(
        resolve_route_protection(db, r) for r in routes
    ):
        lines += [
            "        handle /caddy-schutz/* {",
            "            reverse_proxy 127.0.0.1:8765",
            "        }",
        ]
    for route in ordered:
        opts = options[route.id]
        matcher = "route_" + route.id.replace("-", "")
        lines.append(f"        handle @{matcher} {{")
        for key, value in sorted(opts["response_headers"].items()):
            lines.append(f"            header {key} {json.dumps(value)}")
        if settings.caddy_protection_enabled and resolve_route_protection(db, route):
            lines.append("            import caddy_schutz_forward_auth")
        lines += proxy_lines(route, opts, "            ")
        lines.append("        }")
    lines += ["    }", "}", ""]
    return lines
