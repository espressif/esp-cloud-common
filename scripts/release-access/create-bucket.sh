#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

# create-release-bucket.sh
#
# Idempotently create and harden an S3 bucket intended to hold versioned
# release artifacts for a product.
#
# Convention enforced by this script:
#   - Versioning enabled (release artifacts are immutable history).
#   - Default SSE-S3 encryption with bucket keys.
#   - All public access blocked. Customer access is granted later via an
#     explicit bucket policy on the `releases/*` prefix.
#   - Tagged Project=<value>, Purpose=release-artifacts.
#
# Usage:
#   AWS_PROFILE=<profile> ./create-release-bucket.sh <bucket-name> [<project-tag>]
#
# Example:
#   AWS_PROFILE=<profile> \
#     ./create-release-bucket.sh <product_name>-installer-templates <product_name>
#
# Optional environment overrides:
#   REGION    AWS region (default: us-east-1)
#
# Re-running is safe — every step is idempotent.

set -euo pipefail

usage() {
  cat <<EOF
create-release-bucket.sh — idempotently create and harden an S3 bucket for
release artifacts (versioning + SSE + public-access-block + tags).

Usage:
  AWS_PROFILE=<profile> $(basename "$0") <bucket-name> [<project-tag>]
  $(basename "$0") -h | --help

Arguments:
  <bucket-name>    Globally-unique S3 bucket name. Required.
  <project-tag>    Value for the 'Project' tag. Defaults to <bucket-name>.

Required environment:
  AWS_PROFILE      AWS profile pointed at the target account.
                   (Or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY directly.)

Optional environment:
  REGION           AWS region (default: us-east-1).

Examples:
  # Create a release bucket in the account AWS_PROFILE points at.
  AWS_PROFILE=<profile> \\
    $(basename "$0") <product_name>-installer-templates <product_name>

  # Same, in a non-default region.
  AWS_PROFILE=<profile> REGION=eu-west-1 \\
    $(basename "$0") my-bucket my-product

What it does:
  1. Creates the bucket if it doesn't exist.
  2. Enables versioning (release artifacts are immutable history).
  3. Enables default SSE-S3 encryption with bucket keys.
  4. Blocks all public access.
  5. Tags Project=<project-tag>, Purpose=release-artifacts, ManagedBy=<this script>.

Idempotent — re-running is a no-op on already-applied steps.

Customer read access on releases/* is NOT granted by this script — add a
bucket policy separately once you have the customer's AWS account ID.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

BUCKET="${1:-}"
PROJECT_TAG="${2:-${BUCKET}}"

if [ -z "$BUCKET" ]; then
  echo "ERROR: bucket name required" >&2
  echo "Run '$(basename "$0") --help' for usage." >&2
  exit 2
fi

: "${REGION:=us-east-1}"
: "${AWS_PROFILE:=}"

if [ -z "$AWS_PROFILE" ] && [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
  echo "ERROR: set AWS_PROFILE (or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) before running." >&2
  exit 2
fi
export AWS_PROFILE

echo "── Target ──────────────────────────────────────────────────────────"
echo "Bucket:      $BUCKET"
echo "Region:      $REGION"
echo "Project tag: $PROJECT_TAG"
echo "AWS account: $(aws sts get-caller-identity --query Account --output text)"
echo

# 1. Create the bucket (skip if it already exists).
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "[1/5] Bucket exists — skipping create."
else
  echo "[1/5] Creating bucket $BUCKET in $REGION..."
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi

# 2. Versioning.
echo "[2/5] Enabling versioning..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

# 3. Default encryption (SSE-S3 with bucket keys).
echo "[3/5] Enabling default encryption (SSE-S3)..."
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

# 4. Block all public access.
echo "[4/5] Blocking all public access..."
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

# 5. Tags.
echo "[5/5] Tagging..."
aws s3api put-bucket-tagging \
  --bucket "$BUCKET" \
  --tagging "TagSet=[{Key=Project,Value=${PROJECT_TAG}},{Key=Purpose,Value=release-artifacts},{Key=ManagedBy,Value=esp-cloud-common/scripts/create-release-bucket.sh}]"

echo
echo "Done. Bucket $BUCKET is ready for release artifacts."
echo
echo "Next steps:"
echo "  - Use prefixes: internal_releases/<version>/, releases/<version>/, releases/latest/"
echo "  - Customer read access on releases/* is granted via a separate bucket policy"
echo "    once you have the customer's AWS account ID."
