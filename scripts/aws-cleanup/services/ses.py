# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""SES cleanup — both legacy SES (``ses``) and SES v2 (``sesv2``).

Covers: identities (email/domain), configuration sets, templates, contact
lists (v2), receipt rules + rule sets (v1), custom verification email
templates (v1).

Identity DKIM tokens and SES sandbox state are not deletable (account-level
config). This sweep is destructive — verified domain identities will need
re-verification after.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class SESCleanup(ServiceCleanup):
    name = 'ses'
    boto_client = 'ses'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        v2_real = session.client('sesv2')
        self.v2 = _DryRunClient(v2_real, 'sesv2', console) if dry_run else v2_real

    def run(self):
        self._delete_v2_contact_lists()
        self._delete_v2_email_templates()
        self._delete_v2_configuration_sets()
        self._delete_v2_email_identities()
        self._delete_v1_receipt_rule_sets()
        self._delete_v1_custom_verification_templates()
        self._delete_v1_templates()
        self._delete_v1_configuration_sets()
        self._delete_v1_identities()
        self.console.print("\n[bold green]SES cleanup completed[/bold green]")

    def _delete_v2_contact_lists(self):
        self.console.print("[bold cyan]Listing SESv2 contact lists...[/bold cyan]")
        try:
            response = self.v2.list_contact_lists()
            for cl in response.get('ContactLists', []):
                name = cl.get('ContactListName')
                try:
                    self.v2.delete_contact_list(ContactListName=name)
                    self.console.print(f"[green]✓ Deleted contact list: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting contact list {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list contact lists: {e}[/yellow]")

    def _delete_v2_email_templates(self):
        self.console.print("\n[bold cyan]Listing SESv2 email templates...[/bold cyan]")
        try:
            response = self.v2.list_email_templates()
            for t in response.get('TemplatesMetadata', []):
                name = t.get('TemplateName')
                try:
                    self.v2.delete_email_template(TemplateName=name)
                    self.console.print(f"[green]✓ Deleted v2 template: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v2 template {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v2 templates: {e}[/yellow]")

    def _delete_v2_configuration_sets(self):
        self.console.print("\n[bold cyan]Listing SESv2 configuration sets...[/bold cyan]")
        try:
            response = self.v2.list_configuration_sets()
            for name in response.get('ConfigurationSets', []):
                try:
                    self.v2.delete_configuration_set(ConfigurationSetName=name)
                    self.console.print(f"[green]✓ Deleted v2 config set: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v2 config set {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v2 config sets: {e}[/yellow]")

    def _delete_v2_email_identities(self):
        self.console.print("\n[bold cyan]Listing SESv2 email identities...[/bold cyan]")
        try:
            response = self.v2.list_email_identities()
            for ident in response.get('EmailIdentities', []):
                name = ident.get('IdentityName')
                try:
                    self.v2.delete_email_identity(EmailIdentity=name)
                    self.console.print(f"[green]✓ Deleted v2 identity: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v2 identity {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v2 identities: {e}[/yellow]")

    def _delete_v1_receipt_rule_sets(self):
        self.console.print("\n[bold cyan]Listing SES receipt rule sets...[/bold cyan]")
        try:
            response = self.client.list_receipt_rule_sets()
            for rs in response.get('RuleSets', []):
                name = rs.get('Name')
                try:
                    self.client.delete_receipt_rule_set(RuleSetName=name)
                    self.console.print(f"[green]✓ Deleted receipt rule set: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting rule set {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list receipt rule sets: {e}[/yellow]")

    def _delete_v1_custom_verification_templates(self):
        self.console.print("\n[bold cyan]Listing SES custom verification email templates...[/bold cyan]")
        try:
            response = self.client.list_custom_verification_email_templates()
            for t in response.get('CustomVerificationEmailTemplates', []):
                name = t.get('TemplateName')
                try:
                    self.client.delete_custom_verification_email_template(TemplateName=name)
                    self.console.print(f"[green]✓ Deleted custom verification template: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting custom verification template {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list custom verification templates: {e}[/yellow]")

    def _delete_v1_templates(self):
        self.console.print("\n[bold cyan]Listing SES (v1) templates...[/bold cyan]")
        try:
            response = self.client.list_templates()
            for t in response.get('TemplatesMetadata', []):
                name = t.get('Name')
                try:
                    self.client.delete_template(TemplateName=name)
                    self.console.print(f"[green]✓ Deleted v1 template: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v1 template {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v1 templates: {e}[/yellow]")

    def _delete_v1_configuration_sets(self):
        self.console.print("\n[bold cyan]Listing SES (v1) configuration sets...[/bold cyan]")
        try:
            response = self.client.list_configuration_sets()
            for cs in response.get('ConfigurationSets', []):
                name = cs.get('Name')
                try:
                    self.client.delete_configuration_set(ConfigurationSetName=name)
                    self.console.print(f"[green]✓ Deleted v1 config set: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v1 config set {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v1 config sets: {e}[/yellow]")

    def _delete_v1_identities(self):
        self.console.print("\n[bold cyan]Listing SES (v1) identities...[/bold cyan]")
        try:
            response = self.client.list_identities()
            for ident in response.get('Identities', []):
                try:
                    self.client.delete_identity(Identity=ident)
                    self.console.print(f"[green]✓ Deleted v1 identity: {ident}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting v1 identity {ident}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list v1 identities: {e}[/yellow]")
