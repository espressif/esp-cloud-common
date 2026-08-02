# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for IoT-owned domain configuration protection.

Attempting to delete AWS-owned domain configurations produces:
  ✗ Error deleting domain config iot:Data-ATS: ...
    InvalidRequestException: IoT owned domain configuration cannot be
    updated with the supplied arguments.
  ✗ Error deleting domain config iot:CredentialProvider: ...

AWS-owned IoT domain configurations are named with the ``iot:`` prefix and
cannot be modified or deleted via API. Skip them by name so the cleanup
log doesn't spam errors and we don't waste API calls.
"""

import pytest

from services.iot import _domain_configuration_is_protected


@pytest.mark.parametrize('name', [
    'iot:Data-ATS',
    'iot:CredentialProvider',
    'iot:Jobs',
])
def test_aws_owned_iot_domains_are_skipped(name):
    assert _domain_configuration_is_protected(name), \
        f'AWS-owned IoT domain config {name} must be protected'


@pytest.mark.parametrize('name', [
    'data.example.com',
    'mqtt-broker',
    'my-custom-iot-endpoint',
    # An IoT customer naming their own config without the iot: prefix.
    'iotData-Custom',
])
def test_customer_iot_domains_are_not_skipped(name):
    assert not _domain_configuration_is_protected(name), \
        f'Customer IoT domain config {name} should be deletable'
