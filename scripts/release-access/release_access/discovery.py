# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Locate S3 release buckets by their `Project` + `Purpose` tags."""

from __future__ import annotations

import boto3


PURPOSE_TAG_VALUE = "release-artifacts"


def find_release_buckets(session: boto3.Session, project: str) -> list[str]:
    """Return bucket names tagged Project=<project> AND Purpose=release-artifacts.

    Uses the Resource Groups Tagging API so we don't have to GetBucketTagging
    on every bucket in the account. The API returns ARNs of the form
    ``arn:aws:s3:::<bucket>``; we strip the prefix.
    """
    client = session.client("resourcegroupstaggingapi")

    bucket_names: list[str] = []
    paginator = client.get_paginator("get_resources")
    pages = paginator.paginate(
        ResourceTypeFilters=["s3:bucket"],
        TagFilters=[
            {"Key": "Project", "Values": [project]},
            {"Key": "Purpose", "Values": [PURPOSE_TAG_VALUE]},
        ],
    )
    for page in pages:
        for mapping in page.get("ResourceTagMappingList", []):
            arn = mapping["ResourceARN"]
            # arn:aws:s3:::bucket-name
            bucket_names.append(arn.split(":::", 1)[1])
    return bucket_names
