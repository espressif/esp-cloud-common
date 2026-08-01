from aws_cdk import Aws, Duration, aws_iam as iam
from constructs import Construct

from common import create_lambda_function

from ...managed_table import GSI_MANAGED_BY_TAG_KEY, GSI_MANAGED_BY_TAG_VALUE


class GsiWorkerLambda(Construct):
    def __init__(
        self, scope: Construct, id: str,
        *,
        common_resources,
    ) -> None:
        super().__init__(scope, id)

        prefix = getattr(common_resources, "prefix", "") or ""
        # Asset path stays "gsi_worker" so the Makefile-built binary at
        # ./build/gsi_worker/ resolves regardless of prefix; only the
        # deployed Lambda name changes.
        self.function = create_lambda_function(
            self, "gsi_worker", common_resources,
            timeout=Duration.seconds(60),
            aws_function_name=f"{prefix}gsi-worker",
        )
        # IAM is scoped by ManagedBy tag — only tables ManagedTable creates.
        self.function.role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:UpdateTable", "dynamodb:DescribeTable"],
            resources=[f"arn:{Aws.PARTITION}:dynamodb:{Aws.REGION}:{Aws.ACCOUNT_ID}:table/*"],
            conditions={"StringEquals": {f"aws:ResourceTag/{GSI_MANAGED_BY_TAG_KEY}": GSI_MANAGED_BY_TAG_VALUE}},
        ))
