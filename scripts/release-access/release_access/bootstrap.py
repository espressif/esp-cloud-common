# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotent DynamoDB table provisioning for the grants registry."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError


def ensure_table(session: boto3.Session, table_name: str) -> None:
    """Create the grants table if it doesn't exist; otherwise no-op."""
    client = session.client("dynamodb")
    try:
        client.describe_table(TableName=table_name)
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "project", "AttributeType": "S"},
            {"AttributeName": "account_id", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "project", "KeyType": "HASH"},
            {"AttributeName": "account_id", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
