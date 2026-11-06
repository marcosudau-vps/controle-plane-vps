from fastapi import Header, HTTPException, status

from .config import get_settings


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token")
