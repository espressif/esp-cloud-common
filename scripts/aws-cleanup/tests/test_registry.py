# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Service registry contract tests.

Every cleanup module must:
  - Import cleanly.
  - Subclass ``ServiceCleanup``.
  - Set non-empty ``name`` and ``boto_client`` attributes.
  - Provide a ``cli_options`` list (possibly empty).
  - Implement ``run`` as a callable.
  - Have a unique ``name`` within the registry.

The CLI must build successfully with all per-service options grafted on.
"""

import pytest

from services import REGISTRY, REGISTRY_BY_NAME, supported_services
from services.base import ServiceCleanup


def test_registry_non_empty():
    assert len(REGISTRY) > 0


def test_registry_by_name_lookup_consistent():
    assert {cls.name: cls for cls in REGISTRY} == REGISTRY_BY_NAME


def test_supported_services_includes_all_plus_all():
    names = supported_services()
    assert 'all' in names
    assert all(cls.name in names for cls in REGISTRY)


def test_unique_service_names():
    names = [cls.name for cls in REGISTRY]
    assert len(names) == len(set(names)), \
        f"Duplicate service names: {[n for n in names if names.count(n) > 1]}"


@pytest.mark.parametrize('cls', REGISTRY, ids=lambda c: c.name)
class TestServiceContract:
    def test_subclasses_servicecleanup(self, cls):
        assert issubclass(cls, ServiceCleanup)

    def test_has_name(self, cls):
        assert isinstance(cls.name, str) and cls.name, \
            f'{cls.__name__}.name must be a non-empty string'

    def test_has_boto_client(self, cls):
        assert isinstance(cls.boto_client, str) and cls.boto_client, \
            f'{cls.__name__}.boto_client must be a non-empty string'

    def test_cli_options_is_list(self, cls):
        assert isinstance(cls.cli_options, list), \
            f'{cls.__name__}.cli_options must be a list (possibly empty)'

    def test_run_is_callable(self, cls):
        assert callable(getattr(cls, 'run', None)), \
            f'{cls.__name__} must implement run()'


def test_cli_builds_without_errors():
    """The CLI factory grafts every per-service option onto the main command.
    A bad click decorator on any service breaks startup for everyone.
    """
    import importlib
    import sys
    # aws_cleanup.py builds the command at import time.
    sys.modules.pop('aws_cleanup', None)
    aws_cleanup = importlib.import_module('aws_cleanup')
    assert aws_cleanup.main is not None
    param_names = {p.name for p in aws_cleanup.main.params}
    # Standard options always exist.
    assert {'profile', 'region', 'services', 'dry_run'}.issubset(param_names)
    # Per-service options we know about must surface on the main command.
    for known_opt in ('protect_bucket_prefixes', 'iam_role_include_prefixes',
                      'iam_user_include_prefixes', 'cloudfront_name_include_prefixes',
                      'kms_pending_window_days', 'include_cloudtrail'):
        assert known_opt in param_names, f'{known_opt} missing from CLI'
