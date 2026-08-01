"""EMR cleanup — classic EMR clusters and EMR Serverless applications."""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class EMRCleanup(ServiceCleanup):
    name = 'emr'
    boto_client = 'emr'
    cli_options = []

    ACTIVE_STATES = ['STARTING', 'BOOTSTRAPPING', 'RUNNING', 'WAITING']

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        serverless_real = session.client('emr-serverless')
        self.serverless = _DryRunClient(serverless_real, 'emr-serverless', console) if dry_run else serverless_real

    def run(self):
        self._terminate_clusters()
        self._delete_serverless_applications()
        self.console.print("\n[bold green]EMR cleanup completed[/bold green]")

    def _terminate_clusters(self):
        self.console.print("[bold cyan]Listing EMR clusters...[/bold cyan]")
        cluster_ids = []
        try:
            for page in self.client.get_paginator('list_clusters').paginate(ClusterStates=self.ACTIVE_STATES):
                for c in page.get('Clusters', []):
                    cluster_ids.append(c.get('Id'))
                    self.console.print(f"Found EMR cluster: {c.get('Name')} ({c.get('Id')})")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list EMR clusters: {e}[/yellow]")
            return

        if not cluster_ids:
            return

        try:
            self.client.terminate_job_flows(JobFlowIds=cluster_ids)
            self.console.print(f"[green]✓ Terminated {len(cluster_ids)} EMR clusters[/green]")
        except ClientError as e:
            self.console.print(f"[red]✗ Error terminating EMR clusters: {e}[/red]")

    def _delete_serverless_applications(self):
        self.console.print("\n[bold cyan]Listing EMR Serverless applications...[/bold cyan]")
        try:
            for page in self.serverless.get_paginator('list_applications').paginate():
                for app in page.get('applications', []):
                    aid = app.get('id')
                    name = app.get('name')
                    state = app.get('state')
                    try:
                        if state == 'STARTED':
                            self.serverless.stop_application(applicationId=aid)
                        self.serverless.delete_application(applicationId=aid)
                        self.console.print(f"[green]✓ Deleted EMR Serverless application: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting EMR Serverless app {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list EMR Serverless applications: {e}[/yellow]")
