import sys
import os
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"C:\Users\marco\AppData\Local\Programs\Python\Python312\Lib\site-packages")

from control_plane.db import init_db, get_session
from control_plane.models import Service, SubService, Route
from control_plane.schemas import ServiceOut
from control_plane.config import get_settings
from control_plane.generators import generate_caddy, export_json
from control_plane.validators import persist_validation_run
from control_plane.caddy_protection import configured_api_keys, configured_logins, resolve_route_protection
from control_plane.port_allocator import allocate_port_base
from control_plane.subservice import build_service_tree, build_subservice_tree, delete_subservice_cascade, get_subservice_by_slug
from control_plane.service import get_service_by_slug
from control_plane.domains import render_domain_value
from control_plane import models


def _get_db():
    init_db()
    return next(get_session())


def _json(obj: Any) -> str:
    import json
    from datetime import datetime
    def ser(o: Any) -> str:
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=ser, indent=2, sort_keys=True)


# ============ Tool Implementations ============

def tool_health() -> str:
    return _json({"ok": True, "service": "control-plane"})


def tool_list_services() -> str:
    db = _get_db()
    svcs = db.query(Service).order_by(Service.slug).all()
    db.close()
    return _json([{"id": s.id, "slug": s.slug, "title": s.title, "lifecycle": s.lifecycle, "status": s.status} for s in svcs])


def tool_show_service(slug: str) -> str:
    db = _get_db()
    svc = db.query(Service).filter(Service.slug == slug).one_or_none()
    if not svc:
        db.close()
        return _json({"error": f"service not found: {slug}"})
    data = {c.name: getattr(svc, c.name) for c in svc.__table__.columns}
    data["routes"] = [
        {**{c.name: getattr(r, c.name) for c in r.__table__.columns}, "rendered_host": render_domain_value(r.host)}
        for r in svc.routes
    ]
    db.close()
    return _json(data)


def tool_show_service_tree(slug: str) -> str:
    db = _get_db()
    svc = db.query(Service).filter(Service.slug == slug).one_or_none()
    if not svc:
        db.close()
        return _json({"error": f"service not found: {slug}"})
    tree = build_service_tree(db, svc)
    db.close()
    return _json(tree)


def tool_list_routes() -> str:
    db = _get_db()
    routes = db.query(Route).order_by(Route.host, Route.path).all()
    items = []
    for r in routes:
        item = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        item["rendered_host"] = render_domain_value(r.host)
        if r.parent_type == "service" and r.service:
            item["parent_slug"] = r.service.slug
        elif r.parent_type == "subservice" and r.subservice:
            item["parent_slug"] = r.subservice.slug
        items.append(item)
    db.close()
    return _json(items)


def tool_validate() -> str:
    db = _get_db()
    run = persist_validation_run(db, "all", commit=True)
    results = [
        {"severity": r.severity, "code": r.code, "message": r.message}
        for r in run.results
    ]
    db.close()
    return _json({"status": run.status, "results": results})


def tool_generate_caddy() -> str:
    db = _get_db()
    result = generate_caddy(db)
    db.close()
    return _json(result)


def tool_deploy_plan() -> str:
    from control_plane.generators import generate_caddy as gen_caddy
    from control_plane.api import run_caddy_cert_zones_for_routes
    db = _get_db()
    try:
        validation_run = persist_validation_run(db, "caddy", commit=False)
        artifact = gen_caddy(db)
        cert_plans = []
        db.close()
        return _json({
            "validation_status": validation_run.status,
            "artifact": artifact,
            "apply_allowed": validation_run.status == "passed"
        })
    except Exception as e:
        db.close()
        return _json({"error": str(e)})


def tool_caddy_schutz_status() -> str:
    db = _get_db()
    routes = db.query(Route).order_by(Route.host, Route.path).all()
    data = {
        "configured_login_count": len(configured_logins()),
        "configured_api_key_count": len(configured_api_keys()),
        "routes": [
            {
                "id": route.id,
                "host": route.host,
                "rendered_host": render_domain_value(route.host),
                "configured": route.caddy_protection_enabled,
                "effective": resolve_route_protection(db, route),
            }
            for route in routes
        ],
    }
    db.close()
    return _json(data)


def tool_set_service_caddy_schutz(slug: str, enabled: bool) -> str:
    db = _get_db()
    svc = db.query(Service).filter(Service.slug == slug).one_or_none()
    if not svc:
        db.close()
        return _json({"error": f"service not found: {slug}"})
    svc.caddy_protection_enabled = enabled
    db.commit()
    data = {"slug": svc.slug, "caddy_protection_enabled": svc.caddy_protection_enabled}
    db.close()
    return _json(data)


def tool_set_route_caddy_schutz(route_id: str, enabled: bool | None = None) -> str:
    db = _get_db()
    route = db.query(Route).filter(Route.id == route_id).one_or_none()
    if not route:
        db.close()
        return _json({"error": f"route not found: {route_id}"})
    route.caddy_protection_enabled = enabled
    db.commit()
    data = {"id": route.id, "host": route.host, "configured": route.caddy_protection_enabled, "effective": resolve_route_protection(db, route)}
    db.close()
    return _json(data)


