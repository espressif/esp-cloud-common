"""GsiReadinessGate: a stack-level barrier that holds CFN deploy completion
until every ManagedTable in the parent stack is ACTIVE and every GSI on it is
ACTIVE && !Backfilling — using a native ``AWS::CloudFormation::WaitCondition``
(up to 12h) instead of a custom resource (bounded by CloudFormation's ~1h
``ServiceTimeout``).

Every ``GsiInfraCore``-managed GSI is fire-and-forget: the per-GSI custom
resource returns as soon as its orchestrator execution starts, so no
per-GSI CloudFormation timeout applies (fine for tables with several GSIs —
DynamoDB builds one online index per table at a time, so they are strictly
serial — even on an account with a slow control-plane). GsiReadinessGate is
the readiness barrier: instantiate it once at the end of the stack so
"deploy complete" still means "GSIs queryable".

How it works:
  1. A readiness state machine loops ``Wait -> check -> Choice(ready?)`` until
     every table + GSI is ready, then invokes a signal Lambda; on a repeated
     error it signals FAILURE so the stack fails fast instead of hanging.
  2. A native WaitCondition (timeout up to 12h) is what actually gates the stack.
  3. A lightweight trigger (AwsCustomResource) starts the state machine and
     returns immediately, passing the WaitCondition handle URL as input.

The WaitConditionHandle / WaitCondition logical IDs carry a hash of the current
``table:gsi`` set, so a deploy that adds or removes a GSI gets a fresh
WaitCondition that re-waits (and never consumes a stale signal), while a redeploy
with an unchanged GSI set reuses the already-satisfied one and completes at once.

Failure behavior (deliberate tradeoff): the per-GSI custom resource is
fire-and-forget, but the readiness check detects terminally-failed GSI
creates (bad KeySchema, missing UpdateTable permission, invalid index name,
etc.) — when a per-GSI orchestrator execution reaches FAILED/TIMED_OUT/
ABORTED, the gate signals FAILURE to the WaitCondition, rolling the stack
back in minutes with the failure cause on the stack event. Exception: if a
``LimitExceededException`` (per-table GSI count limit) is hit, the worker
retries it as transient, so the orchestrator execution never terminally
fails and the gate waits out ``wait_condition_timeout`` (default 12h). This is
the cost of decoupling per-GSI creation from CloudFormation so that *valid*
GSIs on a slow control-plane are tolerated. Such invalid definitions are
configuration bugs caught by a test deploy before customer rollout.
"""

import hashlib

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudformation as cfn,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    custom_resources as cr,
)
from constructs import Construct

from common import stable_logical_id
from .lambdas.gsi_readiness_check.stack import GsiReadinessCheckLambda
from .lambdas.gsi_readiness_signal.stack import GsiReadinessSignalLambda
from .managed_table import ManagedTable

# WaitCondition maximum timeout is 12 hours (43200s). It is a native CFN
# resource, so CloudFormation's ~1h custom-resource cap does not apply.
_WAIT_CONDITION_MAX = Duration.hours(12)


