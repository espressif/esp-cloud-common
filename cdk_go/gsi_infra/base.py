"""GSI orchestrator state machine + composer.

Callers wire this into a base CDK stack and then use [ManagedTable] (in
managed_table.py) as a drop-in replacement for `aws_cdk.aws_dynamodb.Table`.
"""

from aws_cdk import (
    Duration,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    custom_resources as cr,
)
from constructs import Construct

from common import create_cr_provider, stable_logical_id
from .lambdas.gsi_worker.stack import GsiWorkerLambda
from .lambdas.gsi_trigger_onevent.stack import GsiTriggerOnEventLambda

STATE_MACHINE_NAME = "gsi-infra"


class GsiInfra(Construct):
    """Step Functions state machine that drives one GSI create/delete per execution."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        worker_function,
        state_machine_name: str = STATE_MACHINE_NAME,
        # Fire-and-forget is the only mode: the state machine serializes
        # same-table GSI builds via its retry loop, bounded by the stack-level
        # GsiReadinessGate's WaitCondition (up to 12h), not a per-GSI cap.
        state_machine_timeout: Duration = Duration.hours(12),
    ) -> None:
        super().__init__(scope, id)
        self._state_machine_name = state_machine_name
        self._state_machine_timeout = state_machine_timeout
        self.state_machine = self._build_state_machine(worker_function)

    @property
    def state_machine_arn(self) -> str:
        return self.state_machine.state_machine_arn

    def _build_state_machine(self, worker) -> sfn.StateMachine:
        # Construct all states first, then wire transitions — sfn.next() /
        # Choice branches evaluate their target argument immediately.
        init = sfn.Pass(
            self, "Init",
            parameters={
                "table_name.$": "$.table_name",
                "operation.$": "$.operation",
                "attribute_definitions.$": "$.attribute_definitions",
                "attempt": 0,
            },
        )
        invoke_describe = tasks.LambdaInvoke(
            self, "DescribeTable",
            lambda_function=worker,
            payload=sfn.TaskInput.from_object({
                "table_name.$": "$.table_name",
                "mode": "describe",
                "attempt.$": "$.attempt",
            }),
            result_selector={"is_active.$": "$.Payload.is_active"},
            result_path="$.worker_out",
        )
        invoke_apply = tasks.LambdaInvoke(
            self, "ApplyOperation",
            lambda_function=worker,
            payload=sfn.TaskInput.from_object({
                "table_name.$": "$.table_name",
                "operation.$": "$.operation",
                "attribute_definitions.$": "$.attribute_definitions",
                "mode": "apply",
                "attempt.$": "$.attempt",
            }),
            result_selector={
                "is_active.$": "$.Payload.is_active",
                "attempt.$": "$.Payload.attempt",
            },
            result_path="$.worker_out",
        )
        # Retry transient Lambda / control-plane errors on BOTH worker tasks.
        # The worker already treats ResourceInUse/LimitExceeded as a retryable
        # Attempt+1 result (no throw), so these retries catch the *other* class:
        # a transient DescribeTable/UpdateTable error the worker surfaces as a
        # hard error, or an SFN-layer Lambda invocation failure (throttling, cold
        # start). This matters because same-table serialization keeps the
        # execution polling for a long time (many invocations), and a FAILED
        # execution is invisible to CloudFormation (fire-and-forget: the custom
        # resource already returned) — so a single un-retried transient error
        # would silently drop a GSI.
        for _worker_task in (invoke_describe, invoke_apply):
            _worker_task.add_retry(
                errors=[
                    "Lambda.ServiceException",
                    "Lambda.TooManyRequestsException",
                    "Lambda.SdkClientException",
                    "States.TaskFailed",
                ],
                interval=Duration.seconds(5),
                max_attempts=3,
                backoff_rate=2.0,
            )
        promote = sfn.Pass(
            self, "PromoteAttempt",
            parameters={
                "table_name.$": "$.table_name",
                "operation.$": "$.operation",
                "attribute_definitions.$": "$.attribute_definitions",
                "attempt.$": "$.worker_out.attempt",
                "is_active.$": "$.worker_out.is_active",
            },
        )
        done = sfn.Succeed(self, "Done")
        # Inverted backoff: 60s first wait skips the certain-not-ready
        # window (DDB warm-throughput floor is ~5 min), then 30s on every
        # subsequent retry. Bounds wall-clock overshoot to ~30s when the
        # prior op finishes, and minimizes DescribeTable calls under the
        # 10 TPS account-wide control-plane cap.
        wait_table = sfn.Wait(self, "WaitTable", time=sfn.WaitTime.duration(Duration.seconds(10)))
        wait_first = sfn.Wait(self, "WaitFirst", time=sfn.WaitTime.duration(Duration.seconds(60)))
        wait_retry = sfn.Wait(self, "WaitRetry", time=sfn.WaitTime.duration(Duration.seconds(30)))

        choose_wait = (
            sfn.Choice(self, "ChooseWait")
            .when(sfn.Condition.number_less_than("$.attempt", 1), wait_first)
            .otherwise(wait_retry)
        )
        is_active = (
            sfn.Choice(self, "IsActive")
            .when(sfn.Condition.boolean_equals("$.is_active", True), done)
            .otherwise(choose_wait)
        )
        # Belt-and-suspenders for cross-stack table+GSI cases where CDK
        # add_dependency can't reach across the synth boundary.
        is_table_active = (
            sfn.Choice(self, "IsTableActive")
            .when(sfn.Condition.boolean_equals("$.worker_out.is_active", True), invoke_apply)
            .otherwise(wait_table.next(invoke_describe))
        )

        init.next(invoke_describe)
        invoke_describe.next(is_table_active)
        for w in (wait_first, wait_retry):
            w.next(invoke_apply)
        invoke_apply.next(promote.next(is_active))

        sm = sfn.StateMachine(
            self, "StateMachine",
            state_machine_name=self._state_machine_name,
            definition_body=sfn.DefinitionBody.from_chainable(init),
            # The per-GSI custom resource returns immediately (fire-and-forget),
            # so this timeout only needs to give same-table GSI serialization
            # room to complete on a slow account. It is bounded by the
            # stack-level GsiReadinessGate's WaitCondition (also 12h) — that's
            # what actually gates CloudFormation.
            timeout=self._state_machine_timeout,
        )
        sm.node.default_child.override_logical_id(
            stable_logical_id("SfnStateMachine", self._state_machine_name)
        )
        return sm


class GsiInfraCore(Construct):
    """Wires worker + state machine + onEvent + cr.Provider, and
    publishes the trigger and state machine ARNs on common_resources.

    Args:
      common_resources: any object with assignable attributes
        ``gsi_state_machine_arn`` and ``gsi_trigger_lambda_arn``. The
        orchestrator writes both on construction; ``ManagedTable`` reads
        them when emitting GSI custom resources. The ``prefix`` attribute
        (defaults to "" on a fresh ``CommonResources``) is prepended to
        every account-region-unique name the orchestrator allocates
        (Lambda functions, the Step Functions state machine). An itest
        fixture stack sets ``common_resources.prefix = "test-"`` so its
        resources coexist with a production deployment in the same account.

    The Lambdas are created via esp-cloud-common's own
    ``cdk.common.create_lambda_function``. Consumers don't need to inject
    a factory.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        common_resources,
    ) -> None:
        """
        Every ``Custom::GsiIndex`` is fire-and-forget: the custom resource
        returns as soon as the orchestrator execution is *started* (~1s), so
        no per-GSI CloudFormation timeout applies. The state machine still
        creates each GSI and serializes same-table builds via its retry
        loop (its timeout is 12h to allow this). Readiness is enforced at
        the stack level by a [GsiReadinessGate] (a native WaitCondition, up
        to 12h) — pair the two so "deploy complete" still means "GSIs
        queryable".
        """
        super().__init__(scope, id)

        prefix = getattr(common_resources, "prefix", "") or ""
        state_machine_name = f"{prefix}{STATE_MACHINE_NAME}"

        # The per-GSI custom resource doesn't bound the execution (fire-and-
        # forget), so the state machine must be free to serialize same-table
        # GSIs for as long as a slow control-plane takes; bound only by the
        # stack-level GsiReadinessGate's WaitCondition (12h).
        state_machine_timeout = Duration.hours(12)

        self.worker = GsiWorkerLambda(
            self, "Worker",
            common_resources=common_resources,
        )
        self.infra = GsiInfra(
            self, "Infra",
            worker_function=self.worker.function,
            state_machine_name=state_machine_name,
            state_machine_timeout=state_machine_timeout,
        )

        self.on_event = GsiTriggerOnEventLambda(
            self, "TriggerOnEvent",
            common_resources=common_resources,
            state_machine_arn=self.infra.state_machine_arn,
            state_machine_name=state_machine_name,
        )

        # No isComplete poller: the provider's onEvent Lambda is the only
        # handler, so the Custom::GsiIndex custom resource returns as soon
        # as the orchestrator execution starts. (query_interval/total_timeout
        # are omitted — they only apply to an isComplete waiter, which this
        # fire-and-forget provider has none of.)
        self.provider = create_cr_provider(
            self, "Provider",
            provider_name=f"{prefix}gsi-infra",
            on_event_handler=self.on_event.function,
            is_complete_handler=None,
        )

        common_resources.gsi_state_machine_arn = self.infra.state_machine_arn
        common_resources.gsi_trigger_lambda_arn = self.provider.service_token
