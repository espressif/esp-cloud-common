# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class SSMCleanup(ServiceCleanup):
    """SSM cleanup — Parameter Store, custom Documents, Associations,
    Maintenance Windows, Patch Baselines."""

    name = 'ssm'
    boto_client = 'ssm'
    cli_options = []

    BATCH_SIZE = 10  # delete_parameters max

    def run(self):
        self._delete_associations()
        self._delete_maintenance_windows()
        self._delete_patch_baselines()
        self._delete_documents()
        self._delete_parameters()
        self.console.print("\n[bold green]SSM cleanup completed[/bold green]")

    def _delete_parameters(self):
        self.console.print("[bold cyan]Listing SSM parameters...[/bold cyan]")
        names = []
        for page in self.client.get_paginator('describe_parameters').paginate():
            for param in page.get('Parameters', []):
                names.append(param.get('Name'))

        if not names:
            self.console.print("[yellow]No parameters found[/yellow]")
            return

        for i in range(0, len(names), self.BATCH_SIZE):
            batch = names[i:i + self.BATCH_SIZE]
            try:
                self.client.delete_parameters(Names=batch)
                self.console.print(f"[green]✓ Deleted {len(batch)} parameters[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting parameter batch: {e}[/red]")

    def _delete_associations(self):
        self.console.print("\n[bold cyan]Listing SSM associations...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_associations').paginate():
                for a in page.get('Associations', []):
                    aid = a.get('AssociationId')
                    try:
                        self.client.delete_association(AssociationId=aid)
                        self.console.print(f"[green]✓ Deleted association: {aid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting association {aid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list associations: {e}[/yellow]")

    def _delete_maintenance_windows(self):
        self.console.print("\n[bold cyan]Listing SSM maintenance windows...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_maintenance_windows').paginate():
                for w in page.get('WindowIdentities', []):
                    wid = w.get('WindowId')
                    try:
                        self.client.delete_maintenance_window(WindowId=wid)
                        self.console.print(f"[green]✓ Deleted maintenance window: {wid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting maintenance window {wid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list maintenance windows: {e}[/yellow]")

    def _delete_patch_baselines(self):
        # ``describe_patch_baselines`` without a filter returns AWS-owned
        # default baselines (account 075727635805 and similar) alongside
        # ones the caller actually owns. Filter to ``OWNER=Self`` so we
        # only see and try to delete our own. The ``DefaultBaseline``
        # check is kept as a belt-and-suspenders for any default we
        # might have explicitly created.
        self.console.print("\n[bold cyan]Listing SSM patch baselines (owned)...[/bold cyan]")
        try:
            paginator = self.client.get_paginator('describe_patch_baselines')
            for page in paginator.paginate(Filters=[{'Key': 'OWNER', 'Values': ['Self']}]):
                for b in page.get('BaselineIdentities', []):
                    if b.get('DefaultBaseline'):
                        continue
                    bid = b.get('BaselineId')
                    try:
                        self.client.delete_patch_baseline(BaselineId=bid)
                        self.console.print(f"[green]✓ Deleted patch baseline: {bid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting patch baseline {bid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list patch baselines: {e}[/yellow]")

    def _delete_documents(self):
        self.console.print("\n[bold cyan]Listing SSM documents (owned by Self)...[/bold cyan]")
        try:
            paginator = self.client.get_paginator('list_documents')
            for page in paginator.paginate(Filters=[{'Key': 'Owner', 'Values': ['Self']}]):
                for d in page.get('DocumentIdentifiers', []):
                    name = d.get('Name')
                    try:
                        self.client.delete_document(Name=name, Force=True)
                        self.console.print(f"[green]✓ Deleted document: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting document {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list documents: {e}[/yellow]")
