"""Tests for registry.py — DynamoDB grant CRUD."""

import boto3
import pytest
from moto import mock_aws

from release_access.bootstrap import ensure_table
from release_access.registry import (
    Grant,
    RoleConflict,
    delete_grant,
    get_grant,
    list_grants,
    upsert_grant,
)


TABLE = "release-access-grants"


def _session():
    return boto3.Session(region_name="us-east-1")


@mock_aws
def test_upsert_creates_new_grant():
    session = _session()
    ensure_table(session, TABLE)

    g = Grant(
        project="p1", account_id="123456789012", role="customer",
        friendly_name="Acme", granted_by="arn:aws:iam::000000000000:user/me",
        buckets=["arn:aws:s3:::bucket-a"],
    )
    upsert_grant(session, TABLE, g, allow_role_change=False)

    fetched = get_grant(session, TABLE, "p1", "123456789012")
    assert fetched is not None
    assert fetched.role == "customer"
    assert fetched.friendly_name == "Acme"
    assert fetched.buckets == ["arn:aws:s3:::bucket-a"]
    assert fetched.granted_at  # set by upsert


@mock_aws
def test_upsert_same_role_updates_friendly_name():
    session = _session()
    ensure_table(session, TABLE)

    g = Grant(project="p1", account_id="123456789012", role="customer",
              friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g, allow_role_change=False)

    g2 = Grant(project="p1", account_id="123456789012", role="customer",
               friendly_name="Acme Corp", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g2, allow_role_change=False)

    fetched = get_grant(session, TABLE, "p1", "123456789012")
    assert fetched.friendly_name == "Acme Corp"
    assert fetched.role == "customer"


@mock_aws
def test_upsert_role_change_without_flag_raises():
    session = _session()
    ensure_table(session, TABLE)

    g = Grant(project="p1", account_id="123456789012", role="customer",
              friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g, allow_role_change=False)

    g2 = Grant(project="p1", account_id="123456789012", role="dev",
               friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    with pytest.raises(RoleConflict) as exc:
        upsert_grant(session, TABLE, g2, allow_role_change=False)
    assert "customer" in str(exc.value) and "dev" in str(exc.value)


@mock_aws
def test_upsert_role_change_with_flag_succeeds():
    session = _session()
    ensure_table(session, TABLE)

    g = Grant(project="p1", account_id="123456789012", role="customer",
              friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g, allow_role_change=False)

    g2 = Grant(project="p1", account_id="123456789012", role="dev",
               friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g2, allow_role_change=True)

    fetched = get_grant(session, TABLE, "p1", "123456789012")
    assert fetched.role == "dev"


@mock_aws
def test_delete_grant_removes_row():
    session = _session()
    ensure_table(session, TABLE)
    g = Grant(project="p1", account_id="123456789012", role="customer",
              friendly_name="Acme", granted_by="me", buckets=["arn:aws:s3:::b"])
    upsert_grant(session, TABLE, g, allow_role_change=False)
    delete_grant(session, TABLE, "p1", "123456789012")
    assert get_grant(session, TABLE, "p1", "123456789012") is None


@mock_aws
def test_list_grants_filters_by_project():
    session = _session()
    ensure_table(session, TABLE)
    for project, account in [("p1", "111111111111"), ("p1", "222222222222"), ("p2", "333333333333")]:
        upsert_grant(
            session, TABLE,
            Grant(project=project, account_id=account, role="customer",
                  friendly_name="x", granted_by="me", buckets=[]),
            allow_role_change=False,
        )

    all_rows = list_grants(session, TABLE, project=None)
    assert {(g.project, g.account_id) for g in all_rows} == {
        ("p1", "111111111111"), ("p1", "222222222222"), ("p2", "333333333333"),
    }

    p1_rows = list_grants(session, TABLE, project="p1")
    assert {g.account_id for g in p1_rows} == {"111111111111", "222222222222"}


@mock_aws
def test_list_grants_paginates_query_for_project_filter(monkeypatch):
    """Force a small page size so we exercise the pagination loop."""
    session = _session()
    ensure_table(session, TABLE)
    for i in range(5):
        upsert_grant(
            session, TABLE,
            Grant(project="p1", account_id=f"{i:012d}", role="customer",
                  friendly_name="x", granted_by="me", buckets=[]),
            allow_role_change=False,
        )

    # Patch the table's query to force a page size of 2 so pagination must run.
    from release_access import registry
    real_resource = boto3.Session.resource

    class _PaginatedTable:
        def __init__(self, inner):
            self._inner = inner
        def __getattr__(self, name):
            return getattr(self._inner, name)
        def query(self, **kwargs):
            kwargs["Limit"] = 2
            return self._inner.query(**kwargs)

    real_table = registry._table

    def patched_table(sess, name):
        return _PaginatedTable(real_table(sess, name))

    monkeypatch.setattr(registry, "_table", patched_table)

    rows = registry.list_grants(session, TABLE, project="p1")
    assert len(rows) == 5
    assert {r.account_id for r in rows} == {f"{i:012d}" for i in range(5)}
