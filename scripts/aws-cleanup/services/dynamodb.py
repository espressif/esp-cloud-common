# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class DynamoDBCleanup(ServiceCleanup):
    name = 'dynamodb'
    boto_client = 'dynamodb'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing DynamoDB tables...[/bold cyan]")
        tables = []
        for page in self.client.get_paginator('list_tables').paginate():
            for name in page.get('TableNames', []):
                tables.append(name)
                self.console.print(f"Found table: {name}")

        if not tables:
            self.console.print("[yellow]No tables found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(tables)} tables to delete[/bold cyan]")
        for name in tables:
            try:
                self.client.delete_table(TableName=name)
                waiter = self.client.get_waiter('table_not_exists')
                waiter.wait(TableName=name)
                self.console.print(f"[green]✓ Deleted table: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting table {name}: {e}[/red]")

        self.console.print("\n[bold green]DynamoDB cleanup completed[/bold green]")
