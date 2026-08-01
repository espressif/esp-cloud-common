"""End-to-end integration tests for the GSI orchestrator.

The fixture stack is self-contained: it instantiates the orchestrator,
the ManagedTable, and a set of GSIs in one stack. Each scenario invokes
``cdk deploy`` to create or update the stack (CDK uploads Lambda assets
and creates/updates the CloudFormation stack as one operation), then
``cdk destroy`` to tear it down.

Scenarios:
  * deploy 1 table + 2 GSIs, then update CFN to update 1 GSI + delete 1 GSI
  * deploy 1 table + 1 GSI, fire-and-forget leaves DDB busy, deploy a 2nd
    GSI on the busy table, then delete the stack
  * deploy fire-and-forget + GsiReadinessGate with 1 deliberately-invalid
    GSI — proves the gate fails the deploy fast instead of waiting out its
    WaitCondition timeout

Tests are SLOW. Each `cdk deploy` waits for CloudFormation, which itself
waits for DynamoDB to provision a GSI — empty PAY_PER_REQUEST tables
still pay a 5-15 minute floor on warm-throughput provisioning per GSI
op (and the suite does multiple ops per test, plus teardown). A full
`make itest` run is ~50 minutes (most recently measured: 48m28s).

Skipped unless RUN_GSI_INFRA_ITEST=true. Opt in deliberately:

    RUN_GSI_INFRA_ITEST=true \\
    pytest cdk_go/gsi_infra/itests/test_gsi_infra.py -v -s

Region comes from ``AWS_REGION`` / ``AWS_DEFAULT_REGION`` env vars (or
``us-east-1`` as a last-resort default). Run ``make setup`` once per
AWS account/region to bootstrap CDK with the ``cc-itest`` qualifier
before the first ``make itest``.
"""
import os
import subprocess
import time
from pathlib import Path

import boto3
import pytest


REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

THIS_DIR = Path(__file__).resolve().parent
APP_PATH = THIS_DIR / "example_stack/app.py"
STACK_NAME = "gsi-infra-itest"
TABLE_NAME = "gsi_infra_itest"

SCENARIO_INITIAL = "initial"
SCENARIO_UPDATED = "updated"
SCENARIO_ONE_GSI = "one_gsi"
SCENARIO_ONE_GSI_PLUS_C = "one_gsi_plus_c"
SCENARIO_FF_INVALID = "ff_invalid"

TABLE_STATE_TIMEOUT_SECONDS = 60 * 30
CDK_DEPLOY_TIMEOUT_SECONDS = 60 * 60  # 1h — covers DDB GSI build time
# ff_invalid must fail well inside this to prove "fast", not "eventually
# within the 1h CDK_DEPLOY_TIMEOUT_SECONDS ceiling". The stack's own
# GsiReadinessGate uses a 30min WaitCondition timeout (see
# example_stack/stack.py); this generous margin only needs to rule out
# "it silently waited out the WaitCondition" (would land near 30min).
FAST_FAIL_TIMEOUT_SECONDS = 60 * 20
# Lower floor for the same assertion: a deploy that fails in a few seconds
# never reached the deploy/worker/readiness cascade at all (e.g. a synth-time
# exception or a CLI/bootstrap/IAM error) — that's a different failure than
# the one this test exists to prove, so treat it as a false pass, not a win.
FAST_FAIL_FLOOR_SECONDS = 30

# Duplicated from example_stack/stack.py (not imported — that module is
# invoked as a `cdk` subprocess app, not imported directly). The ff_invalid
# GSI has a valid, short index name (so it does NOT blow CloudFormation's
# 255-char logical-ID limit) but a bad KeySchema (same attribute for HASH and
# RANGE), which DynamoDB rejects at UpdateTable. Used as a causation marker:
# the readiness check's failure reason ("<table>/<index>: execution ...")
# echoes this index name back in cdk's output.
FF_INVALID_INDEX_NAME = "idx_ff_invalid"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GSI_INFRA_ITEST") != "true",
    reason="Set RUN_GSI_INFRA_ITEST=true to run; deploys real CFN stacks",
)


def _ddb():
    return boto3.client("dynamodb", region_name=REGION)


