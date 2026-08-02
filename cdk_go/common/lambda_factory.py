# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Lambda construction helpers for esp-cloud-common.

[create_lambda_function] is a thin wrapper around
``aws_cdk.aws_lambda.Function`` that loads a prebuilt Go binary from
``build/{function_name}/`` (relative to the consumer's cwd at synth
time). Consumers that need additional product-specific IAM (user pool,
JWKS, etc.) can attach it to ``function.role`` after construction.
"""

import os
from pathlib import Path

from aws_cdk import (
    Aws,
    Duration,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct

from .logical_id import stable_logical_id


def create_base_lambda_role(scope: Construct, lambda_name: str) -> iam.Role:
    """An IAM role with the AWS-managed basic Lambda execution policy plus
    explicit logs:* on all CloudWatch resources."""
    role = iam.Role(
        scope,
        f"{lambda_name}_lambda_role",
        assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        managed_policies=[
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            ),
        ],
    )
    role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
            ],
            resources=["*"],
        )
    )
    return role


def _build_dir(function_name: str) -> str:
    """Return ``build/{function_name}/`` as an absolute path. Resolved
    against the *current working directory* of the CDK synth so consumers
    that vendor esp-cloud-common as a submodule keep their existing build
    layout — Makefile produces binaries in ``./build/<name>/`` at the
    consumer repo root."""
    return str(Path.cwd() / "build" / function_name)


def create_lambda_function(
    scope: Construct,
    function_name: str,
    common_resources=None,
    *,
    lambda_role: iam.Role = None,
    environment: dict = None,
    timeout: Duration = Duration.seconds(30),
    layers: list = None,
    aws_function_name: str = None,
) -> lambda_.Function:
    """Create a Lambda from ``build/{function_name}/`` (consumer's cwd).

    Args:
      function_name: plain string used both for the construct id and the
        ``build/{function_name}/`` asset path.
      common_resources: ignored by this implementation; accepted as a
        positional placeholder so consumer codebases that wrap this with
        their own product-specific factory can pass it through. Attach
        any extra IAM/env to ``function.role`` after construction.
      lambda_role: optional IAM role; if None, [create_base_lambda_role] is
        used.
      environment: extra environment variables (merged with defaults).
      timeout, layers: passed through to ``lambda_.Function``.
      aws_function_name: deployed Lambda name in AWS; may be a CDK token.
        Falls back to ``function_name`` when omitted, so by default the
        construct id, the asset directory, and the deployed Lambda name
        all match. Override only when you need a different deployed name
        (e.g. a ``test-`` prefix to coexist with a production deployment).
    """
    if lambda_role is None:
        lambda_role = create_base_lambda_role(scope, function_name)

    base_env = {
        "AWS_ACCOUNT_ID": Aws.ACCOUNT_ID,
    }
    if environment:
        base_env.update(environment)

    binary_path = _build_dir(function_name)

    lambda_props = {
        "function_name": aws_function_name if aws_function_name is not None else function_name,
        "handler": "bootstrap",
        "code": lambda_.Code.from_asset(path=binary_path),
        "runtime": lambda_.Runtime.PROVIDED_AL2023,
        "architecture": lambda_.Architecture.ARM_64,
        "memory_size": 128,
        "timeout": timeout,
        "role": lambda_role,
        "environment": base_env,
    }

    if layers:
        lambda_props["layers"] = layers

    func = lambda_.Function(scope, function_name, **lambda_props)
    # Pin the CfnFunction logical ID using the deployed AWS function name
    # so a CDK reparent doesn't rename the Lambda — the function_name
    # property is set above and would conflict (ResourceConflictException)
    # on a logical-ID rename. Match the consuming app's convention:
    # input to stable_logical_id is the physical resource name.
    func.node.default_child.override_logical_id(
        stable_logical_id("LambdaFunc", lambda_props["function_name"])
    )
    return func
