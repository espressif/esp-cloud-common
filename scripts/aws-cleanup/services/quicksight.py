"""QuickSight cleanup.

QuickSight resources are scoped to AWS account ID; we look it up via STS.
Deletes datasets, dashboards, analyses, themes, data sources, folders.
Does not unsubscribe the account itself.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class QuickSightCleanup(ServiceCleanup):
    name = 'quicksight'
    boto_client = 'quicksight'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        self.account_id = None
        try:
            self.account_id = session.client('sts').get_caller_identity().get('Account')
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not determine account ID: {e}[/yellow]")

    def run(self):
        if not self.account_id:
            self.console.print("[yellow]Skipping QuickSight (no account ID)[/yellow]")
            return

        for label, list_method, items_key, id_field, delete_method, delete_kwarg in [
            ('dashboard', 'list_dashboards', 'DashboardSummaryList', 'DashboardId', 'delete_dashboard', 'DashboardId'),
            ('analysis', 'list_analyses', 'AnalysisSummaryList', 'AnalysisId', 'delete_analysis', 'AnalysisId'),
            ('dataset', 'list_data_sets', 'DataSetSummaries', 'DataSetId', 'delete_data_set', 'DataSetId'),
            ('data source', 'list_data_sources', 'DataSources', 'DataSourceId', 'delete_data_source', 'DataSourceId'),
            ('theme', 'list_themes', 'ThemeSummaryList', 'ThemeId', 'delete_theme', 'ThemeId'),
            ('folder', 'list_folders', 'FolderSummaryList', 'FolderId', 'delete_folder', 'FolderId'),
        ]:
            self.console.print(f"\n[bold cyan]Listing QuickSight {label}s...[/bold cyan]")
            try:
                paginator = self.client.get_paginator(list_method)
                for page in paginator.paginate(AwsAccountId=self.account_id):
                    for item in page.get(items_key, []):
                        rid = item.get(id_field)
                        try:
                            getattr(self.client, delete_method)(
                                AwsAccountId=self.account_id, **{delete_kwarg: rid},
                            )
                            self.console.print(f"[green]✓ Deleted {label}: {rid}[/green]")
                        except ClientError as e:
                            self.console.print(f"[red]✗ Error deleting {label} {rid}: {e}[/red]")
            except ClientError as e:
                self.console.print(f"[yellow]⚠ Could not list {label}s: {e}[/yellow]")

        self.console.print("\n[bold green]QuickSight cleanup completed[/bold green]")
