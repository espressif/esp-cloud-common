# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for discovery.py — bucket lookup via Resource Groups Tagging API."""

import boto3
import pytest
from moto import mock_aws

from release_access.discovery import find_release_buckets


@mock_aws
def test_find_release_buckets_filters_on_project_and_purpose():
    session = boto3.Session(region_name="us-east-1")
    s3 = session.client("s3")

    # bucket A: matches project AND purpose
    s3.create_bucket(Bucket="bucket-a")
    s3.put_bucket_tagging(Bucket="bucket-a", Tagging={"TagSet": [
        {"Key": "Project", "Value": "my-product"},
        {"Key": "Purpose", "Value": "release-artifacts"},
    ]})

    # bucket B: same project, wrong purpose
    s3.create_bucket(Bucket="bucket-b")
    s3.put_bucket_tagging(Bucket="bucket-b", Tagging={"TagSet": [
        {"Key": "Project", "Value": "my-product"},
        {"Key": "Purpose", "Value": "logs"},
    ]})

    # bucket C: different project, right purpose
    s3.create_bucket(Bucket="bucket-c")
    s3.put_bucket_tagging(Bucket="bucket-c", Tagging={"TagSet": [
        {"Key": "Project", "Value": "other"},
        {"Key": "Purpose", "Value": "release-artifacts"},
    ]})

    buckets = find_release_buckets(session, "my-product")
    assert buckets == ["bucket-a"]


@mock_aws
def test_find_release_buckets_returns_empty_list_when_no_match():
    session = boto3.Session(region_name="us-east-1")
    assert find_release_buckets(session, "nonexistent") == []
