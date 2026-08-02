# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for bootstrap.py — DynamoDB table creation."""

import boto3
from moto import mock_aws

from release_access.bootstrap import ensure_table


@mock_aws
def test_ensure_table_creates_when_absent():
    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, "release-access-grants")

    client = session.client("dynamodb")
    desc = client.describe_table(TableName="release-access-grants")["Table"]
    keys = {k["AttributeName"]: k["KeyType"] for k in desc["KeySchema"]}
    assert keys == {"project": "HASH", "account_id": "RANGE"}
    assert desc["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"


@mock_aws
def test_ensure_table_is_idempotent():
    session = boto3.Session(region_name="us-east-1")
    ensure_table(session, "release-access-grants")
    ensure_table(session, "release-access-grants")  # no exception
    client = session.client("dynamodb")
    assert client.describe_table(TableName="release-access-grants")
