import uvicorn

from .api import app
from .config import get_settings


def run() -> None:
    settings = get_settings()
    uvicorn.run("control_plane.api:app", host=settings.bind_host, port=settings.bind_port)


__all__ = ["app", "run"]
