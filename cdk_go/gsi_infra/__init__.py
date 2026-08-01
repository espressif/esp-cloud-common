"""GSI orchestrator: a CDK construct that serializes DynamoDB GSI changes
behind a state machine + custom resource. The user-facing API is
[ManagedTable] (a drop-in for `aws_cdk.aws_dynamodb.Table`) and
[GsiInfraCore] (the orchestrator construct that ManagedTable depends on).

Typical wiring inside a base stack:

    from gsi_infra import GsiInfraCore, ManagedTable

    self.gsi_infra = GsiInfraCore(
        self, "GsiInfra",
        common_resources=self.common_resources,
        lambda_factory=create_lambda_function,
    )
    # ...later, in any product table:
    self.users = ManagedTable(self, "Users", common_resources=self.common_resources, ...)
"""

from .base import GsiInfra, GsiInfraCore
from .managed_table import (
    GSI_MANAGED_BY_TAG_KEY,
    GSI_MANAGED_BY_TAG_VALUE,
    ManagedTable,
)
from .readiness_gate import GsiReadinessGate

__all__ = [
    "GsiInfra",
    "GsiInfraCore",
    "GSI_MANAGED_BY_TAG_KEY",
    "GSI_MANAGED_BY_TAG_VALUE",
    "ManagedTable",
    "GsiReadinessGate",
]
