# esp-cloud-common

Shared, reusable infrastructure modules and code libraries for Espressif cloud products.

Anything here is designed to be consumed by multiple Espressif products. If a piece of infrastructure or code is only needed by one product, it stays in that product's repo. When a second consumer appears, it moves here.

Go module path: `github.com/espressif/esp-cloud-common` (Go 1.26.10).

## Layout

```
esp-cloud-common/
├── terraform/
│   └── modules/         # Reusable Terraform modules, one subdirectory each
├── go/                  # Reusable Go libraries
├── cdk_go/              # Reusable AWS CDK (Python) constructs + their Go Lambdas
└── scripts/             # Generic operator scripts shared across products
```

## Conventions

- Every module has its own `README.md` with usage example, inputs, and outputs.
- Terraform modules are consumed via `git::` source with a pinned `?ref=<tag>` (SHA or semver). Local-path sources are acceptable during active co-development of a module and its first consumer; switch to pinned refs before merging to main.
- Go and Python code is consumed by pinned tag as well — either `go get ...@<tag>` or a git submodule pinned to a tag. Don't track `main`.
- Breaking changes require a new tag. Consumers opt in.
- No product-specific code lives here. If a module has a product name in it, that's a smell.
- Every source file carries the SPDX header:
  ```
  # SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
  #
  # SPDX-License-Identifier: Apache-2.0
  ```

## Terraform modules

| Path | Purpose |
|---|---|
| [`terraform/modules/shared-kms-cmk`](terraform/modules/shared-kms-cmk/) | Single customer-managed KMS key with alias, automatic rotation, and admin/user principal bindings. |

## Go libraries

| Path | Purpose |
|---|---|
| [`go/clog`](go/clog/) | Global zerolog-based logger configured from the `CLOG` environment variable, with user/node context keys and level filtering. |
| [`go/util`](go/util/) | Small shared helpers: `CustomError` with cause chains and stack rendering, and `any → any` struct conversion. |
| [`go/aws_services/awsconfig`](go/aws_services/awsconfig/) | Default AWS SDK v2 config loader with the shared retry behavior. |
| [`go/aws_services/ddb`](go/aws_services/ddb/) | Narrow DynamoDB control-plane client interface, plus a mock for tests. |
| [`go/aws_services/sfn`](go/aws_services/sfn/) | Step Functions client wrapper, plus a mock for tests. |
| [`go/rbac`](go/rbac/) | Role-based access control: policy definition, validation, and authorization checks. |

## CDK constructs

| Path | Purpose |
|---|---|
| [`cdk_go/gsi_infra`](cdk_go/gsi_infra/) | Makes DynamoDB GSI changes safe in CloudFormation. `ManagedTable` routes GSI create/delete through a Step Functions orchestrator, and `GsiReadinessGate` holds the stack at `CREATE_COMPLETE`/`UPDATE_COMPLETE` until every GSI is `ACTIVE && !Backfilling`. |
| [`cdk_go/common`](cdk_go/common/) | Shared CDK helpers used by the constructs above: Lambda and custom-resource provider factories, deterministic logical IDs. |

## Scripts

| Path | Purpose |
|---|---|
| [`scripts/aws-cleanup/`](scripts/aws-cleanup/) | Multi-service AWS account cleanup across 38 services. `--dry-run` wraps every boto3 client in a read-only allowlist proxy. Destructive — always dry-run first. |
| [`scripts/release-access/`](scripts/release-access/) | Release-bucket lifecycle: `create-bucket.sh` creates and hardens a versioned release bucket (SSE, public-access-block, tags); `release_access.py` grants/revokes per-project read access with DynamoDB-backed friendly-name tracking. |

See [`scripts/README.md`](scripts/README.md) for the full inventory.

## Development

| Command | What it does |
|---|---|
| `make test` | Go unit tests under `cdk_go/` and `go/`. No AWS needed. Writes `coverage.out`. |
| `make vulncheck` | `govulncheck` over the module. Blocking gate in CI. |
| `make go_build` | Builds every Lambda Go binary into `build/<name>/bootstrap`. |
| `make setup` | One-time per AWS account/region: `cdk bootstrap` with the `cc-itest` qualifier so integration tests can stage Lambda assets. |
| `make itest` | Python integration tests under `cdk_go/**/itests/`. Requires AWS credentials and `RUN_GSI_INFRA_ITEST=true`. Depends on `go_build`. |
| `make clean` | Removes build artifacts. |

CI (`.gitlab-ci.yml`) runs `make test` and `make vulncheck` on merge requests that touch Go sources, `go.mod`, `go.sum`, or the `Makefile`.

## License

Apache-2.0. See [LICENSE](LICENSE).