def _cdk(*args: str, scenario: str = None, capture: bool = False):
    """Invoke `cdk <args>` against the fixture app. The scenario env var
    flows through to the CDK app so the synthesized template reflects
    the right GSI declarations.

    By default (capture=False, used by every existing scenario) this
    streams cdk's console output live to the test session and raises
    ``subprocess.CalledProcessError`` on a non-zero exit — unchanged
    behavior. ``capture=True`` is an opt-in used only by the fast-fail
    causation test below: it captures combined stdout+stderr instead of
    streaming it and returns the ``CompletedProcess`` without raising,
    so the caller can inspect ``returncode``/``stdout``/``stderr`` itself.
    """
    env = os.environ.copy()
    if scenario is not None:
        env["GSI_INFRA_SCENARIO"] = scenario
    cmd = [
        "cdk", *args,
        "--app", f"python3 {APP_PATH}",
        "--require-approval", "never",
        STACK_NAME,
    ]
    print(f"\n→ {' '.join(cmd)}")
    if capture:
        return subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=CDK_DEPLOY_TIMEOUT_SECONDS,
        )
    subprocess.run(cmd, env=env, check=True, timeout=CDK_DEPLOY_TIMEOUT_SECONDS)


def _deploy(scenario: str) -> None:
    _cdk("deploy", scenario=scenario)


def _destroy() -> None:
    # `cdk destroy --force` skips the confirmation prompt and exits 0
    # even when the stack doesn't exist, which matches the existing
    # boto3-based teardown's idempotence.
    _cdk("destroy", "--force")


def _gsis() -> dict:
    desc = _ddb().describe_table(TableName=TABLE_NAME)["Table"]
    return {g["IndexName"]: g for g in desc.get("GlobalSecondaryIndexes") or []}


def _wait_for_table_active():
    deadline = time.time() + TABLE_STATE_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            desc = _ddb().describe_table(TableName=TABLE_NAME)["Table"]
        except _ddb().exceptions.ResourceNotFoundException:
            return
        if desc["TableStatus"] == "ACTIVE" and all(
            g.get("IndexStatus") == "ACTIVE" for g in (desc.get("GlobalSecondaryIndexes") or [])
        ):
            return
        time.sleep(10)
    pytest.fail(f"table {TABLE_NAME} did not return to ACTIVE within {TABLE_STATE_TIMEOUT_SECONDS}s")


@pytest.fixture
def deploy_stack():
    """Yields a `deploy(scenario)` callable that creates or updates the
    fixture stack via `cdk deploy`. Always tears the stack down on
    teardown so failed tests don't leak resources."""
    def deploy(scenario: str) -> None:
        _deploy(scenario)

    try:
        yield deploy
    finally:
        try:
            _destroy()
        except Exception as e:
            print(f"warning: teardown cdk destroy failed: {e}")


def test_deploy_two_gsis_then_update_one_and_delete_one(deploy_stack):
    """Deploy with 2 GSIs, then update CFN with idx_a recreated + idx_b
    removed + idx_c added. End state: idx_a (new key) + idx_c.

    Wall-clock: ~30 minutes. Two `cdk deploy` calls
    (initial + updated scenarios) each create/update GSIs whose builds
    are gated on DDB warm-throughput provisioning, plus a final
    `_wait_for_table_active` and stack teardown. The drift-recreate of
    idx_a inside the updated scenario is the slowest leg (Delete→Create
    back to back).
    """
    deploy_stack(SCENARIO_INITIAL)
    gsis = _gsis()
    assert set(gsis) == {"idx_a", "idx_b"}
    assert gsis["idx_a"]["KeySchema"] == [{"AttributeName": "a_key_v1", "KeyType": "HASH"}]
    # GsiReadinessGate contract: when `cdk deploy` returns, every GSI is
    # already ACTIVE && !Backfilling. The fixture stack wires GsiReadinessGate
    # at the end, so this should hold without _wait_for_table_active.
    for name, g in gsis.items():
        assert g["IndexStatus"] == "ACTIVE", f"{name}: status={g['IndexStatus']!r}"
        assert not g.get("Backfilling", False), f"{name}: still backfilling"

    deploy_stack(SCENARIO_UPDATED)
    # Right work started: with fire-and-forget, deploy_stack returns while
    # DDB is mid-mutation OR after it's already settled. Each assertion
    # accepts both — the in-flight status (proves orchestrator kicked off
    # the op) and the final-state shape (proves it already finished).
    gsis = _gsis()
    # idx_b: deleting now, or already gone.
    assert "idx_b" not in gsis or gsis["idx_b"]["IndexStatus"] == "DELETING", \
        f"idx_b should be DELETING or absent, got {gsis.get('idx_b', {}).get('IndexStatus')!r}"
    # idx_c: creating now, or already active.
    assert gsis["idx_c"]["IndexStatus"] in ("CREATING", "ACTIVE"), \
        f"idx_c should be CREATING or ACTIVE, got {gsis['idx_c']['IndexStatus']!r}"
    # idx_a: mid drift-recreate (DELETING old v1, or briefly absent between
    # delete-finish and re-create, or CREATING/ACTIVE with v2 key).
    if "idx_a" in gsis:
        st = gsis["idx_a"]["IndexStatus"]
        assert st in ("DELETING", "CREATING", "ACTIVE")
        if st in ("CREATING", "ACTIVE"):
            assert gsis["idx_a"]["KeySchema"] == [{"AttributeName": "a_key_v2", "KeyType": "HASH"}], \
                "idx_a Create didn't use the new v2 key — drift-recreate didn't trigger"

    # End-state sanity: once DDB settles, the desired final shape holds.
    _wait_for_table_active()
    gsis = _gsis()
    assert set(gsis) == {"idx_a", "idx_c"}, f"unexpected end state: {set(gsis)}"
    assert gsis["idx_a"]["KeySchema"] == [{"AttributeName": "a_key_v2", "KeyType": "HASH"}]


