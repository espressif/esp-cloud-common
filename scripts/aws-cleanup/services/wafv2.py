# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""WAFv2 cleanup — REGIONAL and CLOUDFRONT scopes.

Web ACLs and rule groups require a LockToken on delete. The CLOUDFRONT scope
must be queried from us-east-1 — boto3 does this automatically when the
client region is set; if your sweep targets another region, the CLOUDFRONT
section may be empty.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class WAFv2Cleanup(ServiceCleanup):
    name = 'wafv2'
    boto_client = 'wafv2'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        # CLOUDFRONT scope must be queried from us-east-1 regardless of session region.
        cf_real = session.client('wafv2', region_name='us-east-1')
        self.cf_client = _DryRunClient(cf_real, 'wafv2', console) if dry_run else cf_real

    def run(self):
        self._delete_for_scope(self.client, 'REGIONAL')
        self._delete_for_scope(self.cf_client, 'CLOUDFRONT')
        self.console.print("\n[bold green]WAFv2 cleanup completed[/bold green]")

    def _delete_for_scope(self, client, scope):
        self.console.print(f"\n[bold cyan]Listing WAFv2 web ACLs ({scope})...[/bold cyan]")
        try:
            response = client.list_web_acls(Scope=scope)
            acls = response.get('WebACLs', [])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list web ACLs in {scope}: {e}[/yellow]")
            return

        for acl in acls:
            name = acl.get('Name')
            acl_id = acl.get('Id')
            lock = acl.get('LockToken')
            try:
                client.delete_web_acl(Name=name, Id=acl_id, Scope=scope, LockToken=lock)
                self.console.print(f"[green]✓ Deleted web ACL ({scope}): {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting web ACL {name} ({scope}): {e}[/red]")

        self.console.print(f"\n[bold cyan]Listing WAFv2 rule groups ({scope})...[/bold cyan]")
        try:
            response = client.list_rule_groups(Scope=scope)
            groups = response.get('RuleGroups', [])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list rule groups in {scope}: {e}[/yellow]")
            groups = []

        for rg in groups:
            name = rg.get('Name')
            rg_id = rg.get('Id')
            lock = rg.get('LockToken')
            try:
                client.delete_rule_group(Name=name, Id=rg_id, Scope=scope, LockToken=lock)
                self.console.print(f"[green]✓ Deleted rule group ({scope}): {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting rule group {name} ({scope}): {e}[/red]")

        self.console.print(f"\n[bold cyan]Listing WAFv2 IP sets ({scope})...[/bold cyan]")
        try:
            for ip_set in client.list_ip_sets(Scope=scope).get('IPSets', []):
                name = ip_set.get('Name')
                ip_id = ip_set.get('Id')
                lock = ip_set.get('LockToken')
                try:
                    client.delete_ip_set(Name=name, Id=ip_id, Scope=scope, LockToken=lock)
                    self.console.print(f"[green]✓ Deleted IP set ({scope}): {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting IP set {name} ({scope}): {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list IP sets in {scope}: {e}[/yellow]")

        self.console.print(f"\n[bold cyan]Listing WAFv2 regex pattern sets ({scope})...[/bold cyan]")
        try:
            for rps in client.list_regex_pattern_sets(Scope=scope).get('RegexPatternSets', []):
                name = rps.get('Name')
                rps_id = rps.get('Id')
                lock = rps.get('LockToken')
                try:
                    client.delete_regex_pattern_set(Name=name, Id=rps_id, Scope=scope, LockToken=lock)
                    self.console.print(f"[green]✓ Deleted regex pattern set ({scope}): {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting regex pattern set {name} ({scope}): {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list regex pattern sets in {scope}: {e}[/yellow]")
