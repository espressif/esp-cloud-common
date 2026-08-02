# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Cognito cleanup — user pools and identity pools.

Cognito has two unrelated APIs:
  - ``cognito-idp``: User Pools (signups/auth).
  - ``cognito-identity``: Identity Pools (federated identities for AWS access).
This module wraps both since users think of "Cognito" as one thing.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class CognitoCleanup(ServiceCleanup):
    name = 'cognito'
    boto_client = 'cognito-idp'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        idp_real = session.client('cognito-identity')
        self.identity = _DryRunClient(idp_real, 'cognito-identity', console) if dry_run else idp_real

    def run(self):
        self._delete_user_pools()
        self._delete_identity_pools()
        self.console.print("\n[bold green]Cognito cleanup completed[/bold green]")

    def _delete_user_pools(self):
        self.console.print("[bold cyan]Listing Cognito user pools...[/bold cyan]")
        pools = []
        for page in self.client.get_paginator('list_user_pools').paginate(MaxResults=60):
            for pool in page.get('UserPools', []):
                pools.append(pool)
                self.console.print(f"Found user pool: {pool.get('Name')}")

        for pool in pools:
            pid = pool.get('Id')
            pname = pool.get('Name')
            try:
                try:
                    details = self.client.describe_user_pool(UserPoolId=pid)
                    domain = details.get('UserPool', {}).get('Domain')
                    if domain:
                        self.client.delete_user_pool_domain(Domain=domain, UserPoolId=pid)
                except ClientError as e:
                    if e.response['Error']['Code'] != 'ResourceNotFoundException':
                        self.console.print(f"[yellow]⚠ Could not delete domain: {e}[/yellow]")

                self.client.delete_user_pool(UserPoolId=pid)
                self.console.print(f"[green]✓ Deleted user pool: {pname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting user pool {pname}: {e}[/red]")

    def _delete_identity_pools(self):
        self.console.print("\n[bold cyan]Listing Cognito identity pools...[/bold cyan]")
        try:
            ids = []
            response = self.identity.list_identity_pools(MaxResults=60)
            ids.extend(response.get('IdentityPools', []))
            while response.get('NextToken'):
                response = self.identity.list_identity_pools(MaxResults=60, NextToken=response['NextToken'])
                ids.extend(response.get('IdentityPools', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list identity pools: {e}[/yellow]")
            return

        for pool in ids:
            pid = pool.get('IdentityPoolId')
            pname = pool.get('IdentityPoolName')
            try:
                self.identity.delete_identity_pool(IdentityPoolId=pid)
                self.console.print(f"[green]✓ Deleted identity pool: {pname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting identity pool {pname}: {e}[/red]")