def tool_agent_context(slug: str) -> str:
    db = _get_db()
    svc = db.query(Service).filter(Service.slug == slug).one_or_none()
    if not svc:
        db.close()
        return _json({"error": f"service not found: {slug}"})
    from control_plane.contracts import service_contract
    from control_plane.policies import effective_rules
    ctx = {
        "contract": service_contract(db, svc),
        "policies": effective_rules(db, svc),
        "service": {c.name: getattr(svc, c.name) for c in svc.__table__.columns},
        "routes": [
            {**{c.name: getattr(r, c.name) for c in r.__table__.columns}, "rendered_host": render_domain_value(r.host)}
            for r in svc.routes
        ],
        "rules": [
            "Use control-plane or the Control Plane for changes.",
            "Do not edit generated Caddy files manually.",
            "Do not store secret values in docs, exports, or git.",
        ],
    }
    db.close()
    return _json(ctx)


def tool_service_contract(slug: str) -> str:
    from control_plane.cli import request
    return _json(request('GET', f'/api/v1/services/{slug}/contract'))


def tool_runtime_status(slug: str) -> str:
    from control_plane.cli import request
    return _json(request('GET', f'/api/v1/services/{slug}/runtime/status'))


def tool_operation_plan(slug: str, runtime_id: str, action: str, idempotency_key: str) -> str:
    from control_plane.cli import request
    return _json(request('POST', f'/api/v1/services/{slug}/operations/plan', {'runtime_id':runtime_id,'action':action,'idempotency_key':idempotency_key}))


def tool_operation_execute(operation_id: str, plan_hash: str, approved: bool = False) -> str:
    from control_plane.cli import request
    return _json(request('POST', f'/api/v1/operations/{operation_id}/execute', {'plan_hash':plan_hash,'approved':approved}))


# ============ MCP Server Setup ============

TOOL_MAP: dict[str, dict[str, Any]] = {
    "health": {
        "description": "System health check",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_health,
    },
    "list_services": {
        "description": "List all registered services",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_list_services,
    },
    "show_service": {
        "description": "Show service details including routes and subservices",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Service slug"}},
            "required": ["slug"],
        },
        "func": tool_show_service,
    },
    "service_tree": {
        "description": "Show the full hierarchical tree of a service",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Service slug"}},
            "required": ["slug"],
        },
        "func": tool_show_service_tree,
    },
    "list_routes": {
        "description": "List all registered routes (subdomains)",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_list_routes,
    },
    "validate": {
        "description": "Run full validation of all services, routes, subservices",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_validate,
    },
    "generate_caddy": {
        "description": "Generate Caddy configuration files",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_generate_caddy,
    },
    "deploy_plan": {
        "description": "Generate a deployment plan (dry run)",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_deploy_plan,
    },
    "agent_context": {
        "description": "Get agent context for a service (for AI assistants)",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Service slug"}},
            "required": ["slug"],
        },
        "func": tool_agent_context,
    },
    "caddy_schutz_status": {
        "description": "Show Caddy-Schutz configuration without exposing secrets",
        "input_schema": {"type": "object", "properties": {}},
        "func": tool_caddy_schutz_status,
    },
    "set_service_caddy_schutz": {
        "description": "Enable or disable Caddy-Schutz for a service",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["slug", "enabled"],
        },
        "func": tool_set_service_caddy_schutz,
    },
    "set_route_caddy_schutz": {
        "description": "Override Caddy-Schutz for a route; pass null to inherit",
        "input_schema": {
            "type": "object",
            "properties": {
                "route_id": {"type": "string"},
                "enabled": {"type": ["boolean", "null"]},
            },
            "required": ["route_id"],
        },
        "func": tool_set_route_caddy_schutz,
    },
}


TOOL_MAP.update({
    'service_contract': {'description':'Read the canonical technical contract through the API', 'input_schema':{'type':'object','properties':{'slug':{'type':'string'}},'required':['slug']},'func':tool_service_contract},
    'runtime_status': {'description':'Observe desired and live runtime states through the API', 'input_schema':{'type':'object','properties':{'slug':{'type':'string'}},'required':['slug']},'func':tool_runtime_status},
    'operation_plan': {'description':'Create a scoped, validated operation plan; no execution', 'input_schema':{'type':'object','properties':{k:{'type':'string'} for k in ['slug','runtime_id','action','idempotency_key']},'required':['slug','runtime_id','action','idempotency_key']},'func':tool_operation_plan},
    'operation_execute': {'description':'Execute an explicitly approved immutable plan', 'input_schema':{'type':'object','properties':{'operation_id':{'type':'string'},'plan_hash':{'type':'string'},'approved':{'type':'boolean'}},'required':['operation_id','plan_hash']},'func':tool_operation_execute},
})


def handle_mcp_request(request: dict) -> dict:
    method = request.get("method", "")
    params = request.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "control-plane", "version": "0.1.0"},
            },
        }
    
    if method == "tools/list":
        tools = []
        for name, spec in TOOL_MAP.items():
            tools.append({
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["input_schema"],
            })
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": tools}}
    
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        spec = TOOL_MAP.get(tool_name)
        if not spec:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }
        try:
            result_text = spec["func"](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [{"type": "text", "text": result_text}]
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32603, "message": str(exc)},
            }
    
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio():
    import sys as _sys
    for line in _sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            import json as _json
            request = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        response = handle_mcp_request(request)
        _sys.stdout.write(_json.dumps(response) + "\n")
        _sys.stdout.flush()


def run_sse(host: str = "127.0.0.1", port: int = 8766):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json as _json
    
    class MCPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                request = _json.loads(body)
            except _json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            response = handle_mcp_request(request)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_json.dumps(response).encode("utf-8"))
        
        def log_message(self, format, *args):
            pass
    
    server = HTTPServer((host, port), MCPHandler)
    print(f"MCP SSE server listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Control Plane MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="sse")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    
    init_db()
    
    if args.transport == "stdio":
        run_stdio()
    else:
        run_sse(args.host, args.port)
