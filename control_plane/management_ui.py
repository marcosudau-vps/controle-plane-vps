from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from .access import principal

router = APIRouter()
STATIC = Path(__file__).with_name("static")


@router.get("/management", include_in_schema=False)
def management_page(request: Request):
    try:
        principal(request).check("read")
    except HTTPException as e:
        if e.status_code == 401:
            return RedirectResponse(
                "/caddy-schutz/login?next=/management", status_code=303
            )
        raise
    return FileResponse(
        STATIC / "management.html",
        headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "Cache-Control": "no-store",
        },
    )


@router.get("/management/assets/{name}", include_in_schema=False)
def management_asset(name: str):
    if name not in {"management.js", "management.css"}:
        raise HTTPException(404, "asset not found")
    return FileResponse(STATIC / name)
