"""Shared infrastructure for per-service cleanup modules.

Each concrete service subclasses ``ServiceCleanup`` and implements ``run()``.
The dry-run proxy here works for *any* service because boto3 verb prefixes
(``delete_``, ``detach_``, ``put_``, ``update_``, ...) are universal — there
is no per-service mocking to write.
"""

from abc import ABC, abstractmethod


# Read-only verb prefixes. Anything not matching these is treated as
# potentially mutating in dry-run mode and intercepted. This is an
# allowlist — safer than enumerating destructive verbs (we got bitten
# by `schedule_key_deletion` slipping past a destructive-only list).
_READ_ONLY_PREFIXES = (
    'list_', 'describe_', 'get_', 'head_', 'lookup_', 'query_',
    'search_', 'select_', 'check_', 'test_', 'estimate_', 'preview_',
    'batch_get_', 'batch_describe_',
)


class _NoopWaiter:
    def wait(self, *args, **kwargs):
        return None


def _truncate(value, limit=80):
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + '...'


class _DryRunClient:
    """boto3 client wrapper that short-circuits mutating calls."""

    def __init__(self, real_client, service_name, console):
        self._real = real_client
        self._service = service_name
        self._console = console

    def __getattr__(self, name):
        # Special boto3 methods we always pass through.
        if name in ('get_waiter',):
            return lambda *a, **kw: _NoopWaiter()
        if name in ('get_paginator', 'meta', 'can_paginate', 'exceptions',
                    'waiter_names'):
            return getattr(self._real, name)
        attr = getattr(self._real, name)
        # Allowlist read prefixes; intercept everything else.
        if any(name.startswith(p) for p in _READ_ONLY_PREFIXES):
            return attr
        if not callable(attr):
            return attr
        service = self._service
        console = self._console

        def stub(*args, **kwargs):
            summary = ', '.join(f"{k}={_truncate(v)}" for k, v in kwargs.items())
            console.print(f"[magenta][DRY RUN] would call {service}.{name}({summary})[/magenta]")
            return {}
        return stub


class ServiceCleanup(ABC):
    """Base class for an AWS service cleanup module.

    Subclasses set:
      - ``name``: CLI identifier passed to ``--service``.
      - ``boto_client``: name passed to ``session.client(...)``.
      - ``cli_options``: list of ``click.option`` decorators to expose.
    They implement ``run()`` to perform the actual cleanup using ``self.client``.
    """

    name: str = ''
    boto_client: str = ''
    cli_options: list = []

    def __init__(self, session, console, dry_run=False, options=None):
        self.session = session
        self.console = console
        self.dry_run = dry_run
        self.options = options or {}
        real = session.client(self.boto_client)
        self.client = _DryRunClient(real, self.boto_client, console) if dry_run else real

    @abstractmethod
    def run(self):
        ...
