# aws-cleanup

Generic AWS account cleanup tool. Sweeps an account, deleting resources across
many AWS services. **Destructive — always run with `--dry-run` first.**

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Preview what a full sweep would touch
AWS_PROFILE=sandbox python3 aws_cleanup.py --region us-east-1 --dry-run

# Run a real sweep, protecting publish/release buckets
AWS_PROFILE=sandbox python3 aws_cleanup.py --region us-east-1 \
  --protect-bucket-prefix publish- \
  --protect-bucket-prefix my-product-

# Just one service
python3 aws_cleanup.py --service iam --dry-run

# Multiple specific services
python3 aws_cleanup.py --service iam --service lambda --dry-run
```

See `python3 aws_cleanup.py --help` for the full flag set.

## Supported services

| Service          | Notes                                                                  |
|------------------|------------------------------------------------------------------------|
| `cloudformation` | Stacks (with termination protection disabled) and stack sets (with their instances). |
| `apigateway`     | REST (v1) + HTTP/WebSocket (v2) APIs, usage plans, API keys, custom domains, client certificates. |
| `appsync`        | GraphQL APIs.                                                          |
| `stepfunctions`  | State machines, activities.                                            |
| `ecs`            | Services drained, tasks stopped, clusters deleted, task defs deregistered. |
| `sagemaker`      | Endpoints, endpoint configs, models, pipelines, feature groups, notebook instances, Studio domains + apps + user profiles, inference components. Stops in-progress training/processing/transform jobs. |
| `emr`            | EMR classic clusters (terminated) and EMR Serverless applications.     |
| `bedrock`        | Custom models, knowledge bases (and their data sources), agents, guardrails, provisioned throughput. |
| `codesuite`      | CodeBuild projects + source credentials, CodePipeline pipelines, CodeCommit repositories, CodeDeploy applications + custom deployment configs, CodeArtifact domains + repositories. |
| `quicksight`     | Dashboards, analyses, datasets, data sources, themes, folders.         |
| `lambda`         | Functions.                                                             |
| `ec2`            | Instances, capacity reservations, NAT gateways, network interfaces, launch templates, placement groups, EBS volumes/snapshots, AMIs, key pairs, unassociated EIPs. Skips VPC. |
| `eventbridge`    | Rules (with targets removed), non-default buses, archives, replays, connections, API destinations, and Scheduler schedules + groups. |
| `sqs`            | Queues.                                                                |
| `sns`            | Topics, subscriptions, platform applications, endpoints.               |
| `ses`            | SES v1 and SESv2: identities, configuration sets, templates, contact lists, receipt rule sets, custom verification templates. |
| `kinesis`        | Data Streams, Firehose delivery streams, Video Streams, Managed Service for Apache Flink applications. |
| `glue`           | Triggers, workflows, ML transforms, jobs, crawlers, connections, databases (cascades to tables), schema registries. |
| `athena`         | Named queries, workgroups (skips `primary`).                           |
| `rds`            | Proxies, DB instances, clusters, manual snapshots, event subscriptions, parameter/cluster-parameter/option/subnet groups (skipping defaults). |
| `elasticache`    | Replication groups, cache clusters, manual snapshots, user groups, users, parameter/subnet groups. |
| `dynamodb`       | Tables.                                                                |
| `opensearch`     | Managed domains and OpenSearch Serverless collections + security/access policies + VPC endpoints. |
| `cognito`        | User pools (with domains) and identity pools (separate API).           |
| `iot`            | Jobs, topic rules, things, thing groups, billing groups, thing types, certificates, policies, fleet provisioning templates, domain configurations, custom authorizers. |
| `wafv2`          | Web ACLs, rule groups, IP sets, regex pattern sets — REGIONAL + CLOUDFRONT scopes. |
| `cloudfront`     | Distributions, FLE configs, OAIs, OACs, cache/origin-request/response-headers policies, functions, KeyValueStores. |
| `acm`            | Public certificates and ACM PCA private CAs (disabled then scheduled for permanent deletion in 7 days). |
| `route53`        | Hosted zones — empties all records first (keeping apex SOA/NS), then deletes the zone. Filter with `--route53-zone-include-suffix`. |
| `cloudwatch`     | Log groups, alarms (metric + composite), dashboards, insight rules, Synthetics canaries. |
| `s3`             | Buckets — versioned objects emptied first.                             |
| `ecr`            | Private + public repositories (force-delete with images).              |
| `efs`            | Filesystems (mount targets and access points removed first).           |
| `iam`            | Users (with all credentials/policies), groups, roles, instance profiles, customer-managed policies (with all versions), OIDC + SAML providers, server certificates. AWS service-linked roles and AWS-managed policies always skipped. |
| `secretsmanager` | Secrets (force-deleted, no recovery window).                           |
| `ssm`            | Parameter Store, custom documents, associations, maintenance windows, non-default patch baselines. |
| `kms`            | Customer-managed CMKs (scheduled for deletion; window configurable).   |
| `cloudtrail`     | **Opt-in only** (`--include-cloudtrail`): trails, event data stores, channels. |

Run order is defined in `services/__init__.py`. CloudFormation runs first so
stack-managed resources are removed before underlying services are swept.
KMS runs last so encryption keys outlive things that need them during cleanup.

## Per-service flags

| Flag                                | Service     | Description                                                        |
|-------------------------------------|-------------|--------------------------------------------------------------------|
| `--protect-bucket-prefix`           | s3          | Skip buckets with this name prefix. Repeatable.                    |
| `--iam-role-include-prefix`         | iam         | Only process IAM roles starting with these prefixes. Repeatable.   |
| `--iam-user-include-prefix`         | iam         | Only process IAM users starting with these prefixes. Repeatable.   |
| `--cloudfront-name-include-prefix`  | cloudfront  | Only process distributions whose domain starts with X. Repeatable. |
| `--route53-zone-include-suffix`     | route53     | Only delete hosted zones whose name ends with this suffix. Repeatable. If unset, all zones are deleted. |
| `--kms-pending-window-days`         | kms         | KMS deletion window (7–30 days, default 7).                        |
| `--include-cloudtrail`              | cloudtrail  | **Required** to actually delete CloudTrail resources. Without it, cloudtrail cleanup is a no-op. |

## Dry-run semantics

`--dry-run` wraps every boto3 client in a proxy. Method names starting with
`list_`, `describe_`, `get_`, `head_`, `lookup_`, `query_`, `search_`,
`select_`, `check_`, `test_`, `estimate_`, `preview_`, `batch_get_`,
`batch_describe_` pass through; **everything else is intercepted** and logged
as `[DRY RUN] would call <service>.<method>(...)` instead of being executed.
Waiters become no-ops.

This is an allowlist by design — boto3 has far too many mutating verbs
(`schedule_key_deletion`, `cancel_*`, `stop_*`, ...) for a destructive-verb
denylist to ever be complete, and a missed verb means a "dry run" that
mutates the account. Don't relax the allowlist without thinking very hard.
See `tests/test_dry_run_proxy.py`.

## Adding a new service

1. Create `services/<name>.py` with a class subclassing `ServiceCleanup`:
   ```python
   import click
   from .base import ServiceCleanup

   class FooCleanup(ServiceCleanup):
       name = 'foo'                  # CLI identifier
       boto_client = 'foo'           # session.client() name
       cli_options = []              # optional click.option decorators

       def run(self):
           ...
   ```
2. Add it to the `REGISTRY` list in `services/__init__.py` at a sensible
   ordering relative to dependencies.
3. The dry-run proxy works automatically — no per-service mocking needed.

## Tests

```bash
python3 -m pytest tests/
```

The `tests/` directory currently covers the dry-run proxy. Add a test if you
add a new mutating-verb prefix to be sure it gets intercepted.
