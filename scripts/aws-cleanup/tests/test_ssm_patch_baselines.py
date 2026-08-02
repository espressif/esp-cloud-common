# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for SSM patch baseline cleanup.

These exist because ``describe_patch_baselines`` without a filter returns
AWS-owned default patch baselines from accounts like ``075727635805``
alongside the caller's own baselines. The cleanup logic must filter to
``OWNER=Self`` so we never try to delete cross-account baselines.
"""

from io import StringIO
from rich.console import Console

from services.base import _DryRunClient
from services.ssm import SSMCleanup


class _FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.last_kwargs = None

    def paginate(self, **kwargs):
        self.last_kwargs = kwargs
        for page in self.pages:
            yield page


class _FakeSSMClient:
    """Records arguments to describe_patch_baselines so the test can assert
    the OWNER=Self filter is passed."""

    def __init__(self):
        self.paginator = _FakePaginator([{'BaselineIdentities': []}])

    def get_paginator(self, name):
        assert name == 'describe_patch_baselines', f'unexpected paginator: {name}'
        return self.paginator


class _FakeSession:
    def __init__(self, ssm_client):
        self._ssm_client = ssm_client

    def client(self, name):
        if name == 'ssm':
            return self._ssm_client
        raise AssertionError(f'unexpected client: {name}')


def test_patch_baselines_filtered_to_self_owner():
    fake = _FakeSSMClient()
    session = _FakeSession(fake)
    console = Console(file=StringIO())

    cleanup = SSMCleanup(session, console, dry_run=False)
    cleanup._delete_patch_baselines()

    assert fake.paginator.last_kwargs == {
        'Filters': [{'Key': 'OWNER', 'Values': ['Self']}],
    }, f'expected OWNER=Self filter, got {fake.paginator.last_kwargs}'


def test_default_self_owned_baselines_are_still_skipped():
    """Belt-and-suspenders: even within OWNER=Self, AWS sometimes flags a
    baseline with DefaultBaseline=true. Skip those too."""
    fake = _FakeSSMClient()
    fake.paginator = _FakePaginator([{
        'BaselineIdentities': [
            {'BaselineId': 'pb-default', 'DefaultBaseline': True},
            {'BaselineId': 'pb-custom', 'DefaultBaseline': False},
        ],
    }])

    deleted = []
    fake.delete_patch_baseline = lambda BaselineId: deleted.append(BaselineId)

    session = _FakeSession(fake)
    console = Console(file=StringIO())
    cleanup = SSMCleanup(session, console, dry_run=False)
    cleanup._delete_patch_baselines()

    assert deleted == ['pb-custom'], \
        f'expected only pb-custom deleted, got {deleted}'
