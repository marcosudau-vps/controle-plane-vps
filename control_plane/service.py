from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models


def log_activity(
    db: Session,
    action: str,
    entity_kind: str = "",
    entity_id: str = "",
    detail: dict[str, Any] | None = None,
    actor: str = "system",
) -> None:
    db.add(
        models.ActivityLog(
            action=action,
            entity_kind=entity_kind,
            entity_id=entity_id,
            detail=detail or {},
            actor=actor,
        )
    )


def commit_or_409(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"constraint violation: {exc.orig}") from exc


def flush_or_409(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"constraint violation: {exc.orig}") from exc


def get_service_by_slug(db: Session, slug: str) -> models.Service:
    service = db.query(models.Service).filter(models.Service.slug == slug).one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail=f"service not found: {slug}")
    return service
