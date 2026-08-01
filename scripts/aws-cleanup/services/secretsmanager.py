from botocore.exceptions import ClientError

from .base import ServiceCleanup


class SecretsManagerCleanup(ServiceCleanup):
    name = 'secretsmanager'
    boto_client = 'secretsmanager'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing Secrets Manager secrets...[/bold cyan]")
        secrets = []
        for page in self.client.get_paginator('list_secrets').paginate():
            for secret in page.get('SecretList', []):
                secrets.append(secret)
                self.console.print(f"Found secret: {secret.get('Name')}")

        if not secrets:
            self.console.print("[yellow]No secrets found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(secrets)} secrets to delete[/bold cyan]")
        for secret in secrets:
            name = secret.get('Name')
            try:
                self.client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
                self.console.print(f"[green]✓ Deleted secret: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting secret {name}: {e}[/red]")

        self.console.print("\n[bold green]Secrets Manager cleanup completed[/bold green]")
