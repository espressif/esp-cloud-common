# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Aws, Duration, Fn, aws_iam as iam
from constructs import Construct

from common import create_lambda_function

from ...managed_table import GSI_MANAGED_BY_TAG_KEY, GSI_MANAGED_BY_TAG_VALUE


class GsiReadinessCheckLambda(Construct):
    """One readiness poll: reports whether every named table is ACTIVE and every
    GSI on it is ACTIVE && !Backfilling. Invoked on a loop by the readiness
    state machine (see [GsiReadinessGate])."""

    def __init__(
        self, scope: Construct, id: str,
        *,
        common_resources,
    ) -> None:
        super().__init__(scope, id)

        prefix = getattr(common_resources, "prefix", "") or ""
        sm_arn = common_resources.gsi_state_machine_arn
        self.function = create_lambda_function(
            self, "gsi_readiness_check", common_resources,
            # Generous headroom: one invocation issues a DescribeTable per managed
            # table (sequentially), and the poll is off the hot path.
            timeout=Duration.seconds(120),
            aws_function_name=f"{prefix}gsi-readiness-check",
            environment={"GSI_ORCHESTRATOR_STATE_MACHINE_ARN": sm_arn},
        )
        # Read-only DescribeTable, scoped by the ManagedBy tag — same scope as
        # the GSI worker and the (legacy) tables-ready check.
        self.function.role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:DescribeTable"],
            resources=[f"arn:{Aws.PARTITION}:dynamodb:{Aws.REGION}:{Aws.ACCOUNT_ID}:table/*"],
            conditions={"StringEquals": {f"aws:ResourceTag/{GSI_MANAGED_BY_TAG_KEY}": GSI_MANAGED_BY_TAG_VALUE}},
        ))
        # Read access to the per-GSI orchestrator's own executions, so the
        # check Lambda can detect a terminally failed create and report
        # {"failed": true, "reason": ...} instead of waiting out the
        # WaitCondition timeout (see readiness_gate.py's SignalCreateFailed).
        self.function.role.add_to_policy(iam.PolicyStatement(
            actions=["states:ListExecutions"],
            resources=[sm_arn],
        ))
        self.function.role.add_to_policy(iam.PolicyStatement(
            actions=["states:DescribeExecution"],
            # execution ARNs derive from the state-machine name:
            # arn:<partition>:states:<region>:<acct>:execution:<name>:*
            resources=[Fn.join(":", ["arn", Aws.PARTITION, "states", Aws.REGION, Aws.ACCOUNT_ID, "execution",
                                     Fn.select(6, Fn.split(":", sm_arn)), "*"])],
        ))
