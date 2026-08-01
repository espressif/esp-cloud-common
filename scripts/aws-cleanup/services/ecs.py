"""ECS cleanup — services and tasks first, then clusters, then task definitions.

Service deletion requires desiredCount=0 first. Standalone running tasks are
stopped explicitly. Task definitions are deregistered (AWS keeps them as
INACTIVE — there is no way to fully purge them via API).
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class ECSCleanup(ServiceCleanup):
    name = 'ecs'
    boto_client = 'ecs'
    cli_options = []

    def run(self):
        cluster_arns = self._list_cluster_arns()
        for arn in cluster_arns:
            self._drain_and_delete_services(arn)
            self._stop_standalone_tasks(arn)
            self._delete_cluster(arn)
        self._deregister_task_definitions()
        self.console.print("\n[bold green]ECS cleanup completed[/bold green]")

    def _list_cluster_arns(self):
        self.console.print("[bold cyan]Listing ECS clusters...[/bold cyan]")
        arns = []
        for page in self.client.get_paginator('list_clusters').paginate():
            for arn in page.get('clusterArns', []):
                arns.append(arn)
                self.console.print(f"Found cluster: {arn}")
        return arns

    def _drain_and_delete_services(self, cluster_arn):
        try:
            paginator = self.client.get_paginator('list_services')
            service_arns = []
            for page in paginator.paginate(cluster=cluster_arn):
                service_arns.extend(page.get('serviceArns', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list services on {cluster_arn}: {e}[/yellow]")
            return

        for s_arn in service_arns:
            try:
                self.client.update_service(cluster=cluster_arn, service=s_arn, desiredCount=0)
                self.client.delete_service(cluster=cluster_arn, service=s_arn, force=True)
                self.console.print(f"[green]✓ Deleted service: {s_arn}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting service {s_arn}: {e}[/red]")

    def _stop_standalone_tasks(self, cluster_arn):
        try:
            paginator = self.client.get_paginator('list_tasks')
            task_arns = []
            for page in paginator.paginate(cluster=cluster_arn):
                task_arns.extend(page.get('taskArns', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list tasks on {cluster_arn}: {e}[/yellow]")
            return

        for t_arn in task_arns:
            try:
                self.client.stop_task(cluster=cluster_arn, task=t_arn, reason='aws-cleanup')
                self.console.print(f"[green]✓ Stopped task: {t_arn}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error stopping task {t_arn}: {e}[/red]")

    def _delete_cluster(self, cluster_arn):
        try:
            self.client.delete_cluster(cluster=cluster_arn)
            self.console.print(f"[green]✓ Deleted cluster: {cluster_arn}[/green]")
        except ClientError as e:
            self.console.print(f"[red]✗ Error deleting cluster {cluster_arn}: {e}[/red]")

    def _deregister_task_definitions(self):
        self.console.print("\n[bold cyan]Deregistering ACTIVE task definitions...[/bold cyan]")
        try:
            paginator = self.client.get_paginator('list_task_definitions')
            for page in paginator.paginate(status='ACTIVE'):
                for arn in page.get('taskDefinitionArns', []):
                    try:
                        self.client.deregister_task_definition(taskDefinition=arn)
                        self.console.print(f"[green]✓ Deregistered: {arn}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deregistering {arn}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list task definitions: {e}[/yellow]")
