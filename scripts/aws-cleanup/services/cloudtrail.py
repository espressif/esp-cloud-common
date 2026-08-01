"""CloudTrail cleanup — opt-in only.

Trails carry the audit log for the account. Deleting them by accident is
extremely bad — losing the audit trail can be a compliance violation.
This service refuses to do anything unless ``--include-cloudtrail`` is
explicitly passed.
"""

import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


class CloudTrailCleanup(ServiceCleanup):
    name = 'cloudtrail'
    boto_client = 'cloudtrail'
    cli_options = [
        click.option(
            '--include-cloudtrail', 'include_cloudtrail', is_flag=True, default=False,
            help='REQUIRED to actually delete CloudTrail trails, event data stores, '
                 'and channels. Without this flag, cloudtrail cleanup is a no-op.',
        ),
    ]

    def run(self):
        if not self.options.get('include_cloudtrail'):
            self.console.print("[yellow]Skipping CloudTrail (pass --include-cloudtrail to enable)[/yellow]")
            return

        self._delete_trails()
        self._delete_event_data_stores()
        self._delete_channels()
        self.console.print("\n[bold green]CloudTrail cleanup completed[/bold green]")

    def _delete_trails(self):
        self.console.print("[bold cyan]Listing CloudTrail trails...[/bold cyan]")
        try:
            response = self.client.list_trails()
            for t in response.get('Trails', []):
                arn = t.get('TrailARN')
                name = t.get('Name')
                try:
                    self.client.delete_trail(Name=arn)
                    self.console.print(f"[green]✓ Deleted trail: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting trail {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list trails: {e}[/yellow]")

    def _delete_event_data_stores(self):
        self.console.print("\n[bold cyan]Listing CloudTrail event data stores...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_event_data_stores').paginate():
                for eds in page.get('EventDataStores', []):
                    arn = eds.get('EventDataStoreArn')
                    name = eds.get('Name')
                    try:
                        # Disable termination protection if set.
                        try:
                            self.client.update_event_data_store(
                                EventDataStore=arn, TerminationProtectionEnabled=False,
                            )
                        except ClientError:
                            pass
                        self.client.delete_event_data_store(EventDataStore=arn)
                        self.console.print(f"[green]✓ Deleted event data store: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting event data store {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list event data stores: {e}[/yellow]")

    def _delete_channels(self):
        self.console.print("\n[bold cyan]Listing CloudTrail channels...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_channels').paginate():
                for c in page.get('Channels', []):
                    arn = c.get('ChannelArn')
                    name = c.get('Name')
                    try:
                        self.client.delete_channel(Channel=arn)
                        self.console.print(f"[green]✓ Deleted channel: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting channel {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list channels: {e}[/yellow]")