class GsiReadinessGate(Construct):
    """Stack-level GSI readiness barrier backed by a WaitCondition + state
    machine (see module docstring).

    Scans ``Stack.of(self).node.find_all()`` at __init__ time, so it MUST be
    instantiated AFTER all ManagedTables in the stack are created — otherwise
    tables added later are silently missed.

    Args:
      common_resources: the orchestrator's CommonResources object — its
        ``prefix`` attribute namespaces the state machine / Lambda names so a
        fixture stack can coexist with prod.
      query_interval: how often the state machine re-checks readiness.
      wait_condition_timeout: how long the WaitCondition holds the stack open
        before failing (max 12h).
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        common_resources,
        query_interval: Duration = Duration.seconds(30),
        wait_condition_timeout: Duration = _WAIT_CONDITION_MAX,
    ) -> None:
        super().__init__(scope, id)

        # AWS::CloudFormation::WaitCondition caps Timeout at 12h; reject anything
        # larger up front rather than letting CloudFormation fail at deploy time.
        if wait_condition_timeout.to_seconds() > _WAIT_CONDITION_MAX.to_seconds():
            raise ValueError(
                "wait_condition_timeout must be <= "
                f"{int(_WAIT_CONDITION_MAX.to_seconds())}s (AWS::CloudFormation::WaitCondition "
                f"max is 12h); got {int(wait_condition_timeout.to_seconds())}s."
            )

        tables = [
            c for c in Stack.of(self).node.find_all()
            if isinstance(c, ManagedTable)
        ]
        if not tables:
            raise ValueError(
                "GsiReadinessGate found no ManagedTables in the enclosing Stack. "
                "Instantiate this construct after the ManagedTables it should gate on."
            )
        # Literal names (never tokens) so the digest below is deterministic
        # across synths. t.table_name is a Ref token; t.stable_id is the literal.
        table_names = sorted(t.stable_id for t in tables)
        prefix = getattr(common_resources, "prefix", "") or ""

        check = GsiReadinessCheckLambda(self, "Check", common_resources=common_resources)
        signal = GsiReadinessSignalLambda(self, "Signal", common_resources=common_resources)

        # --- Readiness state machine: Wait -> check -> Choice(ready?) loop ---
        # Shared retry policy for every task that calls a Lambda: transient
        # Lambda / control-plane errors are retried rather than failing the
        # execution (which, on the signal tasks, would strand the WaitCondition
        # until its 12h timeout).
        _lambda_retry = dict(
            errors=[
                "Lambda.ServiceException",
                "Lambda.TooManyRequestsException",
                "Lambda.SdkClientException",
                "States.TaskFailed",
            ],
            interval=Duration.seconds(5),
            max_attempts=5,
            backoff_rate=2.0,
        )

        check_task = tasks.LambdaInvoke(
            self, "CheckReady",
            lambda_function=check.function,
            payload=sfn.TaskInput.from_object({"expected.$": "$.expected"}),
            payload_response_only=True,
            result_path="$.check",
        )
        check_task.add_retry(**_lambda_retry)

        wait = sfn.Wait(self, "WaitForGsis", time=sfn.WaitTime.duration(query_interval))

        # add_retry must be called on the LambdaInvoke before .next() (which
        # returns a Chain, not the task).
        signal_success_task = tasks.LambdaInvoke(
            self, "SignalSuccess",
            lambda_function=signal.function,
            payload=sfn.TaskInput.from_object({"signal_url.$": "$.signal_url", "status": "SUCCESS"}),
            payload_response_only=True,
        )
        signal_success_task.add_retry(**_lambda_retry)
        signal_success = signal_success_task.next(sfn.Succeed(self, "ReadinessComplete"))

        signal_failure_task = tasks.LambdaInvoke(
            self, "SignalFailure",
            lambda_function=signal.function,
            payload=sfn.TaskInput.from_object({
                "signal_url.$": "$.signal_url",
                "status": "FAILURE",
                "reason": "GSI readiness check failed",
            }),
            payload_response_only=True,
        )
        signal_failure_task.add_retry(**_lambda_retry)
        signal_failure = signal_failure_task.next(sfn.Fail(self, "ReadinessFailed", cause="GSI readiness failed"))

        # A genuine, repeated check error (missing perms, bad table) surfaces as
        # FAILURE so the stack fails fast instead of waiting out the WaitCondition.
        check_task.add_catch(signal_failure, result_path="$.error")

        # A terminally failed GSI create (detected by the check Lambda via the
        # per-GSI orchestrator's own execution history) also signals FAILURE so
        # the stack fails fast instead of waiting out the WaitCondition.
        signal_create_failed_task = tasks.LambdaInvoke(
            self, "SignalCreateFailed",
            lambda_function=signal.function,
            payload=sfn.TaskInput.from_object({
                "signal_url.$": "$.signal_url",
                "status": "FAILURE",
                "reason.$": "$.check.reason",
            }),
            payload_response_only=True,
        )
        signal_create_failed_task.add_retry(**_lambda_retry)
        signal_create_failed = signal_create_failed_task.next(
            sfn.Fail(self, "CreateFailed", cause="GSI create failed")
        )

        choice = (
            sfn.Choice(self, "AllGsisReady?")
            .when(sfn.Condition.boolean_equals("$.check.failed", True), signal_create_failed)
            .when(sfn.Condition.boolean_equals("$.check.ready", True), signal_success)
            .otherwise(wait.next(check_task))
        )
        check_task.next(choice)

        state_machine_name = f"{prefix}gsi-readiness"
        state_machine = sfn.StateMachine(
            self, "StateMachine",
            state_machine_name=state_machine_name,
            definition_body=sfn.DefinitionBody.from_chainable(check_task),
            # Just past the WaitCondition ceiling so the WaitCondition is what
            # fails the stack, not an orphaned execution.
            timeout=wait_condition_timeout.plus(Duration.hours(1)),
        )
        state_machine.node.default_child.override_logical_id(
            stable_logical_id("SfnStateMachine", state_machine_name)
        )

        # --- Native WaitCondition that actually gates the stack ---
        # A fresh handle whenever the GSI set changes: the logical id carries a
        # hash of the sorted table:gsi list. Adding/removing a GSI yields a new
        # WaitCondition that re-waits (and can't consume a prior deploy's signal);
        # an unchanged GSI set reuses the already-satisfied one, so a no-op
        # redeploy completes immediately.
        gsi_set = sorted(
            f"{t.stable_id}:{name}"
            for t in tables for name in t.gsi_names
        )
        digest = hashlib.sha256("|".join([*table_names, "::", *gsi_set]).encode()).hexdigest()[:12]

        handle = cfn.CfnWaitConditionHandle(self, "Handle")
        handle.override_logical_id(stable_logical_id("GsiReadinessHandle", f"{prefix}{digest}"))

        # Expected table -> [gsi names]. The readiness check requires every
        # expected GSI to be present AND ACTIVE && !Backfilling, so in
        # fire-and-forget mode it cannot signal ready before a not-yet-created
        # GSI exists (a table with no GSIs maps to [] — only TableStatus checked).
        expected = {t.table_name: sorted(t.gsi_names) for t in tables}
        readiness_input = Stack.of(self).to_json_string({
            "expected": expected,
            "signal_url": handle.ref,
        })

        # Trigger: start the readiness execution (returns in ~1s) with the handle
        # URL as input. Depends on every table (and, transitively, its GSI custom
        # resources) so creation is initiated before the state machine polls.
        trigger = cr.AwsCustomResource(
            self, "Trigger",
            on_create=cr.AwsSdkCall(
                service="sfn",
                action="startExecution",
                parameters={"stateMachineArn": state_machine.state_machine_arn, "input": readiness_input},
                physical_resource_id=cr.PhysicalResourceId.of(f"gsi-readiness-{digest}"),
            ),
            on_update=cr.AwsSdkCall(
                service="sfn",
                action="startExecution",
                parameters={"stateMachineArn": state_machine.state_machine_arn, "input": readiness_input},
                physical_resource_id=cr.PhysicalResourceId.of(f"gsi-readiness-{digest}"),
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["states:StartExecution"],
                    resources=[state_machine.state_machine_arn],
                ),
            ]),
            install_latest_aws_sdk=False,
        )
        for t in tables:
            trigger.node.add_dependency(t)

        condition = cfn.CfnWaitCondition(
            self, "Condition",
            count=1,
            handle=handle.ref,
            timeout=str(int(wait_condition_timeout.to_seconds())),
        )
        condition.override_logical_id(stable_logical_id("GsiReadinessCondition", f"{prefix}{digest}"))
        # Begin waiting only after the trigger has started the state machine.
        condition.node.add_dependency(trigger)

        self.state_machine = state_machine
        self.wait_condition = condition
