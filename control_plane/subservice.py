from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models


def get_subservice_by_slug(db: Session, slug: str) -> models.SubService:
    sub = db.query(models.SubService).filter(models.SubService.slug == slug).one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail=f"subservice not found: {slug}")
    return sub


def get_subservice_children(db: Session, parent_id: str) -> list[models.SubService]:
    return (
        db.query(models.SubService)
        .filter(models.SubService.parent_type == "subservice", models.SubService.parent_id == parent_id)
        .all()
    )


def get_subservice_routes(db: Session, subservice_id: str) -> list[models.Route]:
    return (
        db.query(models.Route)
        .filter(models.Route.parent_type == "subservice", models.Route.parent_id == subservice_id)
        .all()
    )


def _collect_descendants(db: Session, parent_id: str) -> list[models.SubService]:
    children = get_subservice_children(db, parent_id)
    result = []
    for child in children:
        result.extend(_collect_descendants(db, child.id))
        result.append(child)
    return result


def delete_subservice_cascade(db: Session, subservice: models.SubService) -> None:
    descendants = _collect_descendants(db, subservice.id)
    for desc in reversed(descendants):
        routes = get_subservice_routes(db, desc.id)
        for rt in routes:
            db.delete(rt)
        db.delete(desc)
    own_routes = get_subservice_routes(db, subservice.id)
    for rt in own_routes:
        db.delete(rt)
    db.delete(subservice)
    db.flush()


def build_subservice_tree(db: Session, subservice_id: str) -> dict:
    sub = db.query(models.SubService).filter(models.SubService.id == subservice_id).one()
    data = {
        "id": sub.id,
        "slug": sub.slug,
        "title": sub.title,
        "status": sub.status,
        "routes": [
            {"id": rt.id, "host": rt.host, "path": rt.path, "upstream": rt.upstream, "status": rt.status}
            for rt in get_subservice_routes(db, sub.id)
        ],
        "sub_services": [],
    }
    for child in get_subservice_children(db, sub.id):
        data["sub_services"].append(build_subservice_tree(db, child.id))
    return data


def build_service_tree(db: Session, service: models.Service) -> dict:
    data = {
        "id": service.id,
        "slug": service.slug,
        "title": service.title,
        "port_base": service.port_base,
        "large_port_space": service.large_port_space,
        "lifecycle": service.lifecycle,
        "system": service.system,
        "routes": [
            {"id": rt.id, "host": rt.host, "path": rt.path, "upstream": rt.upstream, "status": rt.status}
            for rt in service.routes
        ],
        "sub_services": [],
    }
    direct_subs = (
        db.query(models.SubService)
        .filter(models.SubService.parent_type == "service", models.SubService.parent_id == service.id)
        .all()
    )
    for child in direct_subs:
        data["sub_services"].append(build_subservice_tree(db, child.id))
    return data
