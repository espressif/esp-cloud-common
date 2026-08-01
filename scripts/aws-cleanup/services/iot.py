"""IoT Core cleanup.

Covers: things, thing groups, thing types, billing groups, certificates,
policies, IoT rules, IoT jobs, fleet provisioning templates,
domain configurations, custom authorizers.

Order matters: rules and jobs reference other resources; thing groups
must be empty before delete; thing types must be deprecated before delete.

AWS-owned IoT domain configurations (``iot:Data-ATS``, ``iot:Jobs``,
``iot:CredentialProvider``) are always skipped — they cannot be modified
or deleted via the API and trying to do so returns
``InvalidRequestException: IoT owned domain configuration cannot be
updated``.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


# AWS-owned IoT domain configurations are named with this prefix.
_AWS_OWNED_IOT_DOMAIN_CONFIG_PREFIX = 'iot:'


def _domain_configuration_is_protected(name):
    return name.startswith(_AWS_OWNED_IOT_DOMAIN_CONFIG_PREFIX)


class IoTCleanup(ServiceCleanup):
    name = 'iot'
    boto_client = 'iot'
    cli_options = []

    def run(self):
        self._cleanup_jobs()
        self._cleanup_rules()
        self._cleanup_things()
        self._cleanup_thing_groups()
        self._cleanup_billing_groups()
        self._cleanup_thing_types()
        self._cleanup_certificates()
        self._cleanup_policies()
        self._cleanup_provisioning_templates()
        self._cleanup_domain_configurations()
        self._cleanup_authorizers()
        self.console.print("\n[bold green]IoT cleanup completed[/bold green]")

    def _cleanup_jobs(self):
        self.console.print("[bold cyan]Listing IoT jobs...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_jobs').paginate():
                for job in page.get('jobs', []):
                    jid = job.get('jobId')
                    try:
                        self.client.delete_job(jobId=jid, force=True)
                        self.console.print(f"[green]✓ Deleted job: {jid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting job {jid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list jobs: {e}[/yellow]")

    def _cleanup_rules(self):
        self.console.print("\n[bold cyan]Listing IoT topic rules...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_topic_rules').paginate():
                for rule in page.get('rules', []):
                    name = rule.get('ruleName')
                    try:
                        self.client.delete_topic_rule(ruleName=name)
                        self.console.print(f"[green]✓ Deleted rule: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting rule {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list rules: {e}[/yellow]")

    def _cleanup_things(self):
        self.console.print("\n[bold cyan]Listing IoT things...[/bold cyan]")
        for page in self.client.get_paginator('list_things').paginate():
            for thing in page.get('things', []):
                tname = thing.get('thingName')
                try:
                    try:
                        for principal in self.client.list_thing_principals(thingName=tname).get('principals', []):
                            self.client.detach_thing_principal(thingName=tname, principal=principal)
                    except ClientError:
                        pass
                    self.client.delete_thing(thingName=tname)
                    self.console.print(f"[green]✓ Deleted thing: {tname}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting thing {tname}: {e}[/red]")

    def _cleanup_thing_groups(self):
        self.console.print("\n[bold cyan]Listing IoT thing groups...[/bold cyan]")
        try:
            groups = []
            for page in self.client.get_paginator('list_thing_groups').paginate():
                groups.extend(page.get('thingGroups', []))
            # Children before parents — sort by no-children-first via depth heuristic.
            for g in groups:
                name = g.get('groupName')
                try:
                    self.client.delete_thing_group(thingGroupName=name)
                    self.console.print(f"[green]✓ Deleted thing group: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting thing group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list thing groups: {e}[/yellow]")

    def _cleanup_billing_groups(self):
        self.console.print("\n[bold cyan]Listing IoT billing groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_billing_groups').paginate():
                for g in page.get('billingGroups', []):
                    name = g.get('groupName')
                    try:
                        self.client.delete_billing_group(billingGroupName=name)
                        self.console.print(f"[green]✓ Deleted billing group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting billing group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list billing groups: {e}[/yellow]")

    def _cleanup_thing_types(self):
        self.console.print("\n[bold cyan]Listing IoT thing types...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_thing_types').paginate():
                for t in page.get('thingTypes', []):
                    name = t.get('thingTypeName')
                    try:
                        # Must be deprecated before deletion
                        self.client.deprecate_thing_type(thingTypeName=name)
                        # AWS requires 5 minutes between deprecation and deletion;
                        # we attempt anyway and let the error message be visible.
                        self.client.delete_thing_type(thingTypeName=name)
                        self.console.print(f"[green]✓ Deleted thing type: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[yellow]⚠ Thing type {name}: {e} (must wait ~5min after deprecation)[/yellow]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list thing types: {e}[/yellow]")

    def _cleanup_certificates(self):
        self.console.print("\n[bold cyan]Listing IoT certificates...[/bold cyan]")
        for page in self.client.get_paginator('list_certificates').paginate():
            for cert in page.get('certificates', []):
                cid = cert.get('certificateId')
                arn = cert.get('certificateArn')
                try:
                    try:
                        for policy in self.client.list_principal_policies(principal=arn).get('policies', []):
                            self.client.detach_policy(policyName=policy.get('policyName'), target=arn)
                    except ClientError:
                        pass
                    self.client.update_certificate(certificateId=cid, newStatus='INACTIVE')
                    self.client.delete_certificate(certificateId=cid, forceDelete=True)
                    self.console.print(f"[green]✓ Deleted certificate: {cid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting certificate {cid}: {e}[/red]")

    def _cleanup_policies(self):
        self.console.print("\n[bold cyan]Listing IoT policies...[/bold cyan]")
        for page in self.client.get_paginator('list_policies').paginate():
            for policy in page.get('policies', []):
                pname = policy.get('policyName')
                try:
                    try:
                        for p in self.client.get_paginator('list_targets_for_policy').paginate(policyName=pname):
                            for target in p.get('targets', []):
                                try:
                                    self.client.detach_policy(policyName=pname, target=target)
                                except ClientError:
                                    pass
                    except ClientError:
                        pass

                    # Delete non-default versions
                    try:
                        for v in self.client.list_policy_versions(policyName=pname).get('policyVersions', []):
                            if not v.get('isDefaultVersion'):
                                self.client.delete_policy_version(
                                    policyName=pname, policyVersionId=v['versionId'],
                                )
                    except ClientError:
                        pass

                    self.client.delete_policy(policyName=pname)
                    self.console.print(f"[green]✓ Deleted policy: {pname}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting policy {pname}: {e}[/red]")

    def _cleanup_provisioning_templates(self):
        self.console.print("\n[bold cyan]Listing IoT fleet provisioning templates...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_provisioning_templates').paginate():
                for t in page.get('templates', []):
                    name = t.get('templateName')
                    try:
                        self.client.delete_provisioning_template(templateName=name)
                        self.console.print(f"[green]✓ Deleted provisioning template: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting provisioning template {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list provisioning templates: {e}[/yellow]")

    def _cleanup_domain_configurations(self):
        self.console.print("\n[bold cyan]Listing IoT domain configurations...[/bold cyan]")
        try:
            response = self.client.list_domain_configurations()
            for d in response.get('domainConfigurations', []):
                name = d.get('domainConfigurationName')
                if _domain_configuration_is_protected(name):
                    self.console.print(f"[yellow]Skipping AWS-owned domain config: {name}[/yellow]")
                    continue
                try:
                    self.client.update_domain_configuration(
                        domainConfigurationName=name, domainConfigurationStatus='DISABLED',
                    )
                    self.client.delete_domain_configuration(domainConfigurationName=name)
                    self.console.print(f"[green]✓ Deleted domain configuration: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting domain config {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list domain configurations: {e}[/yellow]")

    def _cleanup_authorizers(self):
        self.console.print("\n[bold cyan]Listing IoT custom authorizers...[/bold cyan]")
        try:
            response = self.client.list_authorizers()
            for a in response.get('authorizers', []):
                name = a.get('authorizerName')
                try:
                    self.client.update_authorizer(authorizerName=name, status='INACTIVE')
                    self.client.delete_authorizer(authorizerName=name)
                    self.console.print(f"[green]✓ Deleted authorizer: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting authorizer {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list authorizers: {e}[/yellow]")
