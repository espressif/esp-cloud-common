# gsi_infra

CDK constructs that **make DynamoDB GSI changes safe in CloudFormation**. Vanilla `AWS::DynamoDB::Table` returns `UPDATE_COMPLETE` while a GSI is still backfilling, so application queries against it return partial results. `gsi_infra` closes that window.

## What's in here

| Construct | Role |
|---|---|
| `GsiInfraCore` | One per stack. Provisions the orchestrator: a Step Functions state machine + worker Lambda that serializes all GSI create/delete operations on tables it manages. Exposes ARNs on `common_resources`. Every `Custom::GsiIndex` it creates is **fire-and-forget** — see [Readiness barrier](#readiness-barrier). |
| `ManagedTable` | Drop-in replacement for `aws_dynamodb.Table`. Each `add_global_secondary_index(...)` emits a `Custom::GsiIndex` resource that routes through the orchestrator instead of letting CFN handle the GSI inline. |
| `GsiReadinessGate` | The stack-level readiness barrier: a native **`AWS::CloudFormation::WaitCondition`** (up to **12h**), driven by a state machine. Instantiate once, last in the stack, after every `ManagedTable`. Holds `CREATE_COMPLETE`/`UPDATE_COMPLETE` until every table + GSI is `ACTIVE && !Backfilling`. |

### Readiness barrier

DynamoDB builds one online index per table at a time, so GSIs on the same table are created **strictly serially**. On an account with a slow control-plane, a table with several GSIs can take longer than CloudFormation's hard **~1h custom-resource ceiling** (`ServiceTimeout` max 3600s) — no restructuring *inside* a custom resource can beat that cap.

`gsi_infra` keeps the wait out of the custom-resource path entirely:

- Every `Custom::GsiIndex` is **fire-and-forget** — it returns as soon as the orchestrator execution *starts* (~1s). The state machine (timeout 12h) creates the GSI and serializes same-table builds via its retry loop; no per-GSI CloudFormation cap applies.
- `GsiReadinessGate` — instantiated once, last in the stack, after every `ManagedTable` — is the stack-level barrier. It runs a `Wait → check → Choice(ready?)` state machine and signals a native `WaitCondition` (up to 12h) once every table + GSI is `ACTIVE && !Backfilling`. The stack blocks on that `WaitCondition`, so `CREATE_COMPLETE`/`UPDATE_COMPLETE` still means "GSIs queryable".

The `GsiReadinessGate` `WaitCondition` handle/condition logical IDs carry a hash of the current `table:gsi` set: adding or removing a GSI mints a fresh `WaitCondition` that re-waits (and never consumes a stale signal from a prior deploy), while an unchanged GSI set reuses the already-satisfied one so a no-op redeploy completes immediately.

**Failure-mode tradeoff:** the readiness check detects terminally-failed GSI creates (bad KeySchema, missing `UpdateTable` permission, invalid index name, etc.) — when a per-GSI orchestrator execution reaches FAILED/TIMED_OUT/ABORTED, the gate signals FAILURE to the WaitCondition, rolling the stack back in minutes with the cause on the stack event. Exception: a `LimitExceededException` (per-table GSI count limit) is retried as transient by the worker, so the orchestrator never terminally fails and the gate waits out `wait_condition_timeout` (default 12h). That is a necessary cost of tolerating *valid* GSIs on a slow control-plane; such invalid definitions are config bugs a test deploy catches before customer rollout, and `wait_condition_timeout` is tunable.

## Architecture

```
GSI creation (fire-and-forget):

  ManagedTable.add_global_secondary_index(...)
      │
      ▼
  Custom::GsiIndex #1 ─┐ depends_on (chained, satisfies DDB's
                       │  "1 online GSI op per table" rule)
  Custom::GsiIndex #2 ─┘
      │ on Create/Update/Delete event
      ▼
  GsiInfraCore.provider (cr.Provider, onEvent only — no isComplete)
      │ StartExecution (~1s, then the custom resource returns SUCCESS)
      ▼
  Step Functions: gsi-infra   (timeout 12h)
      Init → DescribeTable → IsTableActive? → ApplyOperation → IsActive? → Done | wait→retry
      │ UpdateTable
      ▼
  gsi_worker Lambda (Go) ──────────────▶ DynamoDB


Readiness gate (stack-level, instantiated last):

  GsiReadinessGate
      │ StartExecution (~1s)
      ▼
  Trigger — AwsCustomResource (on_create + on_update; depends_on every ManagedTable)
      │
      ▼
  Step Functions: gsi-readiness   (timeout wait_condition_timeout + 1h, backstop only)

      CheckReady ──▶ AllGsisReady?
                        │
                        ├─ ready  ──▶ SignalSuccess ────────┐
                        ├─ failed ──▶ SignalCreateFailed ───┤
                        │                                   ▼
                        └─ else ──▶ Wait(query_interval)    AWS::CloudFormation::WaitCondition
                                       │                     (up to 12h) — gates CFN
                                       └──▶ back to CheckReady   CREATE/UPDATE_COMPLETE

  gsi_readiness_check Lambda:   DescribeTable on every expected table/GSI, plus
                                 (for one that isn't ACTIVE yet) DescribeExecution
                                 on the matching gsi-infra execution, to detect a
                                 terminal FAILED/TIMED_OUT/ABORTED create early.
  gsi_readiness_signal Lambda:  PUTs SUCCESS/FAILURE to the WaitCondition's
                                 pre-signed S3 URL.
```

**One fire-and-forget custom resource, one native WaitCondition:**

| Resource | Backed by | Lambdas | Purpose |
|---|---|---|---|
| `Custom::GsiIndex` (one per GSI) | `GsiInfraCore.provider` — `cr.Provider`, onEvent only | `gsi_trigger_onevent` + `gsi_worker` + state machine `gsi-infra` | Start an SFN execution that calls `UpdateTable` and returns success as soon as the execution *starts* (fire-and-forget). Chained sequentially via CDK `add_dependency` to satisfy DDB's "1 online GSI op per table" rule. |
| `AWS::CloudFormation::WaitCondition` (one per stack, per GSI-set digest) | `GsiReadinessGate` — an `AwsCustomResource` trigger + a native `WaitCondition` | `gsi_readiness_check` + `gsi_readiness_signal` + state machine `gsi-readiness` | Loop `DescribeTable` (and, for a GSI that isn't ready yet, the `gsi-infra` execution history) until every watched table + GSI is `ACTIVE && !Backfilling`, then signal the `WaitCondition`. |

**Deploy flow (CREATE):**

1. CFN creates the L1 DynamoDB table(s).
2. CFN creates each `Custom::GsiIndex` in dependency order. Each one starts a `gsi-infra` SFN execution and returns success as soon as `StartExecution` is accepted (typically <1s — doesn't wait for the GSI to become `ACTIVE`).
3. If `UpdateTable` is rejected with `LimitExceededException` (a prior GSI on the same table still building), the execution retries on a 60s/30s/30s curve, bounded by the state machine's 12h timeout.
4. After every table and `Custom::GsiIndex` is created, `GsiReadinessGate`'s Trigger starts the `gsi-readiness` state machine, which polls every watched table/GSI every `query_interval` (default 30s) until all are `ACTIVE && !Backfilling`, then PUTs a SUCCESS signal to the native `WaitCondition`.
5. CFN was blocking on that `WaitCondition` (up to `wait_condition_timeout`, default and max 12h); `cdk deploy` returns once it's signaled. App code can issue GSI queries safely.

**Why the orchestrator and the readiness gate are separate constructs:** the orchestrator is per-GSI (so failures map cleanly to the offending GSI's own SFN execution) and fire-and-forget (no CloudFormation timeout applies to it — it returns before the GSI even starts building). The readiness gate is per-stack (so it can sweep every table + GSI at the end) and needs a timeout budget (up to 12h) far beyond what any CloudFormation custom resource allows (~1h `ServiceTimeout`) — hence the native `WaitCondition` instead of a second custom resource. They share nothing at runtime except the `ManagedBy=gsi-infra` IAM tag scope.

## Usage

```python
from gsi_infra import GsiInfraCore, ManagedTable, GsiReadinessGate

class MyStack(Stack):
    def __init__(self, scope, id, *, common_resources, **kwargs):
        super().__init__(scope, id, **kwargs)

        # 1. Orchestrator (once per stack)
        self.gsi_infra = GsiInfraCore(
            self, "GsiInfra",
            common_resources=common_resources,
        )

        # 2. Tables — use ManagedTable, not aws_dynamodb.Table
        users = ManagedTable(
            self, "Users",
            common_resources=common_resources,
            table_name="users",
            partition_key=...,
            billing_mode=BillingMode.PAY_PER_REQUEST,
        )
        users.add_global_secondary_index(
            index_name="users_by_email",
            partition_key=...,
        )

        # 3. Readiness barrier (last construct in the stack, after every ManagedTable)
        self.gsi_readiness_gate = GsiReadinessGate(
            self, "GsiReadinessGate",
            common_resources=common_resources,
            # wait_condition_timeout=Duration.hours(12),  # default & max; lower it to fail faster
        )
```

`common_resources` is any object with assignable attributes; `GsiInfraCore` writes `gsi_state_machine_arn` and `gsi_trigger_lambda_arn` on it, which `ManagedTable` reads. `GsiReadinessGate` only reads `common_resources.prefix` (to namespace its Lambdas/state machine) — it writes nothing back.

### Application-side gate (Go)

Application Lambdas should still gate every GSI Query/Scan on the runtime helper. `GsiReadinessGate` is a deploy-time barrier — its `WaitCondition` digest changes (and it re-polls) whenever the tracked GSI set changes, so it does cover a GSI added on an UPDATE deploy, not just the initial CREATE — but it has no visibility into anything that touches DynamoDB outside `gsi_infra` (a manual console change, a table managed by a different stack, etc.):

```go
import (
    cc_ddb "github.com/espressif/esp-cloud-common/go/aws_services/ddb"
)

ok, err := cc_ddb.IsGSIActive(ctx, ddbClient, "users", "users_by_email")
if !ok || err != nil {
    return notReadyResponse, err
}
// safe to issue Query against users_by_email
```

`IsGSIActive` calls `DescribeTable` once per process per (table, index) and caches `true` in a sticky env var. After the first hit, every subsequent call is zero-overhead.

## Performance characteristics

Measured 2026-05-08 against a real account (`ap-south-1`), empty PAY_PER_REQUEST table — this predates the fire-and-forget-only refactor, so the run still used the (now-removed) two-mode design's polling machinery. The overall wall-clock numbers are dominated by AWS's own warm-throughput floor, which the readiness-barrier mechanism doesn't change, but the phase breakdown below hasn't been re-measured against the current single-mode design; treat it as directionally representative rather than exact.

### CREATE: 1 table + 2 GSIs (12m 02s)

| Phase | Duration | What's happening |
|---|---|---|
| Stack init + table create | 22s | CFN baseline + `CreateTable` (empty PAY_PER_REQUEST) |
| **Provider framework setup** | **2m 30s** | CDK `cr.Provider`/`AwsCustomResource` machinery for `GsiInfraCore` and `GsiReadinessGate` (~6 internal resources, sequential). First-deploy cost only. |
| GsiIndex #1 (orchestrator, fire-and-forget) | 7s | SFN: describe → `UpdateTable` accepted → done. |
| GsiIndex #2 (waits for #1) | **5m 01s** | DDB rejects 2nd `UpdateTable` with `LimitExceededException` until #1 finishes warm-throughput provisioning. SFN retries on a 60s/30s/30s curve. |
| `GsiReadinessGate` polls for ACTIVE | **4m 01s** | Polls `DescribeTable` every `query_interval` (30s default). Bounded by AWS-side warm-throughput floor for #2. |
| `CREATE_COMPLETE` | — | All GSIs queryable. |

### CREATE: 1 table + 1 GSI (7m 11s)

| Phase | Duration |
|---|---|
| Stack init + table create | 22s |
| Provider framework setup | 2m 30s |
| GsiIndex #1 (orchestrator) | 7s |
| `GsiReadinessGate` polls for ACTIVE | **4m 11s** |

### UPDATE: drift-recreate idx_a + add idx_c + remove idx_b (9m 02s)

| Phase | Duration | What's happening |
|---|---|---|
| idx_a drift-recreate (delete-then-create) | 40s | Worker issues `Delete`, polls until gone, issues `Create` — fire-and-forget. |
| idx_c (waits for idx_a) | 4m 20s | Same `LimitExceededException` retry path as CREATE. |
| idx_b DELETE | **3m 50s** | AWS warm-throughput *de-allocation*; same floor as create. |

`GsiReadinessGate`'s `WaitCondition` digest changes whenever the tracked GSI set changes (idx_c added, idx_b removed here), so it always mints a fresh `WaitCondition` and re-polls on a scenario like this — the added wall-clock is at most one extra `query_interval` tick layered on top of idx_b's own delete-completion polling above, not a separately-measured phase.

### What's reducible

| Cost | Floor | Reducible? |
|---|---|---|
| AWS warm-throughput provisioning | ~5 min/GSI on PAY_PER_REQUEST tables | **No** — AWS-side, even on empty tables |
| 1-online-GSI-op-per-table serialization | inherent | **No** — DDB hard rule |
| CDK Provider/AwsCustomResource framework setup | 2m 30s on first stack create | Hard — built-in CDK overhead |
| `GsiReadinessGate` poll cadence | `query_interval`, default 30s | Tunable at construction; lower values poll more often but don't change the underlying floor |

For multi-GSI deploys on the same table, total wait scales **linearly** with N (5 min × N), because DDB serializes them. GSIs across *different* tables run in parallel.

## Timeouts

| Layer | Value | Set in | If it fires |
|---|---|---|---|
| CFN stack | none by default | `TimeoutInMinutes` on `create-stack` | Whole-stack roll-back |
| `gsi_trigger_onevent` Lambda | 30s | [lambdas/gsi_trigger_onevent/stack.py](lambdas/gsi_trigger_onevent/stack.py) | Fails the `Custom::GsiIndex` resource directly — this runs *before* the SFN execution even starts, so a failure here means the GSI was never queued. SDK retries (adaptive) usually absorb transients first. |
| `gsi-infra` state machine (per-GSI create/delete + same-table serialization) | 12h | [base.py#L211](base.py#L211) | Execution status = `TIMED_OUT`. Invisible to CloudFormation on its own (fire-and-forget — the custom resource already returned); surfaces only if `GsiReadinessGate`'s check detects the terminal status. |
| `gsi_worker` Lambda | 60s | [lambdas/gsi_worker/stack.py](lambdas/gsi_worker/stack.py) | SDK retries (adaptive, MaxAttempts=5, MaxBackoff=5s — see [go/aws_services/awsconfig](../../go/aws_services/awsconfig/awsconfig.go)) usually handle transients before this hits |
| `gsi_readiness_check` Lambda | 120s | [lambdas/gsi_readiness_check/stack.py](lambdas/gsi_readiness_check/stack.py) | Retried (`States.TaskFailed`, 5 attempts), then signals FAILURE — a broken check fails the stack instead of hanging it for 12h |
| `gsi_readiness_signal` Lambda | 30s | [lambdas/gsi_readiness_signal/stack.py](lambdas/gsi_readiness_signal/stack.py) | Same retry-then-fail-fast handling as the check Lambda |
| `gsi-readiness` state machine | `wait_condition_timeout` + 1h | [readiness_gate.py#L208](readiness_gate.py#L208) | Backstop only: it's built to outlive the `WaitCondition`, so the `WaitCondition` — not an orphaned SFN `TIMED_OUT` — is what CloudFormation actually observes |
| `AWS::CloudFormation::WaitCondition` | `wait_condition_timeout`, default & max **12h** | `GsiReadinessGate(wait_condition_timeout=...)` | This is what actually gates the stack: no SUCCESS signal in time → CFN fails the resource → stack rolls back |

Unlike a nested "nearest layer times out first" design, the `gsi-infra` state machine (12h) and the `GsiReadinessGate` `WaitCondition` (12h by default) are two independent clocks that start around the same moment — either can fire first depending on which table/GSI is slow. Neither should legitimately run anywhere close to 12h in practice; that ceiling exists to tolerate the `LimitExceededException` retry case (see [Readiness barrier](#readiness-barrier)), not because GSI builds routinely take that long.

## Risks / edge cases

1. **`GsiReadinessGate`'s `WaitCondition` caps at 12h (AWS hard limit).** That's generous enough for DDB's own per-table GSI serialization (~5min × N), but an exceptionally large single GSI build, or a very large batch of GSIs added in one deploy, could in theory still exceed it. For a build you expect to run close to 12h, do a two-phase deploy (GSI in one PR, dependent code in the next) rather than relying on the gate alone.
2. **Auto-scan is order-sensitive.** `GsiReadinessGate` scans the construct tree at `__init__` time. It must be instantiated *after* every `ManagedTable` it should gate on — tables added later are silently missed (it raises if it finds none at all, but can't detect "found some, missing more"). Place it last in your stack's `__init__`.
3. **Timeout during backfill = partial DDB state on rollback.** If the `WaitCondition` times out while a GSI is still backfilling, CFN rolls back — but DDB keeps backfilling the GSI to completion regardless. The next deploy sees an existing GSI and the orchestrator's drift-recreate path triggers a ~5min delete+recreate. Loud and recoverable, but slow.
4. **Lambda concurrency caps.** Account-wide unreserved Lambda concurrency (default 1000) is shared with everything else. A burst of retried `gsi_readiness_check`/`gsi_readiness_signal` invocations during a stack rollback can momentarily contend with normal traffic. In practice not a problem; flag if you see throttling on prod Lambdas during stack churn.

## Known issues (tracked)

See [TODO.md](TODO.md) for: progress-driven backoff (CloudWatch `OnlineIndexPercentageProgress` instead of fixed cadence).

## Internals

- **`gsi-infra` state machine** ([base.py](base.py)): `Init → DescribeTable → IsTableActive? → ApplyOperation → IsActive? → Done|wait→retry`. Worker is fire-and-forget on Create/Delete; retries handle `LimitExceededException` and `ResourceInUseException`. Timeout: 12h ([base.py#L211](base.py#L211)).
- **`gsi-readiness` state machine** ([readiness_gate.py](readiness_gate.py)): `CheckReady → Choice(ready? / failed? / else Wait→retry) → SignalSuccess | SignalFailure | SignalCreateFailed`. Timeout: `wait_condition_timeout` + 1h (backstop only — see [Timeouts](#timeouts)).
- **Worker Lambda** ([lambdas/gsi_worker/](lambdas/gsi_worker/)): Go, single-purpose, IAM-scoped via `ManagedBy=gsi-infra` resource tag.
- **Trigger Lambda** ([lambdas/gsi_trigger_onevent/](lambdas/gsi_trigger_onevent/)): bridges the `Custom::GsiIndex` CFN event to a `StartExecution` call and returns immediately — no isComplete companion.
- **Readiness Lambdas** ([lambdas/gsi_readiness_check/](lambdas/gsi_readiness_check/), [lambdas/gsi_readiness_signal/](lambdas/gsi_readiness_signal/)): `check` polls `DescribeTable` on every expected table/GSI each state-machine iteration (and, for one that isn't ready yet, the matching `gsi-infra` execution's status, to detect a terminal failure early); `signal` PUTs SUCCESS/FAILURE to the `WaitCondition`'s pre-signed URL.
- **Tag-scoped IAM**: workers can only touch tables tagged `ManagedBy=gsi-infra` (applied automatically by `ManagedTable`).

## Testing

```bash
make test                       # Go unit tests, no AWS
RUN_GSI_INFRA_ITEST=true make itest   # real CFN deploys, ~50 min
```

Integration tests opt-in only; they create + destroy real CFN stacks and pay the per-deploy times shown above.
