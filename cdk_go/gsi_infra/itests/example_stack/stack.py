"""Fixture stack for GSI orchestrator integration tests.

The fixture is fully self-contained: it instantiates [GsiInfraCore]
inside the same stack as the [ManagedTable] that consumes it. No
dependency on any pre-deployed base stack — the test runs ``cdk deploy``
to create/update the stack (which uploads Lambda assets to the CDK
bootstrap S3 bucket and creates the CloudFormation stack), then
``cdk destroy`` to tear it down.

The GSI declarations vary by SCENARIO env var:
  initial          2 GSIs (idx_a hash=a_key_v1, idx_b hash=b_key)
  updated          idx_a hash=a_key_v2 (drift→recreate), idx_c hash=c_key, idx_b gone
  one_gsi          1 GSI  (idx_a hash=a_key_v1)
  one_gsi_plus_c   2 GSIs (idx_a hash=a_key_v1, idx_c hash=c_key)
  ff_invalid       1 deliberately-invalid GSI (bad KeySchema: same HASH+RANGE key) —
                   proves the gate fails fast instead of waiting out the
                   WaitCondition timeout.
"""
import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
)
from constructs import Construct

from gsi_infra import GsiInfraCore, GsiReadinessGate, ManagedTable

EXAMPLE_TABLE_NAME = "gsi_infra_itest"

SCENARIO_INITIAL = "initial"
SCENARIO_UPDATED = "updated"
SCENARIO_ONE_GSI = "one_gsi"
SCENARIO_ONE_GSI_PLUS_C = "one_gsi_plus_c"
SCENARIO_FF_INVALID = "ff_invalid"

# A GSI that synthesizes cleanly but DynamoDB rejects at UpdateTable, so it
# exercises GsiReadinessGate's fast-fail path (worker hard-errors -> orchestrator
# execution FAILED -> gate signals FAILURE) rather than any earlier synth/template
# error.
#
# Lever: a bad KeySchema — the SAME attribute is used for both the partition
# (HASH) and sort (RANGE) key. DynamoDB rejects this with a ValidationException
# ("Both the Hash Key and the Range Key element in the KeySchema have the same
# name"). We deliberately do NOT use an over-long *index name*: ManagedTable folds
# the index name into the CloudFormation logical resource ID, so a >255-char name
# exceeds CFN's 255-char logical-ID limit and fails the template at changeset time
# (in seconds) BEFORE the request ever reaches DynamoDB or the readiness gate —
# which would prove nothing about fast-fail (and the test's own lower time-bound
# would correctly reject it).
FF_INVALID_INDEX_NAME = "idx_ff_invalid"
FF_INVALID_DUP_KEY = "ff_dup_key"


class _CommonResources:
    """Minimal stand-in for the consumer's CommonResources class. Holds
    the two ARN attributes [GsiInfraCore] sets and [ManagedTable] reads."""

    def __init__(self) -> None:
        self.gsi_state_machine_arn: str = None
        self.gsi_trigger_lambda_arn: str = None
        # Prefix on the orchestrator's Lambda + state machine names lets
        # this fixture coexist with a production deployment of the same
        # orchestrator in the same account.
        self.prefix: str = "test-"


def _add(table: ManagedTable, index_name: str, hash_key: str) -> None:
    table.add_global_secondary_index(
        index_name=index_name,
        partition_key=dynamodb.Attribute(name=hash_key, type=dynamodb.AttributeType.STRING),
        projection_type=dynamodb.ProjectionType.ALL,
    )


class GsiInfraExampleStack(Stack):
    def __init__(self, scope: Construct, id: str, *, scenario: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        common_resources = _CommonResources()

        # The orchestrator. Sets gsi_state_machine_arn / gsi_trigger_lambda_arn
        # on common_resources, which ManagedTable then reads when emitting
        # Custom::GsiIndex resources. ``common_resources.prefix = "test-"``
        # (set above) lets this fixture coexist with a production deployment
        # of the same orchestrator in the same account.
        self.gsi_infra = GsiInfraCore(
            self, "GsiInfra",
            common_resources=common_resources,
        )

        self.table = ManagedTable(
            self, "ExampleTable",
            common_resources=common_resources,
            table_name=EXAMPLE_TABLE_NAME,
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        if scenario == SCENARIO_INITIAL:
            _add(self.table, "idx_a", "a_key_v1")
            _add(self.table, "idx_b", "b_key")
        elif scenario == SCENARIO_UPDATED:
            _add(self.table, "idx_a", "a_key_v2")
            _add(self.table, "idx_c", "c_key")
        elif scenario == SCENARIO_ONE_GSI:
            _add(self.table, "idx_a", "a_key_v1")
        elif scenario == SCENARIO_ONE_GSI_PLUS_C:
            _add(self.table, "idx_a", "a_key_v1")
            _add(self.table, "idx_c", "c_key")
        elif scenario == SCENARIO_FF_INVALID:
            # One deliberately-invalid GSI: synth-valid, DDB-invalid. Reusing the
            # same attribute for HASH and RANGE is rejected by DynamoDB at
            # UpdateTable (see FF_INVALID_INDEX_NAME above), so the orchestrator
            # execution FAILs and GsiReadinessGate must fail the deploy fast.
            self.table.add_global_secondary_index(
                index_name=FF_INVALID_INDEX_NAME,
                partition_key=dynamodb.Attribute(name=FF_INVALID_DUP_KEY, type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name=FF_INVALID_DUP_KEY, type=dynamodb.AttributeType.STRING),
                projection_type=dynamodb.ProjectionType.ALL,
            )
        else:
            raise ValueError(f"unknown SCENARIO {scenario!r}")

        # Stack-level barrier — CFN waits for every GSI declared above to be
        # ACTIVE && !Backfilling before marking the deploy complete. A short
        # wait_condition_timeout (30min, well under the 12h default) keeps
        # this test's own bound tight — each scenario here creates at most 2
        # GSIs serially, well inside that window even on a slow control
        # plane — while still leaving room for ff_invalid to observe a real
        # fast-fail rather than a synth-time artifact.
        self.gate = GsiReadinessGate(
            self, "Gate",
            common_resources=common_resources,
            wait_condition_timeout=Duration.minutes(30),
        )

        CfnOutput(self, "ExampleTableName", value=self.table.table_name)


def scenario_from_env() -> str:
    return os.environ.get("GSI_INFRA_SCENARIO", SCENARIO_INITIAL)
