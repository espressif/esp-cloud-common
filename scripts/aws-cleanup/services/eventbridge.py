# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""EventBridge cleanup — rules across all buses, then non-default buses.

Rules must have their targets removed before deletion.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class EventBridgeCleanup(ServiceCleanup):
    """EventBridge cleanup — Events (rules, buses, archives, replays,
    connections, API destinations) and Scheduler (schedules, groups)."""

    name = 'eventbridge'
    boto_client = 'events'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        sched_real = session.client('scheduler')
        self.scheduler = _DryRunClient(sched_real, 'scheduler', console) if dry_run else sched_real

    def run(self):
        buses = self._list_buses()
        for bus_name in [b.get('Name') for b in buses]:
            self._cleanup_rules(bus_name)
        self._cleanup_replays()
        self._cleanup_archives()
        self._cleanup_api_destinations()
        self._cleanup_connections()
        self._cleanup_schedules()
        self._cleanup_schedule_groups()
        self._cleanup_buses(buses)
        self.console.print("\n[bold green]EventBridge cleanup completed[/bold green]")

    def _cleanup_replays(self):
        self.console.print("\n[bold cyan]Listing EventBridge replays...[/bold cyan]")
        try:
            response = self.client.list_replays()
            for r in response.get('Replays', []):
                name = r.get('ReplayName')
                if r.get('State') in ('CANCELLED', 'COMPLETED'):
                    continue
                try:
                    self.client.cancel_replay(ReplayName=name)
                    self.console.print(f"[green]✓ Cancelled replay: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error cancelling replay {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list replays: {e}[/yellow]")

    def _cleanup_archives(self):
        self.console.print("\n[bold cyan]Listing EventBridge archives...[/bold cyan]")
        try:
            response = self.client.list_archives()
            for a in response.get('Archives', []):
                name = a.get('ArchiveName')
                try:
                    self.client.delete_archive(ArchiveName=name)
                    self.console.print(f"[green]✓ Deleted archive: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting archive {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list archives: {e}[/yellow]")

    def _cleanup_api_destinations(self):
        self.console.print("\n[bold cyan]Listing EventBridge API destinations...[/bold cyan]")
        try:
            response = self.client.list_api_destinations()
            for d in response.get('ApiDestinations', []):
                name = d.get('Name')
                try:
                    self.client.delete_api_destination(Name=name)
                    self.console.print(f"[green]✓ Deleted API destination: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting API destination {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list API destinations: {e}[/yellow]")

    def _cleanup_connections(self):
        self.console.print("\n[bold cyan]Listing EventBridge connections...[/bold cyan]")
        try:
            response = self.client.list_connections()
            for c in response.get('Connections', []):
                name = c.get('Name')
                try:
                    self.client.delete_connection(Name=name)
                    self.console.print(f"[green]✓ Deleted connection: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting connection {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list connections: {e}[/yellow]")

    def _cleanup_schedules(self):
        self.console.print("\n[bold cyan]Listing EventBridge schedules...[/bold cyan]")
        try:
            for page in self.scheduler.get_paginator('list_schedules').paginate():
                for s in page.get('Schedules', []):
                    name = s.get('Name')
                    group = s.get('GroupName', 'default')
                    try:
                        self.scheduler.delete_schedule(Name=name, GroupName=group)
                        self.console.print(f"[green]✓ Deleted schedule: {group}/{name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting schedule {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list schedules: {e}[/yellow]")

    def _cleanup_schedule_groups(self):
        self.console.print("\n[bold cyan]Listing EventBridge schedule groups (excluding 'default')...[/bold cyan]")
        try:
            for page in self.scheduler.get_paginator('list_schedule_groups').paginate():
                for g in page.get('ScheduleGroups', []):
                    name = g.get('Name')
                    if name == 'default':
                        continue
                    try:
                        self.scheduler.delete_schedule_group(Name=name)
                        self.console.print(f"[green]✓ Deleted schedule group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting schedule group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list schedule groups: {e}[/yellow]")

    def _list_buses(self):
        try:
            return self.client.list_event_buses().get('EventBuses', [])
        except ClientError as e:
            self.console.print(f"[red]Error listing event buses: {e}[/red]")
            return []

    def _cleanup_rules(self, bus_name):
        self.console.print(f"[bold cyan]Listing rules on bus '{bus_name}'...[/bold cyan]")
        try:
            response = self.client.list_rules(EventBusName=bus_name)
            rules = response.get('Rules', [])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list rules on {bus_name}: {e}[/yellow]")
            return

        for rule in rules:
            rname = rule.get('Name')
            self.console.print(f"Found rule: {rname}")
            try:
                target_resp = self.client.list_targets_by_rule(Rule=rname, EventBusName=bus_name)
                target_ids = [t['Id'] for t in target_resp.get('Targets', [])]
                if target_ids:
                    self.client.remove_targets(Rule=rname, EventBusName=bus_name, Ids=target_ids)

                self.client.delete_rule(Name=rname, EventBusName=bus_name, Force=True)
                self.console.print(f"[green]✓ Deleted rule: {rname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting rule {rname}: {e}[/red]")

    def _cleanup_buses(self, buses):
        self.console.print("\n[bold cyan]Deleting non-default event buses...[/bold cyan]")
        for bus in buses:
            name = bus.get('Name')
            if name == 'default':
                continue
            try:
                self.client.delete_event_bus(Name=name)
                self.console.print(f"[green]✓ Deleted bus: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting bus {name}: {e}[/red]")
