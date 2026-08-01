"""Click-based CLI dispatch for release-access."""

from __future__ import annotations

import json
import os
import re

import boto3
import click
from botocore.exceptions import ClientError
from rich.console import Console
from rich.table import Table

from release_access.bootstrap import ensure_table
from release_access.discovery import find_release_buckets
from release_access.policy import merge_grant, remove_grant
from release_access.registry import (
    Grant,
    RoleConflict,
    delete_grant,
    get_grant,
    list_grants,
    upsert_grant,
)


TABLE_NAME = os.environ.get("RELEASE_ACCESS_TABLE", "release-access-grants")
ACCOUNT_ID_RE = re.compile(r"^\d{12}$")


def _session(ctx) -> boto3.Session:
    kwargs = {"region_name": ctx.obj["region"]}
    if ctx.obj["profile"]:
        kwargs["profile_name"] = ctx.obj["profile"]
    return boto3.Session(**kwargs)


def _validate_account_id(account_id: str) -> None:
    if not ACCOUNT_ID_RE.match(account_id):
        raise click.BadParameter(
            f"{account_id!r} is not a 12-digit AWS account ID"
        )


def _get_bucket_policy(s3, bucket: str):
    try:
        resp = s3.get_bucket_policy(Bucket=bucket)
        return json.loads(resp["Policy"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucketPolicy":
            return None
        raise


def _put_or_delete_policy(s3, bucket: str, policy):
    if policy is None:
        try:
            s3.delete_bucket_policy(Bucket=bucket)
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchBucketPolicy":
                raise
    else:
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))


@click.group()
@click.option("--profile", help="AWS profile name.")
@click.option("--region", default="us-east-1", show_default=True, help="AWS region.")
@click.option("--dry-run", is_flag=True, help="Print actions without mutating AWS state.")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging.")
@click.pass_context
def main(ctx, profile, region, dry_run, verbose):
    """release-access — grant/revoke per-project read access on release buckets."""
    ctx.ensure_object(dict)
    ctx.obj.update(profile=profile, region=region, dry_run=dry_run, verbose=verbose,
                   console=Console())


@main.command()
@click.pass_context
def bootstrap(ctx):
    """Create the DynamoDB grants table (idempotent)."""
    console = ctx.obj["console"]
    if ctx.obj["dry_run"]:
        console.print(f"[magenta]DRY-RUN[/magenta] would ensure table {TABLE_NAME}")
        return
    session = _session(ctx)
    ensure_table(session, TABLE_NAME)
    console.print(f"[green]✓[/green] table {TABLE_NAME} ready")


def _parse_products(raw: str) -> list[str]:
    """Split a comma-separated product list, trimming blanks and de-duping."""
    seen: dict[str, None] = {}
    for part in raw.split(","):
        product = part.strip()
        if product:
            seen.setdefault(product, None)
    products = list(seen)
    if not products:
        raise click.BadParameter("no product names provided")
    return products


@main.command()
@click.option("--products", required=True,
              help="One product name or a comma-separated list, e.g. "
                   '"product-a,product-b".')
@click.option("--account-id", "account_id", required=True,
              help="12-digit AWS account ID to grant access to.")
@click.option("--role", type=click.Choice(["dev", "customer"]), required=True)
@click.option("--friendly-name", required=True,
              help="Human label for this grantee (company/team). Stored only "
                   "for audit/lookup; not used in any access policy.")
@click.option("--update-role", is_flag=True,
              help="Required when changing an existing grant's role.")
@click.pass_context
def grant(ctx, products, account_id, role, friendly_name, update_role):
    """Grant an AWS account read access to one or more products' release buckets."""
    console = ctx.obj["console"]
    _validate_account_id(account_id)
    product_list = _parse_products(products)

    session = _session(ctx)

    # Phase 1 — validate every product before mutating anything, so a bad
    # product in the list can't leave us half-granted.
    resolved: dict[str, list[str]] = {}
    for product in product_list:
        buckets = find_release_buckets(session, product)
        if not buckets:
            raise click.ClickException(
                f"no buckets tagged Project={product} AND Purpose=release-artifacts"
            )
        console.print(f"Resolved {len(buckets)} bucket(s) for project {product!r}: "
                      + ", ".join(buckets))

        existing = get_grant(session, TABLE_NAME, product, account_id)
        if existing and existing.role != role and not update_role:
            raise click.ClickException(
                f"grant exists for {product} with role={existing.role!r}; pass "
                f"--update-role to change it to {role!r}"
            )
        resolved[product] = buckets

    # Phase 2 — apply each product.
    for product in product_list:
        _grant_one(ctx, session, product, account_id, role, friendly_name,
                   update_role, resolved[product])


