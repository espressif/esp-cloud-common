# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for cli.py — dry-run paths and revoke-missing-grant behaviour."""

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from release_access.bootstrap import ensure_table
from release_access.cli import main


TABLE = "release-access-grants"


def _setup_bucket(session, bucket="ra-test-bucket", project="ra-test"):
    s3 = session.client("s3")
    s3.create_bucket(Bucket=bucket)
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [
        {"Key": "Project", "Value": project},
        {"Key": "Purpose", "Value": "release-artifacts"},
    ]})


@mock_aws
def test_grant_dry_run_does_not_call_sts_or_mutate(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, TABLE)
    _setup_bucket(session)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--region", "us-east-1", "--dry-run",
        "grant", "--products", "ra-test", "--account-id", "123456789012",
        "--role", "customer", "--friendly-name", "Acme",
    ])

    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    # No bucket policy should have been written.
    s3 = session.client("s3")
    from botocore.exceptions import ClientError
    with pytest.raises(ClientError) as exc:
        s3.get_bucket_policy(Bucket="ra-test-bucket")
    assert exc.value.response["Error"]["Code"] == "NoSuchBucketPolicy"
    # No DynamoDB row should exist.
    table = session.resource("dynamodb").Table(TABLE)
    assert table.get_item(Key={"project": "ra-test", "account_id": "123456789012"}).get("Item") is None


@mock_aws
def test_grant_multiple_products_records_a_row_per_product(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, TABLE)
    _setup_bucket(session, bucket="ra-kb-bucket", project="product-a")
    _setup_bucket(session, bucket="ra-pa-bucket", project="product-b")

    runner = CliRunner()
    result = runner.invoke(main, [
        "--region", "us-east-1",
        "grant", "--products", "product-a,product-b",
        "--account-id", "123456789012",
        "--role", "customer", "--friendly-name", "Acme",
    ])

    assert result.exit_code == 0, result.output
    table = session.resource("dynamodb").Table(TABLE)
    for product in ("product-a", "product-b"):
        item = table.get_item(
            Key={"project": product, "account_id": "123456789012"}
        ).get("Item")
        assert item is not None, f"no grant row for {product}"
        assert item["role"] == "customer"


@mock_aws
def test_grant_multiple_products_aborts_before_mutating_on_bad_product(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, TABLE)
    _setup_bucket(session, bucket="ra-kb-bucket", project="product-a")
    # "product-b" has no bucket → should abort the whole invocation.

    runner = CliRunner()
    result = runner.invoke(main, [
        "--region", "us-east-1",
        "grant", "--products", "product-a,product-b",
        "--account-id", "123456789012",
        "--role", "customer", "--friendly-name", "Acme",
    ])

    assert result.exit_code != 0
    assert "product-b" in result.output
    # The good product must NOT have been granted (validate-all-first).
    table = session.resource("dynamodb").Table(TABLE)
    assert table.get_item(
        Key={"project": "product-a", "account_id": "123456789012"}
    ).get("Item") is None
    from botocore.exceptions import ClientError
    s3 = session.client("s3")
    with pytest.raises(ClientError) as exc:
        s3.get_bucket_policy(Bucket="ra-kb-bucket")
    assert exc.value.response["Error"]["Code"] == "NoSuchBucketPolicy"


@mock_aws
def test_revoke_errors_when_no_grant_exists(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, TABLE)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--region", "us-east-1",
        "revoke", "missing-project", "123456789012",
    ])

    assert result.exit_code != 0
    assert "no grant found" in result.output


@mock_aws
def test_revoke_dry_run_shows_grant_contents(monkeypatch):
    from release_access.registry import Grant, upsert_grant

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, TABLE)
    _setup_bucket(session)

    upsert_grant(session, TABLE, Grant(
        project="ra-test", account_id="123456789012", role="customer",
        friendly_name="Acme Corp", granted_by="me",
        buckets=["arn:aws:s3:::ra-test-bucket"],
    ), allow_role_change=False)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--region", "us-east-1", "--dry-run",
        "revoke", "ra-test", "123456789012",
    ])

    assert result.exit_code == 0, result.output
    assert "Acme Corp" in result.output
    assert "role=customer" in result.output
