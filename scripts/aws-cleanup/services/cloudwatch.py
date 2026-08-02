# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""CloudWatch-family cleanup.

Covers everything that lives under the CloudWatch console umbrella:
  - Log groups (CloudWatch Logs — ``logs`` client).
  - Alarms (metric + composite — ``cloudwatch`` client).
  - Dashboards.
  - Contributor Insight rules.
  - Synthetics canaries (running canaries are stopped first).

Metrics themselves are not deletable — they age out after 15 months.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class CloudWatchCleanup(ServiceCleanup):
    name = 'cloudwatch'
    boto_client = 'cloudwatch'  # used for alarms/dashboards/insight rules
    cli_options = []

    BATCH_SIZE = 100  # delete_alarms / delete_dashboards limits

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        logs_real = session.client('logs')
        synth_real = session.client('synthetics')
        self.logs = _DryRunClient(logs_real, 'logs', console) if dry_run else logs_real
        self.synthetics = _DryRunClient(synth_real, 'synthetics', console) if dry_run else synth_real

    def run(self):
        self._delete_log_groups()
        self._delete_alarms()
        self._delete_dashboards()
        self._delete_insight_rules()
        self._delete_canaries()
        self.console.print("\n[bold green]CloudWatch cleanup completed[/bold green]")

    def _delete_log_groups(self):
        self.console.print("[bold cyan]Listing CloudWatch log groups...[/bold cyan]")
        groups = []
        try:
            response = self.logs.describe_log_groups()
            groups.extend(response.get('logGroups', []))
            while 'nextToken' in response:
                response = self.logs.describe_log_groups(nextToken=response['nextToken'])
                groups.extend(response.get('logGroups', []))
        except ClientError as e:
            self.console.print(f"[red]Error listing log groups: {e}[/red]")
            return

        for g in groups:
            name = g.get('logGroupName')
            try:
                self.logs.delete_log_group(logGroupName=name)
                self.console.print(f"[green]✓ Deleted log group: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting log group {name}: {e}[/red]")

    def _delete_alarms(self):
        self.console.print("\n[bold cyan]Listing CloudWatch alarms...[/bold cyan]")
        metric_names, composite_names = [], []
        try:
            for page in self.client.get_paginator('describe_alarms').paginate():
                metric_names.extend(a['AlarmName'] for a in page.get('MetricAlarms', []))
                composite_names.extend(a['AlarmName'] for a in page.get('CompositeAlarms', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list alarms: {e}[/yellow]")
            return

        # Delete composite alarms first — they reference metric alarms.
        for batch_names, kind in [(composite_names, 'composite'), (metric_names, 'metric')]:
            for i in range(0, len(batch_names), self.BATCH_SIZE):
                batch = batch_names[i:i + self.BATCH_SIZE]
                try:
                    self.client.delete_alarms(AlarmNames=batch)
                    self.console.print(f"[green]✓ Deleted {len(batch)} {kind} alarms[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting {kind} alarm batch: {e}[/red]")

    def _delete_dashboards(self):
        self.console.print("\n[bold cyan]Listing CloudWatch dashboards...[/bold cyan]")
        names = []
        try:
            for page in self.client.get_paginator('list_dashboards').paginate():
                names.extend(d['DashboardName'] for d in page.get('DashboardEntries', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list dashboards: {e}[/yellow]")
            return

        for i in range(0, len(names), self.BATCH_SIZE):
            batch = names[i:i + self.BATCH_SIZE]
            try:
                self.client.delete_dashboards(DashboardNames=batch)
                self.console.print(f"[green]✓ Deleted {len(batch)} dashboards[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting dashboard batch: {e}[/red]")

    def _delete_insight_rules(self):
        self.console.print("\n[bold cyan]Listing Contributor Insight rules...[/bold cyan]")
        names = []
        try:
            response = self.client.describe_insight_rules()
            names.extend(r['Name'] for r in response.get('InsightRules', []))
            while response.get('NextToken'):
                response = self.client.describe_insight_rules(NextToken=response['NextToken'])
                names.extend(r['Name'] for r in response.get('InsightRules', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list insight rules: {e}[/yellow]")
            return

        if names:
            try:
                self.client.delete_insight_rules(RuleNames=names)
                self.console.print(f"[green]✓ Deleted {len(names)} insight rules[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting insight rules: {e}[/red]")

    def _delete_canaries(self):
        self.console.print("\n[bold cyan]Listing Synthetics canaries...[/bold cyan]")
        canaries = []
        try:
            response = self.synthetics.describe_canaries()
            canaries.extend(response.get('Canaries', []))
            while response.get('NextToken'):
                response = self.synthetics.describe_canaries(NextToken=response['NextToken'])
                canaries.extend(response.get('Canaries', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list canaries: {e}[/yellow]")
            return

        for c in canaries:
            name = c.get('Name')
            state = c.get('Status', {}).get('State')
            try:
                if state == 'RUNNING':
                    self.synthetics.stop_canary(Name=name)
                self.synthetics.delete_canary(Name=name)
                self.console.print(f"[green]✓ Deleted canary: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting canary {name}: {e}[/red]")
