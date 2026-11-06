from sqlalchemy.orm import Session

from . import models


PORT_ALLOCATOR_100_START = 2000
PORT_ALLOCATOR_1000_START = 10000


def _existing_service_bases(db: Session) -> set[int]:
    rows = db.query(models.Service.port_base).filter(models.Service.port_base.isnot(None)).all()
    return {row[0] for row in rows}


def allocate_port_base(
    db: Session,
    large_port_space: bool = False,
    manual_port_base: int | None = None,
) -> int:
    if manual_port_base is not None:
        existing = _existing_service_bases(db)
        if manual_port_base in existing:
            raise ValueError(f"Port base {manual_port_base} is already in use")
        return manual_port_base

    existing = _existing_service_bases(db)
    block_size = 1000 if large_port_space else 100
    start = PORT_ALLOCATOR_1000_START if large_port_space else PORT_ALLOCATOR_100_START

    for base in range(start, start + 100000, block_size):
        if base not in existing:
            return base
    raise ValueError("No free port base found (all blocks exhausted)")
