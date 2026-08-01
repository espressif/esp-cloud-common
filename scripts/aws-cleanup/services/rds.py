"""RDS cleanup — DB instances, clusters, manual snapshots.

RDS is normally protected by deletion protection and final-snapshot
requirements. This sweep disables both. Aurora cluster instances must be
removed before the cluster itself.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class RDSCleanup(ServiceCleanup):
    name = 'rds'
    boto_client = 'rds'
    cli_options = []

    def run(self):
        self._delete_proxies()
        self._delete_instances()
        self._delete_clusters()
        self._delete_db_snapshots()
        self._delete_cluster_snapshots()
        self._delete_event_subscriptions()
        self._delete_parameter_groups()
        self._delete_cluster_parameter_groups()
        self._delete_option_groups()
        self._delete_subnet_groups()
        self.console.print("\n[bold green]RDS cleanup completed[/bold green]")

    def _delete_proxies(self):
        self.console.print("[bold cyan]Listing RDS proxies...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_db_proxies').paginate():
                for p in page.get('DBProxies', []):
                    name = p.get('DBProxyName')
                    try:
                        self.client.delete_db_proxy(DBProxyName=name)
                        self.console.print(f"[green]✓ Deleted RDS proxy: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting RDS proxy {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list RDS proxies: {e}[/yellow]")

    def _delete_event_subscriptions(self):
        self.console.print("\n[bold cyan]Listing RDS event subscriptions...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_event_subscriptions').paginate():
                for s in page.get('EventSubscriptionsList', []):
                    name = s.get('CustSubscriptionId')
                    try:
                        self.client.delete_event_subscription(SubscriptionName=name)
                        self.console.print(f"[green]✓ Deleted event subscription: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting event subscription {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list event subscriptions: {e}[/yellow]")

    def _delete_parameter_groups(self):
        self.console.print("\n[bold cyan]Listing DB parameter groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_db_parameter_groups').paginate():
                for pg in page.get('DBParameterGroups', []):
                    name = pg.get('DBParameterGroupName')
                    if name.startswith('default.'):
                        continue
                    try:
                        self.client.delete_db_parameter_group(DBParameterGroupName=name)
                        self.console.print(f"[green]✓ Deleted DB parameter group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting parameter group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list parameter groups: {e}[/yellow]")

    def _delete_cluster_parameter_groups(self):
        self.console.print("\n[bold cyan]Listing DB cluster parameter groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_db_cluster_parameter_groups').paginate():
                for pg in page.get('DBClusterParameterGroups', []):
                    name = pg.get('DBClusterParameterGroupName')
                    if name.startswith('default.'):
                        continue
                    try:
                        self.client.delete_db_cluster_parameter_group(DBClusterParameterGroupName=name)
                        self.console.print(f"[green]✓ Deleted cluster parameter group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting cluster parameter group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list cluster parameter groups: {e}[/yellow]")

    def _delete_option_groups(self):
        self.console.print("\n[bold cyan]Listing DB option groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_option_groups').paginate():
                for og in page.get('OptionGroupsList', []):
                    name = og.get('OptionGroupName')
                    if name.startswith('default:'):
                        continue
                    try:
                        self.client.delete_option_group(OptionGroupName=name)
                        self.console.print(f"[green]✓ Deleted option group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting option group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list option groups: {e}[/yellow]")

    def _delete_subnet_groups(self):
        self.console.print("\n[bold cyan]Listing DB subnet groups...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_db_subnet_groups').paginate():
                for sg in page.get('DBSubnetGroups', []):
                    name = sg.get('DBSubnetGroupName')
                    if name == 'default':
                        continue
                    try:
                        self.client.delete_db_subnet_group(DBSubnetGroupName=name)
                        self.console.print(f"[green]✓ Deleted DB subnet group: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting subnet group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list subnet groups: {e}[/yellow]")

    def _delete_instances(self):
        self.console.print("[bold cyan]Listing RDS DB instances...[/bold cyan]")
        for page in self.client.get_paginator('describe_db_instances').paginate():
            for db in page.get('DBInstances', []):
                ident = db.get('DBInstanceIdentifier')
                self.console.print(f"Found DB instance: {ident}")
                try:
                    if db.get('DeletionProtection'):
                        self.client.modify_db_instance(
                            DBInstanceIdentifier=ident,
                            DeletionProtection=False,
                            ApplyImmediately=True,
                        )
                    self.client.delete_db_instance(
                        DBInstanceIdentifier=ident,
                        SkipFinalSnapshot=True,
                        DeleteAutomatedBackups=True,
                    )
                    self.console.print(f"[green]✓ Deleted DB instance: {ident}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting DB instance {ident}: {e}[/red]")

    def _delete_clusters(self):
        self.console.print("\n[bold cyan]Listing RDS DB clusters...[/bold cyan]")
        for page in self.client.get_paginator('describe_db_clusters').paginate():
            for cluster in page.get('DBClusters', []):
                ident = cluster.get('DBClusterIdentifier')
                self.console.print(f"Found DB cluster: {ident}")
                try:
                    if cluster.get('DeletionProtection'):
                        self.client.modify_db_cluster(
                            DBClusterIdentifier=ident,
                            DeletionProtection=False,
                            ApplyImmediately=True,
                        )
                    self.client.delete_db_cluster(
                        DBClusterIdentifier=ident,
                        SkipFinalSnapshot=True,
                    )
                    self.console.print(f"[green]✓ Deleted DB cluster: {ident}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting DB cluster {ident}: {e}[/red]")

    def _delete_db_snapshots(self):
        self.console.print("\n[bold cyan]Listing manual DB snapshots...[/bold cyan]")
        for page in self.client.get_paginator('describe_db_snapshots').paginate(SnapshotType='manual'):
            for snap in page.get('DBSnapshots', []):
                sid = snap.get('DBSnapshotIdentifier')
                try:
                    self.client.delete_db_snapshot(DBSnapshotIdentifier=sid)
                    self.console.print(f"[green]✓ Deleted DB snapshot: {sid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting DB snapshot {sid}: {e}[/red]")

    def _delete_cluster_snapshots(self):
        self.console.print("\n[bold cyan]Listing manual DB cluster snapshots...[/bold cyan]")
        for page in self.client.get_paginator('describe_db_cluster_snapshots').paginate(SnapshotType='manual'):
            for snap in page.get('DBClusterSnapshots', []):
                sid = snap.get('DBClusterSnapshotIdentifier')
                try:
                    self.client.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=sid)
                    self.console.print(f"[green]✓ Deleted cluster snapshot: {sid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting cluster snapshot {sid}: {e}[/red]")
