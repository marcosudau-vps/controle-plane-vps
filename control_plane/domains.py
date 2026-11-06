from sqlalchemy.orm import Session

from .config import get_settings
from . import models


BASE_DOMAIN_TOKEN = "{base_domain}"


def render_domain_value(value: str) -> str:
    return value.replace(BASE_DOMAIN_TOKEN, get_settings().public_base_domain)


def host_template_for_subdomain(subdomain: str) -> str:
    clean = subdomain.strip().strip(".")
    if not clean:
        return BASE_DOMAIN_TOKEN
    if clean.endswith(BASE_DOMAIN_TOKEN):
        return clean
    if "." in clean and BASE_DOMAIN_TOKEN not in clean:
        return clean
    return f"{clean}.{BASE_DOMAIN_TOKEN}"


def is_domain_template(value: str) -> bool:
    return BASE_DOMAIN_TOKEN in value


def build_subservice_host_prefix(db: Session, subservice_id: str) -> str:
    labels: list[str] = []
    current_id = subservice_id
    visited: set[str] = set()
    for _ in range(50):
        if current_id in visited:
            break
        visited.add(current_id)
        sub = db.query(models.SubService).filter(models.SubService.id == current_id).one()
        labels.append(sub.slug)
        if sub.parent_type == "service":
            svc = db.query(models.Service).filter(models.Service.id == sub.parent_id).one()
            labels.append(svc.slug)
            break
        elif sub.parent_type == "subservice":
            current_id = sub.parent_id
        else:
            break
    return ".".join(labels)


def build_subservice_route_host(raw_host: str, prefix: str) -> str:
    clean = raw_host.strip().strip(".")
    if not clean or clean == BASE_DOMAIN_TOKEN:
        return f"{prefix}.{BASE_DOMAIN_TOKEN}"
    base_suffix = f".{BASE_DOMAIN_TOKEN}"
    if clean.endswith(base_suffix):
        local = clean[: -len(base_suffix)].strip(".")
    else:
        local = clean
    if local == prefix or local.endswith(f".{prefix}"):
        return f"{local}.{BASE_DOMAIN_TOKEN}"
    if "." in local:
        raise ValueError("subservice route host must be a single label or a full host under the subservice prefix")
    return f"{local}.{prefix}.{BASE_DOMAIN_TOKEN}"
