from uuid import uuid4
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from .redaction import clean


def install(app):
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        codes = {
            400: "BAD_REQUEST",
            401: "UNAUTHENTICATED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            409: "STATE_CONFLICT",
            412: "STALE_PLAN",
            422: "VALIDATION_FAILED",
            429: "CAPACITY_LIMIT",
            503: "BACKEND_UNAVAILABLE",
        }
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "detail": clean(exc.detail),
                "error": {
                    "code": codes.get(exc.status_code, "REQUEST_FAILED"),
                    "request_id": getattr(request.state, "request_id", None),
                },
            },
        )

    from sqlalchemy.exc import SQLAlchemyError

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request, _exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "database unavailable or registry transaction failed"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        # Pydantic's default error includes the rejected input, including secret-like values.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]}
                    for e in exc.errors()
                ]
            },
        )

    @app.middleware("http")
    async def request_security(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        } and response.status_code in {401, 403, 409, 412, 422}:
            from .db import SessionLocal
            from .service import log_activity

            with SessionLocal() as db:
                route = request.scope.get("route")
                log_activity(
                    db,
                    "request.denied",
                    detail={
                        "request_id": request_id,
                        "handler": getattr(route, "name", "unknown"),
                        "status": response.status_code,
                    },
                    actor=getattr(request.state, "actor", "unauthenticated"),
                )
                db.commit()
        return response
