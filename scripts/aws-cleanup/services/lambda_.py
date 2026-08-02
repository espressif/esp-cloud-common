# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class LambdaCleanup(ServiceCleanup):
    name = 'lambda'
    boto_client = 'lambda'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing Lambda functions...[/bold cyan]")
        functions = []
        for page in self.client.get_paginator('list_functions').paginate():
            for fn in page.get('Functions', []):
                functions.append(fn)
                self.console.print(f"Found function: {fn.get('FunctionName')}")

        if not functions:
            self.console.print("[yellow]No functions found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(functions)} functions to delete[/bold cyan]")
        for fn in functions:
            name = fn.get('FunctionName')
            try:
                self.client.delete_function(FunctionName=name)
                self.console.print(f"[green]✓ Deleted function: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting function {name}: {e}[/red]")

        self.console.print("\n[bold green]Lambda cleanup completed[/bold green]")