def test_busy_update_then_destroy(deploy_stack):
    """Add one GSI via CFN while the table is still UPDATING from a
    prior fire-and-forget GSI op (idx_a still CREATING in DDB after
    deploy_stack returns). Orchestrator's WaitTableActive must hold
    until DDB is free, then add idx_c. Stack delete tears everything
    down.

    Wall-clock: ~20 minutes. Two `cdk deploy` calls
    plus stack destroy; the second deploy is the interesting one because
    it lands on a busy table and the orchestrator's wait-for-active loop
    kicks in before idx_c can be added.
    """
    deploy_stack(SCENARIO_ONE_GSI)

    # First deploy returns immediately under fire-and-forget while idx_a
    # is still CREATING in DDB. The second deploy therefore lands on a
    # busy table, exercising the orchestrator's wait-for-free path.
    deploy_stack(SCENARIO_ONE_GSI_PLUS_C)
    # Right work started: idx_c create kicked off on the still-busy table.
    gsis = _gsis()
    assert gsis["idx_c"]["IndexStatus"] in ("CREATING", "ACTIVE"), \
        f"idx_c should be CREATING or ACTIVE, got {gsis.get('idx_c', {}).get('IndexStatus')!r}"
    assert "idx_a" in gsis

    _destroy()
    _wait_for_table_active()
    with pytest.raises(_ddb().exceptions.ResourceNotFoundException):
        _ddb().describe_table(TableName=TABLE_NAME)


