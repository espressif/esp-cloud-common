from botocore.exceptions import ClientError

from .base import ServiceCleanup


class AppSyncCleanup(ServiceCleanup):
    name = 'appsync'
    boto_client = 'appsync'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing AppSync GraphQL APIs...[/bold cyan]")
        apis = []
        next_token = None
        try:
            while True:
                kwargs = {'maxResults': 25}
                if next_token:
                    kwargs['nextToken'] = next_token
                response = self.client.list_graphql_apis(**kwargs)
                apis.extend(response.get('graphqlApis', []))
                next_token = response.get('nextToken')
                if not next_token:
                    break
        except ClientError as e:
            self.console.print(f"[red]Error listing AppSync APIs: {e}[/red]")
            return

        for api in apis:
            self.console.print(f"Found GraphQL API: {api.get('name')} ({api.get('apiId')})")

        if not apis:
            self.console.print("[yellow]No AppSync APIs found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(apis)} AppSync APIs to delete[/bold cyan]")
        for api in apis:
            api_id = api.get('apiId')
            name = api.get('name')
            try:
                self.client.delete_graphql_api(apiId=api_id)
                self.console.print(f"[green]✓ Deleted AppSync API: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting AppSync API {name}: {e}[/red]")

        self.console.print("\n[bold green]AppSync cleanup completed[/bold green]")
