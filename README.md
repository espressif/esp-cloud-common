# esp-cloud-common

Shared, reusable infrastructure modules and code libraries for Espressif cloud products.

Anything here is designed to be consumed by multiple Espressif products. If a piece of infrastructure or code is only needed by one product, it stays in that product's repo. When a second consumer appears, it moves here.

## Layout

```
esp-cloud-common/
├── terraform/
│   └── modules/         # Reusable Terraform modules, one subdirectory each
├── go/                  # Reusable Go libraries (added when first consumer needs them)
├── python/              # Reusable Python libraries (added when first consumer needs them)
└── scripts/             # Generic operator scripts shared across products
```

## Conventions

- Every Terraform module has its own `README.md` with usage example, input variables, outputs.
- Modules are consumed via `git::` source with a pinned `?ref=<tag>` (SHA or semver). Local-path sources are acceptable during active co-development of a module and its first consumer; switch to pinned refs before merging to main.
- Breaking changes to a module require a new tag. Consumers opt in.
- No product-specific code lives here. If a module has a product name in it, that's a smell.

## Current modules

| Path | Purpose | First consumer |
|---|---|---|
| `terraform/modules/shared-kms-cmk` | Single-CMK pattern with admin/user role bindings | |

## Current scripts

| Path | Purpose |
|---|---|
| `scripts/create-release-bucket.sh` | Idempotently create + harden an S3 bucket for release artifacts (versioning, SSE, public-access-block, tags). Generic; takes bucket name as arg. |
| `scripts/aws-cleanup/` | Multi-service AWS account cleanup. 30 services. `--dry-run` mode that wraps every boto3 client in a read-only allowlist proxy. Generic; no product-specific code. |
