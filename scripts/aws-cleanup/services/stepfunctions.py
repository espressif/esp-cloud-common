from botocore.exceptions import ClientError

from .base import ServiceCleanup


class StepFunctionsCleanup(ServiceCleanup):
    name = 'stepfunctions'
    boto_client = 'stepfunctions'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing Step Functions state machines...[/bold cyan]")
        machines = []
        for page in self.client.get_paginator('list_state_machines').paginate():
            for sm in page.get('stateMachines', []):
                machines.append(sm)
                self.console.print(f"Found state machine: {sm.get('name')}")

        if not machines:
            self.console.print("[yellow]No state machines found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(machines)} state machines to delete[/bold cyan]")
        for sm in machines:
            arn = sm.get('stateMachineArn')
            try:
                self.client.delete_state_machine(stateMachineArn=arn)
                self.console.print(f"[green]✓ Deleted state machine: {sm.get('name')}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting state machine {arn}: {e}[/red]")

        self._delete_activities()
        self.console.print("\n[bold green]Step Functions cleanup completed[/bold green]")

    def _delete_activities(self):
        self.console.print("\n[bold cyan]Listing Step Functions activities...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_activities').paginate():
                for a in page.get('activities', []):
                    arn = a.get('activityArn')
                    name = a.get('name')
                    try:
                        self.client.delete_activity(activityArn=arn)
                        self.console.print(f"[green]✓ Deleted activity: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting activity {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list activities: {e}[/yellow]")
