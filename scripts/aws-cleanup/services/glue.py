# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Glue cleanup — jobs, crawlers, triggers, databases (with their tables)."""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class GlueCleanup(ServiceCleanup):
    name = 'glue'
    boto_client = 'glue'
    cli_options = []

    def run(self):
        self._delete_triggers()
        self._delete_workflows()
        self._delete_ml_transforms()
        self._delete_jobs()
        self._delete_crawlers()
        self._delete_connections()
        self._delete_databases()
        self._delete_schema_registries()
        self.console.print("\n[bold green]Glue cleanup completed[/bold green]")

    def _delete_workflows(self):
        self.console.print("\n[bold cyan]Listing Glue workflows...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_workflows').paginate():
                for name in page.get('Workflows', []):
                    try:
                        self.client.delete_workflow(Name=name)
                        self.console.print(f"[green]✓ Deleted workflow: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting workflow {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list workflows: {e}[/yellow]")

    def _delete_ml_transforms(self):
        # Glue's get_ml_transforms is not exposed as a paginator. Iterate
        # manually via NextToken.
        self.console.print("\n[bold cyan]Listing Glue ML transforms...[/bold cyan]")
        try:
            transforms = []
            response = self.client.get_ml_transforms()
            transforms.extend(response.get('Transforms', []))
            while response.get('NextToken'):
                response = self.client.get_ml_transforms(NextToken=response['NextToken'])
                transforms.extend(response.get('Transforms', []))
            for t in transforms:
                tid = t.get('TransformId')
                try:
                    self.client.delete_ml_transform(TransformId=tid)
                    self.console.print(f"[green]✓ Deleted ML transform: {tid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting ML transform {tid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list ML transforms: {e}[/yellow]")

    def _delete_connections(self):
        self.console.print("\n[bold cyan]Listing Glue connections...[/bold cyan]")
        try:
            for page in self.client.get_paginator('get_connections').paginate():
                for c in page.get('ConnectionList', []):
                    name = c.get('Name')
                    try:
                        self.client.delete_connection(ConnectionName=name)
                        self.console.print(f"[green]✓ Deleted connection: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting connection {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list connections: {e}[/yellow]")

    def _delete_schema_registries(self):
        self.console.print("\n[bold cyan]Listing Glue schema registries...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_registries').paginate():
                for r in page.get('Registries', []):
                    arn = r.get('RegistryArn')
                    name = r.get('RegistryName')
                    try:
                        self.client.delete_registry(RegistryId={'RegistryArn': arn})
                        self.console.print(f"[green]✓ Deleted schema registry: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting schema registry {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list schema registries: {e}[/yellow]")

    def _delete_triggers(self):
        self.console.print("[bold cyan]Listing Glue triggers...[/bold cyan]")
        names = []
        for page in self.client.get_paginator('get_triggers').paginate():
            for t in page.get('Triggers', []):
                names.append(t.get('Name'))
        for name in names:
            try:
                self.client.delete_trigger(Name=name)
                self.console.print(f"[green]✓ Deleted trigger: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting trigger {name}: {e}[/red]")

    def _delete_jobs(self):
        self.console.print("\n[bold cyan]Listing Glue jobs...[/bold cyan]")
        names = []
        for page in self.client.get_paginator('list_jobs').paginate():
            names.extend(page.get('JobNames', []))
        for name in names:
            try:
                self.client.delete_job(JobName=name)
                self.console.print(f"[green]✓ Deleted job: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting job {name}: {e}[/red]")

    def _delete_crawlers(self):
        self.console.print("\n[bold cyan]Listing Glue crawlers...[/bold cyan]")
        names = []
        for page in self.client.get_paginator('get_crawlers').paginate():
            for c in page.get('Crawlers', []):
                names.append(c.get('Name'))
        for name in names:
            try:
                self.client.delete_crawler(Name=name)
                self.console.print(f"[green]✓ Deleted crawler: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting crawler {name}: {e}[/red]")

    def _delete_databases(self):
        self.console.print("\n[bold cyan]Listing Glue databases...[/bold cyan]")
        names = []
        for page in self.client.get_paginator('get_databases').paginate():
            for db in page.get('DatabaseList', []):
                names.append(db.get('Name'))
        for name in names:
            # delete_database cascades to its tables.
            try:
                self.client.delete_database(Name=name)
                self.console.print(f"[green]✓ Deleted database: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting database {name}: {e}[/red]")