def test_invalid_gsi_fails_fast_under_readiness_gate(deploy_stack):
    """A deliberately-invalid GSI must fail the deploy fast via the
    GsiReadinessGate, not hang until its WaitCondition timeout — AND the
    failure must be attributable to that gate detecting the bad GSI, not to
    some unrelated fast failure (a synth-time exception, a bootstrap/IAM
    error, ...) that would also exit non-zero quickly and so would wrongly
    satisfy a speed-only check while proving nothing about the readiness
    gate.

    The ff_invalid scenario (see example_stack/stack.py) wires
    ``GsiInfraCore`` (fire-and-forget is the only mode) + ``GsiReadinessGate(...,
    wait_condition_timeout=Duration.minutes(30))`` and declares one GSI whose
    KeySchema reuses the same attribute for both the HASH and RANGE key — a
    shape CDK/CloudFormation synth without complaint (a valid, short index name
    keeps the logical resource ID well under CloudFormation's 255-char limit),
    but that DynamoDB rejects with a ValidationException once the request
    reaches it. (An over-long *index name* would NOT work here: ManagedTable
    folds the index name into the logical ID, so a >255-char name fails the
    CFN template at changeset time — in seconds, before the worker/gate ever
    run — which leg 2's lower time-bound correctly rejects.)

    Expected causal chain: the Custom::GsiIndex resource returns immediately
    (fire-and-forget), the per-GSI orchestrator's UpdateTable call gets back
    a ValidationException from DynamoDB, the Go worker surfaces that as a
    hard error, the state machine execution reaches a terminal FAILED status,
    GsiReadinessGate's readiness-check Lambda detects that FAILED execution
    (see check_task.add_catch / the "$.check.failed" Choice branch in
    gsi_infra/readiness_gate.py) and signals FAILURE on the WaitCondition,
    and `cdk deploy` exits non-zero (stack rolls back) — well inside minutes,
    not the 30-minute WaitCondition timeout the fixture configures (let alone
    the 12h default).

    This test verifies all three legs of that claim instead of just the
    "exits non-zero, and quickly" shape any unrelated fast failure would
    also produce:
      1. the deploy failed (non-zero exit);
      2. it failed fast (< FAST_FAIL_TIMEOUT_SECONDS) but not suspiciously
         fast (> FAST_FAIL_FLOOR_SECONDS) — the floor rules out a trivial
         immediate crash (e.g. synth) that never reached the deploy/worker/
         readiness cascade at all;
      3. the captured output actually names the intended cause — the
         ff_invalid index name or "execution" (both embedded in the readiness
         check's failure reason, "<table>/<index>: execution <arn> ..."), or
         "gsireadiness" (the gate's WaitCondition logical ID, which CFN reports
         as the failed resource on rollback) — see readiness_gate.py /
         lambdas/readiness.go.

    Unlike every other scenario in this module, this test invokes `cdk
    deploy` itself via ``_cdk(..., capture=True)`` (not through the
    `deploy_stack` fixture's `deploy()` helper) so it can capture combined
    stdout+stderr to inspect for (3), instead of streaming it live and
    discarding it. The `deploy_stack` fixture is still used so its teardown
    (`_destroy()`) runs unconditionally, matching every other test.

    DEPLOY-GATED: like every test in this module, skipped unless
    RUN_GSI_INFRA_ITEST=true (real AWS deploy, real DynamoDB
    ValidationException). Not executed in a synth-only environment — verify
    the wiring there with a synth of GSI_INFRA_SCENARIO=ff_invalid instead
    (confirms the gate's state machine + the duplicate-key invalid GSI both
    make it into the template).
    """
    start = time.time()
    result = _cdk("deploy", scenario=SCENARIO_FF_INVALID, capture=True)
    elapsed = time.time() - start

    combined = f"{result.stdout}\n{result.stderr}"
    tail = combined[-4000:]

    assert result.returncode != 0, (
        f"expected `cdk deploy` to fail for the {SCENARIO_FF_INVALID!r} "
        f"scenario, but it exited 0. Output tail:\n{tail}"
    )

    assert elapsed < FAST_FAIL_TIMEOUT_SECONDS, (
        f"deploy took {elapsed:.0f}s (>= {FAST_FAIL_TIMEOUT_SECONDS}s) — "
        "the readiness gate should fail fast via the SFN check, not wait "
        "out the WaitCondition timeout"
    )
    assert elapsed > FAST_FAIL_FLOOR_SECONDS, (
        f"deploy failed in only {elapsed:.0f}s (<= {FAST_FAIL_FLOOR_SECONDS}s) "
        "— too fast to have reached the deploy/worker/readiness cascade at "
        "all, which suggests a trivial synth-time or CLI/bootstrap failure "
        f"unrelated to the readiness gate. Output tail:\n{tail}"
    )

    # Markers specific to the readiness-gate failure path: the readiness
    # check's reason ("<table>/<index>: execution <arn> ...") echoes the index
    # name and "execution", and CFN reports the gate's WaitCondition logical ID
    # (starts with "GsiReadiness") as the failed resource on rollback. "gsi" and
    # "createfailed" are excluded — "gsi" is in STACK_NAME (appears regardless of
    # cause), and "createfailed" is an internal SFN state name unlikely to
    # surface in cdk's output.
    markers = (FF_INVALID_INDEX_NAME.lower(), "execution", "gsireadiness")
    combined_lower = combined.lower()
    assert any(m in combined_lower for m in markers), (
        "deploy failed, and fast — but none of the expected causation "
        f"markers {markers!r} appeared anywhere in the captured output, so "
        "this failure can't be attributed to the GsiReadinessGate detecting "
        f"the invalid GSI. Output tail:\n{tail}"
    )
