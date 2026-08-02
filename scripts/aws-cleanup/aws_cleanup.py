#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Generic AWS account cleanup tool.

Sweeps an account, deleting resources across many AWS services. Run with
``--dry-run`` first to preview. New services live under ``services/``.
"""

import boto3
import click
from rich.console import Console

from services import REGISTRY, REGISTRY_BY_NAME, supported_services


def _build_session(profile, access_key, secret_key, session_token, region):
    kwargs = {}
    if profile:
        kwargs['profile_name'] = profile
    if region:
        kwargs['region_name'] = region
    if access_key and secret_key:
        kwargs['aws_access_key_id'] = access_key
        kwargs['aws_secret_access_key'] = secret_key
        if session_token:
            kwargs['aws_session_token'] = session_token
    return boto3.Session(**kwargs)


def _build_main():
    @click.command()
    @click.option('--profile', help='AWS profile name to use')
    @click.option('--access-key', help='AWS access key ID')
    @click.option('--secret-key', help='AWS secret access key')
    @click.option('--session-token', help='AWS session token')
    @click.option('--region', default='us-east-1', show_default=True,
                  help='AWS region (e.g. us-east-1, eu-west-1)')
    @click.option('--service', 'services', multiple=True,
                  type=click.Choice(supported_services()),
                  help='Service to clean up. Repeatable. Default: all.')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='List resources and log mutating calls without modifying AWS state.')
    def main(profile, access_key, secret_key, session_token, region, services, dry_run, **service_options):
        """AWS Account Cleanup Tool"""
        console = Console()
        session = _build_session(profile, access_key, secret_key, session_token, region)

        if dry_run:
            console.print("[bold magenta]DRY RUN — no AWS resources will be modified[/bold magenta]")

        # Resolve which services to run
        if not services or 'all' in services:
            selected = REGISTRY
        else:
            selected = [REGISTRY_BY_NAME[name] for name in services]

        for cls in selected:
            console.rule(f"[bold]{cls.name}")
            try:
                instance = cls(session, console, dry_run=dry_run, options=service_options)
                instance.run()
            except Exception as e:
                console.print(f"[red]✗ {cls.name} cleanup failed: {e}[/red]")

        # CloudFormation retry pass. A stack can fail to delete on the first pass because a
        # resource it owns is still held by a consumer removed later in the sweep — or by a
        # resource this tool doesn't own (e.g. a Terraform-created CloudFront distribution or
        # API Gateway custom domain that references a stack-owned ACM cert). Once the sweep has
        # torn those consumers down, retry the DELETE_FAILED stacks once. No-op if none remain.
        # Skipped in dry-run and when cloudformation wasn't part of this run.
        cfn_cls = REGISTRY_BY_NAME.get('cloudformation')
        if not dry_run and cfn_cls in selected and len(selected) > 1:
            console.rule("[bold]cloudformation (retry pass)")
            try:
                cfn_cls(session, console, dry_run=dry_run, options=service_options).run()
            except Exception as e:
                console.print(f"[red]✗ cloudformation retry pass failed: {e}[/red]")

        console.print("\n[bold green]AWS cleanup completed[/bold green]")

    # Apply per-service options as additional decorators
    for cls in REGISTRY:
        for opt in cls.cli_options:
            main = opt(main)

    return main


main = _build_main()


if __name__ == '__main__':
    main()
