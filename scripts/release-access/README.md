# release-access

Lifecycle tools for Espressif release S3 buckets:

1. **`create-bucket.sh`** — create + harden a new release bucket.
2. **`release_access.py`** — grant/revoke per-project read access on those
   buckets, with DynamoDB-backed friendly-name tracking.

## Lifecycle

```
create-bucket.sh         →  release_access.py grant   →  release_access.py revoke
  (one-time per bucket)     (per consumer account)      (when access ends)
```

## `create-bucket.sh` — create a release bucket

Idempotently create and harden an S3 bucket: versioning, SSE-S3, all public
access blocked, tagged `Project=<project>`, `Purpose=release-artifacts`.

```bash
AWS_PROFILE=<profile> \
  ./create-bucket.sh <product_name>-installer-templates <product_name>
```

Optional env: `REGION` (default `us-east-1`).

Re-running is a no-op on already-applied steps. See the script header for
full details.

## `release_access.py` — manage access

Discovers buckets tagged `Project=<project>` AND `Purpose=release-artifacts`,
then adds (or removes) per-account bucket-policy statements granting read on:

- `releases/*` — for `--role customer`
- `internal_releases/*` + `releases/*` — for `--role dev`

Each grant is tracked in a DynamoDB table (`release-access-grants`) with a
free-form friendly name for audit. The friendly name is **never** used in
any access policy.

### Setup

```bash
cd scripts/release-access
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

One-time per AWS account hosting the buckets:

```bash
AWS_PROFILE=<profile> python release_access.py bootstrap
```

### Usage

```bash
# Grant a customer read on releases/
AWS_PROFILE=<profile> python release_access.py grant \
    --products <product_name> \
    --account-id 123456789012 \
    --role customer \
    --friendly-name "Acme Corp"

# Grant the same account across multiple products at once
# (comma-separated, no spaces). Buckets for every product are resolved and
# validated up front, so a bad name aborts before anything is changed.
AWS_PROFILE=<profile> python release_access.py grant \
    --products <product_name>,<other_product_name> \
    --account-id 123456789012 \
    --role customer \
    --friendly-name "Acme Corp"

# Promote that grant to a dev (requires explicit flag)
AWS_PROFILE=<profile> python release_access.py grant \
    --products <product_name> \
    --account-id 123456789012 \
    --role dev \
    --friendly-name "Acme Corp" \
    --update-role

# List
AWS_PROFILE=<profile> python release_access.py list <product_name>

# Revoke
AWS_PROFILE=<profile> python release_access.py revoke \
    <product_name> 123456789012
```

Append `--dry-run` to any mutating command to preview without changes.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

### How it works

- Bucket lookup uses the **Resource Groups Tagging API** so we don't have
  to enumerate every bucket in the account.
- Bucket policy statements are keyed by a deterministic
  `Sid: ReleaseAccess-<role>-<account_id>`, so re-running `grant` is a
  clean replacement, never a duplicate.
- `revoke` reads the bucket list off the DynamoDB row (not by re-querying
  tags), so it still works if a bucket has since been retagged.

### Note on listing

The `ListBucket` permission is scoped to the `releases/` and
`internal_releases/` prefixes. `aws s3 ls s3://<bucket>/` (no prefix) will
return `AccessDenied`; list inside the allowed prefixes
(`aws s3 ls s3://<bucket>/releases/`) instead. Always include the trailing
slash.
