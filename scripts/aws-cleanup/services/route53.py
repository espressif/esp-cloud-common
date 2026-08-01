import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


class Route53Cleanup(ServiceCleanup):
    name = 'route53'
    boto_client = 'route53'
    cli_options = [
        click.option(
            '--route53-zone-include-suffix', 'route53_zone_include_suffixes', multiple=True,
            help='Only delete hosted zones whose name ends with one of these suffixes '
                 '(e.g. staging.example.com). Repeatable. If unset, ALL '
                 'hosted zones are processed — use with care.',
        ),
    ]

    def run(self):
        include = tuple(s.rstrip('.').lower() for s in (self.options.get('route53_zone_include_suffixes') or ()))

        self.console.print("[bold cyan]Listing Route53 hosted zones...[/bold cyan]")
        zones = []
        for page in self.client.get_paginator('list_hosted_zones').paginate():
            for z in page.get('HostedZones', []) or []:
                name = (z.get('Name') or '').rstrip('.').lower()
                if include and not name.endswith(include):
                    continue
                zones.append(z)
                scope = 'private' if z.get('Config', {}).get('PrivateZone') else 'public'
                self.console.print(f"Found hosted zone: {z.get('Name')} ({scope}, ID: {z.get('Id')})")

        if not zones:
            self.console.print("[yellow]No matching hosted zones found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(zones)} hosted zones to delete[/bold cyan]")
        for z in zones:
            zone_id, zone_name = z.get('Id'), z.get('Name')
            try:
                self._empty_zone(zone_id, zone_name)
                self.client.delete_hosted_zone(Id=zone_id)
                self.console.print(f"[green]✓ Deleted hosted zone: {zone_name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting hosted zone {zone_name}: {e}[/red]")

        self.console.print("\n[bold green]Route53 cleanup completed[/bold green]")

    def _empty_zone(self, zone_id, zone_name):
        """Delete all record sets except the apex SOA + NS (Route53 removes those on zone delete)."""
        changes = []
        for page in self.client.get_paginator('list_resource_record_sets').paginate(HostedZoneId=zone_id):
            for rr in page.get('ResourceRecordSets', []) or []:
                if rr.get('Type') in ('SOA', 'NS') and rr.get('Name') == zone_name:
                    continue
                changes.append({'Action': 'DELETE', 'ResourceRecordSet': rr})
        if not changes:
            return
        for i in range(0, len(changes), 900):  # Route53 caps a ChangeBatch at 1000
            self.client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={'Comment': 'aws-cleanup: empty zone before delete',
                             'Changes': changes[i:i + 900]},
            )
        self.console.print(f"  removed {len(changes)} record set(s) from {zone_name}")
