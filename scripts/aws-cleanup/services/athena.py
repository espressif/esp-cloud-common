"""Athena cleanup — workgroups (skip 'primary') and named queries."""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class AthenaCleanup(ServiceCleanup):
    name = 'athena'
    boto_client = 'athena'
    cli_options = []

    def run(self):
        self._delete_named_queries()
        self._delete_workgroups()
        self.console.print("\n[bold green]Athena cleanup completed[/bold green]")

    def _delete_named_queries(self):
        self.console.print("[bold cyan]Listing Athena named queries...[/bold cyan]")
        ids = []
        try:
            for page in self.client.get_paginator('list_named_queries').paginate():
                ids.extend(page.get('NamedQueryIds', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list named queries: {e}[/yellow]")
            return

        for qid in ids:
            try:
                self.client.delete_named_query(NamedQueryId=qid)
                self.console.print(f"[green]✓ Deleted named query: {qid}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting named query {qid}: {e}[/red]")

    def _delete_workgroups(self):
        # Athena's list_work_groups is not exposed as a paginator. Iterate
        # manually via NextToken.
        self.console.print("\n[bold cyan]Listing Athena workgroups (excluding 'primary')...[/bold cyan]")
        names = []
        try:
            response = self.client.list_work_groups()
            workgroups = list(response.get('WorkGroups', []))
            while response.get('NextToken'):
                response = self.client.list_work_groups(NextToken=response['NextToken'])
                workgroups.extend(response.get('WorkGroups', []))
            for wg in workgroups:
                name = wg.get('Name')
                if name == 'primary':
                    continue
                names.append(name)
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list workgroups: {e}[/yellow]")
            return

        for name in names:
            try:
                self.client.delete_work_group(WorkGroup=name, RecursiveDeleteOption=True)
                self.console.print(f"[green]✓ Deleted workgroup: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting workgroup {name}: {e}[/red]")
