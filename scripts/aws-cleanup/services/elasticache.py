from botocore.exceptions import ClientError

from .base import ServiceCleanup


class ElastiCacheCleanup(ServiceCleanup):
    """ElastiCache cleanup — replication groups first, then standalone clusters."""

    name = 'elasticache'
    boto_client = 'elasticache'
    cli_options = []

    def run(self):
        self._delete_replication_groups()
        self._delete_clusters()
        self._delete_snapshots()
        self._delete_user_groups()
        self._delete_users()
        self._delete_parameter_groups()
        self._delete_subnet_groups()
        self.console.print("\n[bold green]ElastiCache cleanup completed[/bold green]")

    def _delete_snapshots(self):
        self.console.print("\n[bold cyan]Listing ElastiCache snapshots (manual)...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_snapshots').paginate(SnapshotSource='user'):
                for s in page.get('Snapshots', []):
                    name = s.get('SnapshotName')
                    try:
                        self.client.delete_snapshot(SnapshotName=name)
                        self.console.print(f"[green]✓ Deleted snapshot: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting snapshot {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list snapshots: {e}[/yellow]")

    def _delete_user_groups(self):
        self.console.print("\n[bold cyan]Listing ElastiCache user groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_user_groups').paginate():
                for ug in page.get('UserGroups', []):
                    gid = ug.get('UserGroupId')
                    try:
                        self.client.delete_user_group(UserGroupId=gid)
                        self.console.print(f"[green]✓ Deleted user group: {gid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting user group {gid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list user groups: {e}[/yellow]")

    def _delete_users(self):
        self.console.print("\n[bold cyan]Listing ElastiCache users...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_users').paginate():
                for u in page.get('Users', []):
                    uid = u.get('UserId')
                    if uid == 'default':
                        continue
                    try:
                        self.client.delete_user(UserId=uid)
                        self.console.print(f"[green]✓ Deleted user: {uid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting user {uid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list users: {e}[/yellow]")

    def _delete_parameter_groups(self):
        self.console.print("\n[bold cyan]Listing ElastiCache parameter groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_cache_parameter_groups').paginate():
                for pg in page.get('CacheParameterGroups', []):
                    name = pg.get('CacheParameterGroupName')
                    if name.startswith('default.'):
                        continue
                    try:
                        self.client.delete_cache_parameter_group(CacheParameterGroupName=name)
                        self.console.print(f"[green]✓ Deleted parameter group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting parameter group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list parameter groups: {e}[/yellow]")

    def _delete_subnet_groups(self):
        self.console.print("\n[bold cyan]Listing ElastiCache subnet groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_cache_subnet_groups').paginate():
                for sg in page.get('CacheSubnetGroups', []):
                    name = sg.get('CacheSubnetGroupName')
                    if name == 'default':
                        continue
                    try:
                        self.client.delete_cache_subnet_group(CacheSubnetGroupName=name)
                        self.console.print(f"[green]✓ Deleted subnet group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting subnet group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list subnet groups: {e}[/yellow]")

    def _delete_replication_groups(self):
        self.console.print("[bold cyan]Listing ElastiCache replication groups...[/bold cyan]")
        for page in self.client.get_paginator('describe_replication_groups').paginate():
            for rg in page.get('ReplicationGroups', []):
                rid = rg.get('ReplicationGroupId')
                self.console.print(f"Found replication group: {rid}")
                try:
                    self.client.delete_replication_group(
                        ReplicationGroupId=rid,
                        RetainPrimaryCluster=False,
                    )
                    self.console.print(f"[green]✓ Deleted replication group: {rid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting replication group {rid}: {e}[/red]")

    def _delete_clusters(self):
        self.console.print("\n[bold cyan]Listing ElastiCache cache clusters...[/bold cyan]")
        for page in self.client.get_paginator('describe_cache_clusters').paginate():
            for cluster in page.get('CacheClusters', []):
                # Skip clusters that are part of a replication group (deleted above).
                if cluster.get('ReplicationGroupId'):
                    continue
                cid = cluster.get('CacheClusterId')
                self.console.print(f"Found cache cluster: {cid}")
                try:
                    self.client.delete_cache_cluster(CacheClusterId=cid)
                    self.console.print(f"[green]✓ Deleted cache cluster: {cid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting cache cluster {cid}: {e}[/red]")
