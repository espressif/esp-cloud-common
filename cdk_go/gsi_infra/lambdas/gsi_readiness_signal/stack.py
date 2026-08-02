# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Duration
from constructs import Construct

from common import create_lambda_function


class GsiReadinessSignalLambda(Construct):
    """Fire-once PUT of a SUCCESS/FAILURE signal to a CloudFormation
    WaitCondition pre-signed URL. Needs no AWS permissions (the URL is
    pre-signed) — only outbound HTTPS. Invoked by the readiness state machine
    once the check reports ready, or from its failure path."""

    def __init__(
        self, scope: Construct, id: str,
        *,
        common_resources,
    ) -> None:
        super().__init__(scope, id)

        prefix = getattr(common_resources, "prefix", "") or ""
        self.function = create_lambda_function(
            self, "gsi_readiness_signal", common_resources,
            timeout=Duration.seconds(30),
            aws_function_name=f"{prefix}gsi-readiness-signal",
        )
