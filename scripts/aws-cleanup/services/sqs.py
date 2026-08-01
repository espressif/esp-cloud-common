from botocore.exceptions import ClientError

from .base import ServiceCleanup


class SQSCleanup(ServiceCleanup):
    name = 'sqs'
    boto_client = 'sqs'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing SQS queues...[/bold cyan]")
        urls = []
        for page in self.client.get_paginator('list_queues').paginate():
            for url in page.get('QueueUrls', []) or []:
                urls.append(url)
                self.console.print(f"Found queue: {url}")

        if not urls:
            self.console.print("[yellow]No queues found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(urls)} queues to delete[/bold cyan]")
        for url in urls:
            try:
                self.client.delete_queue(QueueUrl=url)
                self.console.print(f"[green]✓ Deleted queue: {url}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting queue {url}: {e}[/red]")

        self.console.print("\n[bold green]SQS cleanup completed[/bold green]")
