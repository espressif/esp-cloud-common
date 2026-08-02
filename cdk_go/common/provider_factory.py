# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Custom resource Provider factory.

[create_cr_provider] is a thin wrapper around
``aws_cdk.custom_resources.Provider`` that pins the logical IDs of the
Provider's framework Lambdas and waiter state machine to inputs derived
from ``provider_name``. Same role as ``create_lambda_function`` for
Lambdas: build the construct, then immediately stabilise its logical
IDs so a future reparent doesn't propagate down as a CFN replacement on
the consumer's ``Custom::*`` resources.

Why this matters:
  ``provider.service_token`` is ``GetAtt(framework-onEvent, Arn)``. If
  the framework-onEvent Lambda renames (CDK path change, reparent of
  the Provider, or a CDK-internal rename of the child), every consumer
  ``Custom::*`` resource using the service token sees a ``ServiceToken``
  property change → CFN treats it as Replacement → fires Create on a
  resource that already exists, with whatever side effect the onEvent
  handler implements. Pinning the framework Lambdas + waiter SM keeps
  service_token + framework-onEvent's WAITER_STATE_MACHINE_ARN env var
  stable.
"""

from aws_cdk import Duration, custom_resources as cr
from constructs import Construct

from .logical_id import stable_logical_id


def create_cr_provider(
    scope: Construct,
    id: str,
    *,
    provider_name: str,
    on_event_handler,
    is_complete_handler=None,
    query_interval: Duration = Duration.seconds(5),
    total_timeout: Duration = Duration.minutes(50),
) -> cr.Provider:
    """Create a ``cr.Provider`` with stable framework-Lambda + waiter-SM
    logical IDs.

    Args:
      provider_name: account-region-unique physical-name analog, used as
        the input to [stable_logical_id]. Pick something the consumer
        won't accidentally rename (e.g. ``"my-app-gsi-infra"``).
      on_event_handler / is_complete_handler / query_interval /
      total_timeout: passed through to ``cr.Provider``.

    Returns:
      The constructed ``cr.Provider`` (use ``provider.service_token`` on
      the consumer's ``CustomResource``).
    """
    # query_interval / total_timeout drive the isComplete waiter; CFN rejects
    # them when there is no isComplete handler (fire-and-forget provider), so
    # only pass them in the polling case.
    provider_kwargs = {"on_event_handler": on_event_handler}
    if is_complete_handler is not None:
        provider_kwargs["is_complete_handler"] = is_complete_handler
        provider_kwargs["query_interval"] = query_interval
        provider_kwargs["total_timeout"] = total_timeout
    provider = cr.Provider(scope, id, **provider_kwargs)
    # find_child raises if a child is missing — that's intentional. A
    # CDK upgrade that renames a framework child would fail loudly at
    # synth instead of silently un-pinning at deploy time.
    provider.node.find_child("framework-onEvent").node.default_child.override_logical_id(
        stable_logical_id("LambdaFunc", f"{provider_name}-framework-onevent"))
    if is_complete_handler is not None:
        provider.node.find_child("framework-isComplete").node.default_child.override_logical_id(
            stable_logical_id("LambdaFunc", f"{provider_name}-framework-iscomplete"))
        provider.node.find_child("framework-onTimeout").node.default_child.override_logical_id(
            stable_logical_id("LambdaFunc", f"{provider_name}-framework-ontimeout"))
        provider.node.find_child("waiter-state-machine").node.default_child.override_logical_id(
            stable_logical_id("SfnStateMachine", f"{provider_name}-waiter"))
    return provider
