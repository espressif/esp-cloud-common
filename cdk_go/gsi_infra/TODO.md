# GSI Infra TODO

### Dynamic poll cadence

```
1. Initial wait = max(30s, est_total_sec / 10)   # est from table_size_GB and GSI WCU
2. Poll DescribeTable; read progress % from CloudWatch
3. If progress available: next_wait = clamp(elapsed * (100-p)/p * 0.5, 30s, 5min)
   Else:                  next_wait = prev_wait * 1.5
4. Terminal: IndexStatus=ACTIVE && Backfilling=false
```

Rough rate-of-thumb: **~1 GB / min / 1000 GSI WCU**.

### Behavior on a 10 GB table @ 1000 GSI WCU

~10 min total backfill, first poll at ~60s, ~6–8 `DescribeTable` calls before ACTIVE. `DescribeTable` is free; CloudWatch `GetMetricStatistics` is sub-cent at this volume — total readiness-check cost ≈ $0.

### Notes

- `OnlineIndexPercentageProgress` only emits while backfill is running; once done it disappears. Don't use it as the terminal condition — use `DescribeTable`.
- A freshly-created GSI has auto-scaling **disabled** until backfill completes. For faster/cheaper backfill, provision high WCU during creation, drop it after ACTIVE, then re-enable auto-scaling.
- DynamoDB allows only one GSI create/delete per `UpdateTable`. Multiple GSIs must be serialized by the custom resource / state machine.

## Future: progress-driven backoff for GsiReadinessGate

Currently `GsiReadinessGate`'s readiness state machine waits a fixed `query_interval` (default 30s — see `WaitForGsis` in `readiness_gate.py`) between `CheckReady` polls. It works but overshoots near the end — if backfill finishes mid-window, we discover ~1 poll late. Smarter alternative: drive the next-poll interval from real backfill progress, switching `WaitForGsis` from a fixed `Duration` to `sfn.WaitTime.seconds_path(...)` fed by the check Lambda's response.

```
At each real check:
  read OnlineIndexPercentageProgress for each backfilling GSI
  remaining_pct  = 100 - max(progresses)
  elapsed        = now - deploy_start_time
  eta_seconds    = elapsed * remaining_pct / (100 - remaining_pct)
  next_skip      = clamp(eta_seconds * 0.5 / 10, 0, 60)  # poll at half the ETA, capped
```

Self-correcting: speeds up if backfill is faster than expected, slows down if not.

### Implementation notes / gotchas

- Add `cloudwatch:GetMetricData` to the `gsi_readiness_check` Lambda's IAM (scoped to `arn:aws:cloudwatch:*:*:metric/AWS/DynamoDB/OnlineIndexPercentageProgress` if AWS supports resource-level perms here; otherwise `*`).
- `OnlineIndexPercentageProgress` only emits during active backfill, so the **terminal** check must still be `DescribeTable` for `IndexStatus=ACTIVE && Backfilling=false`. Don't infer "done" from "metric absent" — could just be a publish lag.
- CloudWatch metric has ~1 min publish lag, so very-fast GSIs (small tables) finish before any data point lands. Combine with a minimum-poll-interval floor (e.g., 10s) so the trivial case stays fast.
- Persist `deploy_start_time` in the state machine execution's own JSON state — set once in the `Trigger`'s initial input alongside `expected`/`signal_url` (there's no Provider `Data` field to piggyback on; `GsiReadinessGate` has no isComplete waiter).
- Keep the fixed-interval path as a fallback when the metric API errors (don't fail the deploy on a CloudWatch hiccup).
