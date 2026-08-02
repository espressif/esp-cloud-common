# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""API Gateway cleanup — handles both v1 (REST) and v2 (HTTP/WebSocket) APIs."""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class APIGatewayCleanup(ServiceCleanup):
    name = 'apigateway'
    boto_client = 'apigateway'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        from .base import _DryRunClient
        v2_real = session.client('apigatewayv2')
        self.v2_client = _DryRunClient(v2_real, 'apigatewayv2', console) if dry_run else v2_real

    def run(self):
        self._cleanup_usage_plans()
        self._cleanup_api_keys()
        # Delete custom domains BEFORE the APIs. An API can't be deleted while it is still
        # mapped to a custom domain ("remove all API mappings for the API ..."), and deleting
        # the domain removes its mappings — so domains first, then the APIs delete cleanly.
        self._cleanup_v2_domains()
        self._cleanup_v1_domains()
        self._cleanup_rest_apis()
        self._cleanup_v2_apis()
        self._cleanup_client_certificates()
        self.console.print("\n[bold green]API Gateway cleanup completed[/bold green]")

    def _cleanup_usage_plans(self):
        self.console.print("[bold cyan]Listing API Gateway usage plans...[/bold cyan]")
        try:
            for page in self.client.get_paginator('get_usage_plans').paginate():
                for plan in page.get('items', []):
                    pid = plan.get('id')
                    name = plan.get('name')
                    # Detach plan keys first
                    try:
                        for k in self.client.get_usage_plan_keys(usagePlanId=pid).get('items', []):
                            self.client.delete_usage_plan_key(usagePlanId=pid, keyId=k['id'])
                    except ClientError:
                        pass
                    try:
                        self.client.delete_usage_plan(usagePlanId=pid)
                        self.console.print(f"[green]✓ Deleted usage plan: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting usage plan {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list usage plans: {e}[/yellow]")

    def _cleanup_api_keys(self):
        self.console.print("\n[bold cyan]Listing API keys...[/bold cyan]")
        try:
            for page in self.client.get_paginator('get_api_keys').paginate():
                for k in page.get('items', []):
                    kid = k.get('id')
                    try:
                        self.client.delete_api_key(apiKey=kid)
                        self.console.print(f"[green]✓ Deleted API key: {k.get('name', kid)}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting API key {kid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list API keys: {e}[/yellow]")

    def _cleanup_v1_domains(self):
        self.console.print("\n[bold cyan]Listing API Gateway custom domains (v1)...[/bold cyan]")
        try:
            for page in self.client.get_paginator('get_domain_names').paginate():
                for d in page.get('items', []):
                    name = d.get('domainName')
                    try:
                        self.client.delete_domain_name(domainName=name)
                        self.console.print(f"[green]✓ Deleted v1 domain: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting v1 domain {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v1 domains: {e}[/yellow]")

    def _cleanup_v2_domains(self):
        self.console.print("\n[bold cyan]Listing API Gateway custom domains (v2)...[/bold cyan]")
        try:
            response = self.v2_client.get_domain_names()
            for d in response.get('Items', []):
                name = d.get('DomainName')
                try:
                    self.v2_client.delete_domain_name(DomainName=name)
                    self.console.print(f"[green]✓ Deleted v2 domain: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v2 domain {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v2 domains: {e}[/yellow]")

    def _cleanup_client_certificates(self):
        self.console.print("\n[bold cyan]Listing API Gateway client certificates...[/bold cyan]")
        try:
            for page in self.client.get_paginator('get_client_certificates').paginate():
                for c in page.get('items', []):
                    cid = c.get('clientCertificateId')
                    try:
                        self.client.delete_client_certificate(clientCertificateId=cid)
                        self.console.print(f"[green]✓ Deleted client cert: {cid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting client cert {cid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list client certificates: {e}[/yellow]")

    def _cleanup_rest_apis(self):
        self.console.print("[bold cyan]Listing API Gateway REST APIs...[/bold cyan]")
        apis = []
        for page in self.client.get_paginator('get_rest_apis').paginate():
            for api in page.get('items', []):
                apis.append(api)
                self.console.print(f"Found REST API: {api.get('name')} ({api.get('id')})")

        if not apis:
            self.console.print("[yellow]No REST APIs found[/yellow]")
            return

        for api in apis:
            api_id = api.get('id')
            name = api.get('name')
            try:
                self.client.delete_rest_api(restApiId=api_id)
                self.console.print(f"[green]✓ Deleted REST API: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting REST API {name}: {e}[/red]")

    def _cleanup_v2_apis(self):
        self.console.print("\n[bold cyan]Listing API Gateway v2 (HTTP/WebSocket) APIs...[/bold cyan]")
        try:
            response = self.v2_client.get_apis()
            apis = response.get('Items', [])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v2 APIs: {e}[/yellow]")
            return

        for api in apis:
            self.console.print(f"Found v2 API: {api.get('Name')} ({api.get('ApiId')})")

        if not apis:
            self.console.print("[yellow]No v2 APIs found[/yellow]")
            return

        for api in apis:
            api_id = api.get('ApiId')
            name = api.get('Name')
            try:
                self.v2_client.delete_api(ApiId=api_id)
                self.console.print(f"[green]✓ Deleted v2 API: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting v2 API {name}: {e}[/red]")
