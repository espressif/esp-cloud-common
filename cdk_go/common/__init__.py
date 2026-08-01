"""Shared CDK helpers used by other esp-cloud-common constructs.

The canonical entry point is [create_lambda_function], a thin wrapper
around ``aws_cdk.aws_lambda.Function`` that loads a prebuilt Go binary
from a ``build/{function_name}/`` directory. Consumers that need
additional IAM (e.g. user-pool / JWKS access) can layer it on after the
function is constructed.
"""

from .lambda_factory import (
    create_base_lambda_role,
    create_lambda_function,
)
from .logical_id import stable_logical_id
from .provider_factory import create_cr_provider

__all__ = [
    "create_base_lambda_role",
    "create_cr_provider",
    "create_lambda_function",
    "stable_logical_id",
]
