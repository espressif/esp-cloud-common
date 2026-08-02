# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""OpenSearch cleanup — managed domains and OpenSearch Serverless collections.

Two unrelated APIs share the OpenSearch brand:
  - ``opensearch``: managed domains (legacy, full clusters).
  - ``opensearchserverless``: collections (newer, autoscaled).
This module wraps both.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class OpenSearchCleanup(ServiceCleanup):
    name = 'opensearch'
    boto_client = 'opensearch'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        serverless_real = session.client('opensearchserverless')
        self.serverless = _DryRunClient(serverless_real, 'opensearchserverless', console) if dry_run else serverless_real

    def run(self):
        self._delete_domains()
        self._delete_serverless_collections()
        self._delete_serverless_security_policies()
        self._delete_serverless_access_policies()
        self._delete_serverless_vpc_endpoints()
        self.console.print("\n[bold green]OpenSearch cleanup completed[/bold green]")

    def _delete_domains(self):
        self.console.print("[bold cyan]Listing OpenSearch managed domains...[/bold cyan]")
        try:
            response = self.client.list_domain_names()
            domains = response.get('DomainNames', [])
        except ClientError as e:
            self.console.print(f"[red]Error listing OpenSearch domains: {e}[/red]")
            return

        for d in domains:
            name = d.get('DomainName')
            self.console.print(f"Found domain: {name}")
            try:
                self.client.delete_domain(DomainName=name)
                self.console.print(f"[green]✓ Deleted domain: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting domain {name}: {e}[/red]")

    def _delete_serverless_collections(self):
        self.console.print("\n[bold cyan]Listing OpenSearch Serverless collections...[/bold cyan]")
        try:
            response = self.serverless.list_collections()
            for c in response.get('collectionSummaries', []):
                cid = c.get('id')
                name = c.get('name')
                try:
                    self.serverless.delete_collection(id=cid)
                    self.console.print(f"[green]✓ Deleted serverless collection: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting serverless collection {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list serverless collections: {e}[/yellow]")

    def _delete_serverless_security_policies(self):
        self.console.print("\n[bold cyan]Listing OpenSearch Serverless security policies...[/bold cyan]")
        for ptype in ('encryption', 'network'):
            try:
                response = self.serverless.list_security_policies(type=ptype)
                for p in response.get('securityPolicySummaries', []):
                    name = p.get('name')
                    try:
                        self.serverless.delete_security_policy(name=name, type=ptype)
                        self.console.print(f"[green]✓ Deleted {ptype} policy: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting {ptype} policy {name}: {e}[/red]")
            except ClientError as e:
                self.console.print(f"[yellow]⚠ Could not list {ptype} policies: {e}[/yellow]")

    def _delete_serverless_access_policies(self):
        self.console.print("\n[bold cyan]Listing OpenSearch Serverless access policies...[/bold cyan]")
        try:
            response = self.serverless.list_access_policies(type='data')
            for p in response.get('accessPolicySummaries', []):
                name = p.get('name')
                try:
                    self.serverless.delete_access_policy(name=name, type='data')
                    self.console.print(f"[green]✓ Deleted access policy: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting access policy {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list access policies: {e}[/yellow]")

    def _delete_serverless_vpc_endpoints(self):
        self.console.print("\n[bold cyan]Listing OpenSearch Serverless VPC endpoints...[/bold cyan]")
        try:
            response = self.serverless.list_vpc_endpoints()
            for vpe in response.get('vpcEndpointSummaries', []):
                vid = vpe.get('id')
                name = vpe.get('name')
                try:
                    self.serverless.delete_vpc_endpoint(id=vid)
                    self.console.print(f"[green]✓ Deleted VPC endpoint: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting VPC endpoint {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list VPC endpoints: {e}[/yellow]")
