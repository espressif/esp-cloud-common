import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


class CloudFrontCleanup(ServiceCleanup):
    name = 'cloudfront'
    boto_client = 'cloudfront'
    cli_options = [
        click.option(
            '--cloudfront-name-include-prefix', 'cloudfront_name_include_prefixes', multiple=True,
            help='Only process CloudFront distributions whose domain name starts with one of '
                 'these prefixes. Repeatable. If unset, all distributions are processed.',
        ),
    ]

    def run(self):
        include = tuple(self.options.get('cloudfront_name_include_prefixes') or ())

        self.console.print("[bold cyan]Listing CloudFront distributions...[/bold cyan]")
        distributions = []
        for page in self.client.get_paginator('list_distributions').paginate():
            for dist in page.get('DistributionList', {}).get('Items', []) or []:
                domain = (dist.get('DomainName') or '').lower()
                if include and not domain.startswith(tuple(p.lower() for p in include)):
                    continue
                distributions.append(dist)
                self.console.print(f"Found distribution: {domain} (ID: {dist.get('Id')})")

        if distributions:
            self.console.print(f"\n[bold cyan]Found {len(distributions)} distributions to delete[/bold cyan]")
            for dist in distributions:
                dist_id = dist.get('Id')
                domain = dist.get('DomainName')
                try:
                    config_resp = self.client.get_distribution_config(Id=dist_id)
                    etag = config_resp.get('ETag')
                    config = config_resp.get('DistributionConfig')
                    # Disable first if still enabled (skip the redundant update if already disabled).
                    if config.get('Enabled'):
                        config['Enabled'] = False
                        self.client.update_distribution(Id=dist_id, DistributionConfig=config, IfMatch=etag)
                    # ALWAYS wait for Deployed before deleting — a distribution that is disabled but
                    # still propagating (Status=InProgress, e.g. from an interrupted prior run or an
                    # out-of-band disable) is not yet deletable and would 409. The waiter returns
                    # immediately when already Deployed, so this is cheap in the common case.
                    self.client.get_waiter('distribution_deployed').wait(
                        Id=dist_id, WaiterConfig={'Delay': 30, 'MaxAttempts': 60})
                    # Re-fetch the current ETag immediately before delete: the disable rotates it,
                    # and delete_distribution with a stale ETag is a hard PreconditionFailed.
                    etag = self.client.get_distribution_config(Id=dist_id).get('ETag')
                    self.client.delete_distribution(Id=dist_id, IfMatch=etag)
                    self.console.print(f"[green]✓ Deleted distribution: {domain}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting distribution {domain}: {e}[/red]")

        self.console.print("\n[bold cyan]Listing CloudFront field-level encryption configs...[/bold cyan]")
        try:
            response = self.client.list_field_level_encryption_configs()
            for policy in response.get('FieldLevelEncryptionList', {}).get('Items', []) or []:
                policy_id = policy.get('Id')
                policy_name = (policy.get('Name') or '').lower()
                if include and not policy_name.startswith(tuple(p.lower() for p in include)):
                    continue
                try:
                    self.client.delete_field_level_encryption_config(Id=policy_id)
                    self.console.print(f"[green]✓ Deleted FLE config: {policy_name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting FLE config {policy_name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list FLE configs: {e}[/yellow]")

        self._delete_origin_access_identities()
        self._delete_origin_access_controls()
        self._delete_custom_policies('cache', 'list_cache_policies', 'CachePolicyList',
                                     'CachePolicySummary', 'CachePolicy', 'delete_cache_policy')
        self._delete_custom_policies('origin-request', 'list_origin_request_policies',
                                     'OriginRequestPolicyList', 'OriginRequestPolicySummary',
                                     'OriginRequestPolicy', 'delete_origin_request_policy')
        self._delete_custom_policies('response-headers', 'list_response_headers_policies',
                                     'ResponseHeadersPolicyList', 'ResponseHeadersPolicySummary',
                                     'ResponseHeadersPolicy', 'delete_response_headers_policy')
        self._delete_functions()
        self._delete_key_value_stores()
        self.console.print("\n[bold green]CloudFront cleanup completed[/bold green]")

    def _delete_origin_access_identities(self):
        self.console.print("\n[bold cyan]Listing CloudFront origin access identities...[/bold cyan]")
        try:
            response = self.client.list_cloud_front_origin_access_identities()
            for oai in response.get('CloudFrontOriginAccessIdentityList', {}).get('Items', []) or []:
                oid = oai.get('Id')
                try:
                    detail = self.client.get_cloud_front_origin_access_identity(Id=oid)
                    self.client.delete_cloud_front_origin_access_identity(Id=oid, IfMatch=detail['ETag'])
                    self.console.print(f"[green]✓ Deleted OAI: {oid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting OAI {oid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list OAIs: {e}[/yellow]")

    def _delete_origin_access_controls(self):
        self.console.print("\n[bold cyan]Listing CloudFront origin access controls...[/bold cyan]")
        try:
            response = self.client.list_origin_access_controls()
            for oac in response.get('OriginAccessControlList', {}).get('Items', []) or []:
                oid = oac.get('Id')
                try:
                    detail = self.client.get_origin_access_control(Id=oid)
                    self.client.delete_origin_access_control(Id=oid, IfMatch=detail['ETag'])
                    self.console.print(f"[green]✓ Deleted OAC: {oid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting OAC {oid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list OACs: {e}[/yellow]")

    def _delete_custom_policies(self, label, list_method, list_key, summary_key, policy_field, delete_method):
        self.console.print(f"\n[bold cyan]Listing CloudFront {label} policies (custom)...[/bold cyan]")
        try:
            response = getattr(self.client, list_method)(Type='custom')
            for item in response.get(list_key, {}).get('Items', []) or []:
                summary = item.get(policy_field, item)
                pid = summary.get('Id')
                pname = summary.get(policy_field, {}).get('Config', {}).get('Name') or summary.get('Id')
                try:
                    # Need ETag — fetch the resource
                    get_method = list_method.replace('list_', 'get_').rstrip('s')
                    detail = getattr(self.client, get_method)(Id=pid)
                    getattr(self.client, delete_method)(Id=pid, IfMatch=detail['ETag'])
                    self.console.print(f"[green]✓ Deleted {label} policy: {pname}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting {label} policy {pid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list {label} policies: {e}[/yellow]")

    def _delete_functions(self):
        self.console.print("\n[bold cyan]Listing CloudFront functions...[/bold cyan]")
        try:
            response = self.client.list_functions()
            for f in response.get('FunctionList', {}).get('Items', []) or []:
                name = f.get('Name')
                try:
                    detail = self.client.describe_function(Name=name)
                    self.client.delete_function(Name=name, IfMatch=detail['ETag'])
                    self.console.print(f"[green]✓ Deleted CloudFront function: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting CloudFront function {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list CloudFront functions: {e}[/yellow]")

    def _delete_key_value_stores(self):
        self.console.print("\n[bold cyan]Listing CloudFront KeyValueStores...[/bold cyan]")
        try:
            response = self.client.list_key_value_stores()
            for kvs in response.get('KeyValueStoreList', {}).get('Items', []) or []:
                name = kvs.get('Name')
                try:
                    detail = self.client.describe_key_value_store(Name=name)
                    self.client.delete_key_value_store(Name=name, IfMatch=detail['ETag'])
                    self.console.print(f"[green]✓ Deleted KeyValueStore: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting KeyValueStore {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list KeyValueStores: {e}[/yellow]")
