"""DynamoDB read/write for release-access grants.

Schema:
    PK  project       (string)
    SK  account_id    (string)

Attrs: role, friendly_name, granted_at, granted_by, buckets (string set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key


class RoleConflict(Exception):
    """Raised when an upsert would change role without ``allow_role_change=True``."""


@dataclass
class Grant:
    project: str
    account_id: str
    role: str  # "dev" | "customer"
    friendly_name: str
    granted_by: str
    buckets: list[str] = field(default_factory=list)
    granted_at: Optional[str] = None


def _table(session: boto3.Session, table_name: str):
    return session.resource("dynamodb").Table(table_name)


def _to_grant(item: dict) -> Grant:
    return Grant(
        project=item["project"],
        account_id=item["account_id"],
        role=item["role"],
        friendly_name=item["friendly_name"],
        granted_by=item["granted_by"],
        granted_at=item.get("granted_at"),
        buckets=list(item.get("buckets", []) or []),
    )


def get_grant(session: boto3.Session, table_name: str,
              project: str, account_id: str) -> Optional[Grant]:
    resp = _table(session, table_name).get_item(
        Key={"project": project, "account_id": account_id}
    )
    item = resp.get("Item")
    return _to_grant(item) if item else None


def upsert_grant(session: boto3.Session, table_name: str, grant: Grant,
                 *, allow_role_change: bool) -> None:
    existing = get_grant(session, table_name, grant.project, grant.account_id)
    if existing and existing.role != grant.role and not allow_role_change:
        raise RoleConflict(
            f"grant for {grant.project}/{grant.account_id} already exists "
            f"with role={existing.role!r}; refusing to change to "
            f"{grant.role!r} without --update-role"
        )

    item = {
        "project": grant.project,
        "account_id": grant.account_id,
        "role": grant.role,
        "friendly_name": grant.friendly_name,
        "granted_by": grant.granted_by,
        "granted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "buckets": grant.buckets,
    }
    _table(session, table_name).put_item(Item=item)


def delete_grant(session: boto3.Session, table_name: str,
                 project: str, account_id: str) -> None:
    _table(session, table_name).delete_item(
        Key={"project": project, "account_id": account_id}
    )


def list_grants(session: boto3.Session, table_name: str,
                project: Optional[str]) -> list[Grant]:
    table = _table(session, table_name)
    if project is None:
        items: list[dict] = []
        scan_kwargs: dict = {}
        while True:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return [_to_grant(i) for i in items]
    items: list[dict] = []
    query_kwargs = {"KeyConditionExpression": Key("project").eq(project)}
    while True:
        resp = table.query(**query_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        query_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [_to_grant(i) for i in items]
