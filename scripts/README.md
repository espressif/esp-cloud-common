# scripts/

Operational scripts shared across Espressif cloud products. Each tool is
product-agnostic — anything product-specific belongs in the product repo,
not here.

## Inventory

| Tool                                   | Purpose                                                                       |
|----------------------------------------|-------------------------------------------------------------------------------|
| [`aws-cleanup/`](./aws-cleanup/)       | Sweep an AWS account, deleting resources across many services.                |
| [`release-access/`](./release-access/) | Create release buckets and grant/revoke per-project read access on them.      |

## `aws-cleanup/`

Multi-service AWS account cleanup with `--dry-run` support. See
[`aws-cleanup/README.md`](./aws-cleanup/README.md) for usage, supported
services, per-service flags, and how to add a new service.

## `release-access/`

End-to-end lifecycle for release S3 buckets:

- `create-bucket.sh` — create + harden a versioned release bucket.
- `release_access.py` — grant/revoke per-project read access, with
  DynamoDB-backed friendly-name tracking.

See [`release-access/README.md`](./release-access/README.md).