def _grant_one(ctx, session, project, account_id, role, friendly_name,
               update_role, buckets):
    """Apply a single project's grant: bucket policies then the DynamoDB row."""
    console = ctx.obj["console"]
    s3 = session.client("s3")

    # Apply bucket policies first (so DynamoDB stays accurate if S3 fails).
    bucket_arns = [f"arn:aws:s3:::{b}" for b in buckets]
    for bucket in buckets:
        current = _get_bucket_policy(s3, bucket)
        new_policy = merge_grant(current, bucket, account_id, role)
        if new_policy is not None:
            policy_bytes = len(json.dumps(new_policy).encode("utf-8"))
            if policy_bytes > 20 * 1024:
                raise click.ClickException(
                    f"bucket policy for {bucket} would be {policy_bytes} bytes, "
                    f"exceeding the 20 KB S3 limit. Revoke unused grants first."
                )
        if ctx.obj["dry_run"]:
            console.print(f"[magenta]DRY-RUN[/magenta] would put policy on {bucket}:")
            console.print_json(data=new_policy)
            continue
        _put_or_delete_policy(s3, bucket, new_policy)
        console.print(f"[green]✓[/green] applied {role} grant to {bucket}")

    # Then write DynamoDB.
    if ctx.obj["dry_run"]:
        preview = Grant(project=project, account_id=account_id, role=role,
                        friendly_name=friendly_name, granted_by="<dry-run>",
                        buckets=bucket_arns)
        console.print(f"[magenta]DRY-RUN[/magenta] would upsert grant: {preview}")
        return

    granted_by = session.client("sts").get_caller_identity()["Arn"]
    g = Grant(project=project, account_id=account_id, role=role,
              friendly_name=friendly_name, granted_by=granted_by,
              buckets=bucket_arns)
    try:
        upsert_grant(session, TABLE_NAME, g, allow_role_change=update_role)
    except RoleConflict as e:
        raise click.ClickException(str(e))
    console.print(f"[green]✓[/green] recorded grant for {account_id} "
                  f"({friendly_name}) on {project}")


@main.command()
@click.argument("project")
@click.argument("account_id")
@click.pass_context
def revoke(ctx, project, account_id):
    """Revoke <account-id>'s access to <project>'s release buckets."""
    console = ctx.obj["console"]
    _validate_account_id(account_id)

    session = _session(ctx)
    existing = get_grant(session, TABLE_NAME, project, account_id)
    if existing is None:
        raise click.ClickException(
            f"no grant found for project={project} account={account_id}"
        )

    s3 = session.client("s3")
    for arn in existing.buckets:
        bucket = arn.split(":::", 1)[1]
        current = _get_bucket_policy(s3, bucket)
        new_policy = remove_grant(current, account_id)
        if ctx.obj["dry_run"]:
            console.print(f"[magenta]DRY-RUN[/magenta] would update policy on {bucket}:")
            console.print_json(data=new_policy if new_policy else {"_": "delete policy"})
            continue
        _put_or_delete_policy(s3, bucket, new_policy)
        console.print(f"[green]✓[/green] removed grant from {bucket}")

    if ctx.obj["dry_run"]:
        console.print(
            f"[magenta]DRY-RUN[/magenta] would delete grant: "
            f"role={existing.role} friendly_name={existing.friendly_name!r} "
            f"granted_at={existing.granted_at}"
        )
        return
    delete_grant(session, TABLE_NAME, project, account_id)
    console.print(f"[green]✓[/green] removed grant row for {account_id}")


@main.command(name="list")
@click.argument("project", required=False)
@click.pass_context
def list_grants_cmd(ctx, project):
    """List grants (optionally filtered by project)."""
    console = ctx.obj["console"]
    session = _session(ctx)
    rows = list_grants(session, TABLE_NAME, project=project)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Account")
    table.add_column("Role")
    table.add_column("Friendly Name")
    table.add_column("Granted At")
    for r in rows:
        table.add_row(r.project, r.account_id, r.role, r.friendly_name, r.granted_at or "")
    console.print(table)
