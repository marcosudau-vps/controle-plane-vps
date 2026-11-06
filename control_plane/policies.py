from typing import Literal
from pydantic import Field
from . import models
from .contracts import StrictInput, object_data

ACTIONS = {
    "start",
    "stop",
    "restart",
    "autostart",
    "pull",
    "build",
    "deploy",
    "update",
    "rollback",
}
BASE_RULES = [
    {
        "rule_id": "registered-runtime",
        "version": 1,
        "severity": "block",
        "actions": sorted(ACTIONS),
        "message": "Only registered Compose paths and projects may execute.",
    },
    {
        "rule_id": "core-protection",
        "version": 1,
        "severity": "block",
        "actions": ["stop", "restart", "autostart", "deploy", "update", "rollback"],
        "message": "Core services and database runtimes are protected.",
    },
    {
        "rule_id": "no-implicit-build-pull",
        "version": 1,
        "severity": "block",
        "actions": ["start"],
        "message": "Start preserves containers and never builds or pulls images.",
    },
    {
        "rule_id": "secret-references-only",
        "version": 1,
        "severity": "block",
        "actions": sorted(ACTIONS),
        "message": "Keep secret values outside contracts, logs and source control.",
    },
]


class RuleInput(StrictInput):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    version: int = Field(ge=1)
    service_slug: str | None = None
    severity: Literal["block", "requires_approval", "warning", "info"]
    actions: list[
        Literal[
            "start",
            "stop",
            "restart",
            "autostart",
            "pull",
            "build",
            "deploy",
            "update",
            "rollback",
        ]
    ] = Field(min_length=1)
    message: str = Field(min_length=3, max_length=1000)


def effective_rules(db, service):
    query = db.query(models.PolicyRule).filter(
        (models.PolicyRule.service_id == service.id)
        | models.PolicyRule.service_id.is_(None)
    )
    latest = {}
    for row in query:
        scope = (row.service_id, row.rule_id)
        if scope not in latest or row.version > latest[scope].version:
            latest[scope] = row
    return BASE_RULES + [
        object_data(r)
        for r in sorted(latest.values(), key=lambda r: (r.rule_id, r.version))
    ]


def rule_findings(db, service, action):
    return [
        r
        for r in effective_rules(db, service)
        if action in r["actions"]
        and r["rule_id"] not in {x["rule_id"] for x in BASE_RULES}
    ]
