"""CFN custom-resource onEvent handler for the GSI provider.

Starts a Step Functions execution per CFN Create/Update; on Delete, stops
the in-flight execution so rollback isn't blocked.
"""

from aws_cdk import Aws, Duration, aws_iam as iam
from constructs import Construct

from common import create_lambda_function


class GsiTriggerOnEventLambda(Construct):
    def __init__(
        self, scope: Construct, id: str,
        *,
        common_resources,
        state_machine_arn: str,
        state_machine_name: str,
    ) -> None:
        super().__init__(scope, id)

        prefix = getattr(common_resources, "prefix", "") or ""
        self.function = create_lambda_function(
            self, "gsi_trigger_onevent", common_resources,
            timeout=Duration.seconds(30),
            aws_function_name=f"{prefix}gsi-trigger-onevent",
        )
        self.function.role.add_to_policy(iam.PolicyStatement(
            actions=["states:StartExecution", "states:StopExecution"],
            resources=[
                state_machine_arn,
                f"arn:{Aws.PARTITION}:states:{Aws.REGION}:{Aws.ACCOUNT_ID}:execution:{state_machine_name}:*",
            ],
        ))
