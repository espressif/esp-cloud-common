# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Pure functions for building and merging S3 bucket policies for release access."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

PREFIXES_BY_ROLE: dict[str, tuple[str, ...]] = {
    "customer": ("releases/",),
    "dev": ("internal_releases/", "releases/"),
}

POLICY_VERSION = "2012-10-17"
SID_PREFIX = "ReleaseAccess"


def sid_for(role: str, account_id: str) -> str:
    return f"{SID_PREFIX}-{role}-{account_id}"


def _list_sid_for(role: str, account_id: str) -> str:
    return f"{sid_for(role, account_id)}-List"


def build_statements(bucket: str, account_id: str, role: str) -> list[dict[str, Any]]:
    """Return the [GetObject, ListBucket] statement pair for one grant."""
    if role not in PREFIXES_BY_ROLE:
        raise ValueError(f"unknown role: {role!r}")

    prefixes = PREFIXES_BY_ROLE[role]
    principal = {"AWS": f"arn:aws:iam::{account_id}:root"}

    get_stmt = {
        "Sid": sid_for(role, account_id),
        "Effect": "Allow",
        "Principal": principal,
        "Action": ["s3:GetObject", "s3:GetObjectVersion"],
        "Resource": [f"arn:aws:s3:::{bucket}/{p}*" for p in prefixes],
    }

    list_prefixes: list[str] = []
    for p in prefixes:
        list_prefixes.append(p)
        list_prefixes.append(f"{p}*")

    list_stmt = {
        "Sid": _list_sid_for(role, account_id),
        "Effect": "Allow",
        "Principal": principal,
        "Action": ["s3:ListBucket"],
        "Resource": f"arn:aws:s3:::{bucket}",
        "Condition": {"StringLike": {"s3:prefix": list_prefixes}},
    }

    return [get_stmt, list_stmt]


def _all_account_sids(account_id: str) -> set[str]:
    """Every Sid this tool might have created for a given account, across roles."""
    out: set[str] = set()
    for role in PREFIXES_BY_ROLE:
        out.add(sid_for(role, account_id))
        out.add(_list_sid_for(role, account_id))
    return out


def merge_grant(
    policy: Optional[dict[str, Any]],
    bucket: str,
    account_id: str,
    role: str,
) -> dict[str, Any]:
    """Return a new policy with this account's statements replaced.

    Strips any Sid this tool might have created for the account (any role,
    including the List variant), then appends the fresh pair.
    """
    if policy is None:
        base = {"Version": POLICY_VERSION, "Statement": []}
    else:
        base = deepcopy(policy)
        base.setdefault("Version", POLICY_VERSION)
        base.setdefault("Statement", [])

    sids_to_strip = _all_account_sids(account_id)
    base["Statement"] = [
        s for s in base["Statement"] if s.get("Sid") not in sids_to_strip
    ]
    base["Statement"].extend(build_statements(bucket, account_id, role))
    return base


def remove_grant(
    policy: Optional[dict[str, Any]],
    account_id: str,
) -> Optional[dict[str, Any]]:
    """Strip every Sid this tool created for ``account_id``.

    Returns ``None`` if the policy ends up with zero statements (caller should
    delete the bucket policy entirely).
    """
    if policy is None:
        return None

    sids_to_strip = _all_account_sids(account_id)
    new_stmts = [s for s in policy.get("Statement", []) if s.get("Sid") not in sids_to_strip]
    if not new_stmts:
        return None
    out = deepcopy(policy)
    out["Statement"] = new_stmts
    return out
