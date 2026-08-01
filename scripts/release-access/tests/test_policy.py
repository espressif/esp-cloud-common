"""Tests for policy.py — pure bucket-policy statement logic."""

import json
import pytest

from release_access.policy import (
    PREFIXES_BY_ROLE,
    build_statements,
    merge_grant,
    remove_grant,
    sid_for,
)


def test_sid_is_deterministic_per_role_and_account():
    assert sid_for("customer", "123456789012") == "ReleaseAccess-customer-123456789012"
    assert sid_for("dev", "123456789012") == "ReleaseAccess-dev-123456789012"


def test_prefixes_by_role():
    assert PREFIXES_BY_ROLE["customer"] == ("releases/",)
    assert PREFIXES_BY_ROLE["dev"] == ("internal_releases/", "releases/")


def test_build_statements_customer():
    stmts = build_statements("my-bucket", "123456789012", "customer")

    # Two statements: GetObject on prefixes, ListBucket scoped via condition.
    assert len(stmts) == 2

    get_stmt = next(s for s in stmts if "s3:GetObject" in s["Action"])
    assert get_stmt["Sid"] == "ReleaseAccess-customer-123456789012"
    assert get_stmt["Effect"] == "Allow"
    assert get_stmt["Principal"] == {"AWS": "arn:aws:iam::123456789012:root"}
    assert sorted(get_stmt["Action"]) == ["s3:GetObject", "s3:GetObjectVersion"]
    assert get_stmt["Resource"] == ["arn:aws:s3:::my-bucket/releases/*"]

    list_stmt = next(s for s in stmts if "s3:ListBucket" in s["Action"])
    assert list_stmt["Sid"] == "ReleaseAccess-customer-123456789012-List"
    assert list_stmt["Resource"] == "arn:aws:s3:::my-bucket"
    assert list_stmt["Condition"] == {
        "StringLike": {"s3:prefix": ["releases/", "releases/*"]}
    }


def test_build_statements_dev_includes_internal_releases():
    stmts = build_statements("my-bucket", "123456789012", "dev")
    get_stmt = next(s for s in stmts if "s3:GetObject" in s["Action"])
    assert sorted(get_stmt["Resource"]) == [
        "arn:aws:s3:::my-bucket/internal_releases/*",
        "arn:aws:s3:::my-bucket/releases/*",
    ]
    list_stmt = next(s for s in stmts if "s3:ListBucket" in s["Action"])
    assert sorted(list_stmt["Condition"]["StringLike"]["s3:prefix"]) == [
        "internal_releases/", "internal_releases/*", "releases/", "releases/*",
    ]


def test_merge_grant_into_empty_policy():
    new_policy = merge_grant(None, "my-bucket", "123456789012", "customer")
    assert new_policy["Version"] == "2012-10-17"
    sids = {s["Sid"] for s in new_policy["Statement"]}
    assert sids == {
        "ReleaseAccess-customer-123456789012",
        "ReleaseAccess-customer-123456789012-List",
    }


def test_merge_grant_replaces_existing_same_role():
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ReleaseAccess-customer-123456789012", "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::other/releases/*"]},
            {"Sid": "ReleaseAccess-customer-123456789012-List", "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::other",
             "Condition": {"StringLike": {"s3:prefix": ["releases/"]}}},
            {"Sid": "ReleaseAccess-customer-999999999999", "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::999999999999:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::my-bucket/releases/*"]},
        ],
    }

    merged = merge_grant(existing, "my-bucket", "123456789012", "customer")

    sids = [s["Sid"] for s in merged["Statement"]]
    # Exactly one Get + one List for 123…012, plus the unrelated 999…999 row.
    assert sids.count("ReleaseAccess-customer-123456789012") == 1
    assert sids.count("ReleaseAccess-customer-123456789012-List") == 1
    assert "ReleaseAccess-customer-999999999999" in sids

    new_get = next(s for s in merged["Statement"]
                   if s["Sid"] == "ReleaseAccess-customer-123456789012")
    assert new_get["Resource"] == ["arn:aws:s3:::my-bucket/releases/*"]


def test_merge_grant_role_upgrade_removes_old_role_sids():
    """Upgrading customer→dev must drop the customer Sid for that account."""
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ReleaseAccess-customer-123456789012", "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::b/releases/*"]},
            {"Sid": "ReleaseAccess-customer-123456789012-List", "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::b",
             "Condition": {"StringLike": {"s3:prefix": ["releases/"]}}},
        ],
    }

    merged = merge_grant(existing, "b", "123456789012", "dev")
    sids = {s["Sid"] for s in merged["Statement"]}
    assert "ReleaseAccess-customer-123456789012" not in sids
    assert "ReleaseAccess-customer-123456789012-List" not in sids
    assert "ReleaseAccess-dev-123456789012" in sids
    assert "ReleaseAccess-dev-123456789012-List" in sids


def test_remove_grant_returns_none_when_emptied():
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ReleaseAccess-customer-123456789012",
             "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::b/releases/*"]},
            {"Sid": "ReleaseAccess-customer-123456789012-List",
             "Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::b",
             "Condition": {"StringLike": {"s3:prefix": ["releases/"]}}},
        ],
    }
    assert remove_grant(existing, "123456789012") is None


def test_remove_grant_keeps_other_statements():
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ReleaseAccess-customer-123456789012",
             "Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::b/releases/*"]},
            {"Sid": "ReleaseAccess-customer-999999999999",
             "Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::999999999999:root"},
             "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::b/releases/*"]},
        ],
    }
    remaining = remove_grant(existing, "123456789012")
    assert remaining is not None
    sids = {s["Sid"] for s in remaining["Statement"]}
    assert sids == {"ReleaseAccess-customer-999999999999"}
