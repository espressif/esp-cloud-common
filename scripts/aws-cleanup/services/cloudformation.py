# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from botocore.exceptions import ClientError, WaiterError

from .base import ServiceCleanup


class CloudFormationCleanup(ServiceCleanup):
    name = 'cloudformation'
    boto_client = 'cloudformation'
    cli_options = []

    DELETABLE_STATUSES = {
        'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'ROLLBACK_COMPLETE',
        'DELETE_FAILED', 'UPDATE_ROLLBACK_COMPLETE',
    }
    LISTABLE_STATUSES = [
        'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE',
        'ROLLBACK_COMPLETE', 'DELETE_FAILED',
    ]

    def run(self):
        self.console.print("[bold cyan]Listing CloudFormation stacks...[/bold cyan]")
        stacks = []
        paginator = self.client.get_paginator('list_stacks')
        for page in paginator.paginate(StackStatusFilter=self.LISTABLE_STATUSES):
            for stack in page.get('StackSummaries', []):
                if stack['StackStatus'] != 'DELETE_COMPLETE' and 'ParentId' not in stack:
                    stacks.append(stack)
                    self.console.print(f"Found stack: {stack.get('StackName')}")

        if not stacks:
            self.console.print("[yellow]No stacks found[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(stacks)} stacks to delete[/bold cyan]")
        sorted_stacks = sorted(stacks, key=lambda x: x.get('CreationTime', ''), reverse=True)

        for stack in sorted_stacks:
            stack_name = stack.get('StackName')
            try:
                self.console.print(f"\n[bold]Processing stack: {stack_name}[/bold]")
                response = self.client.describe_stacks(StackName=stack_name)
                stack_status = response['Stacks'][0]['StackStatus']

                try:
                    self.client.update_termination_protection(
                        StackName=stack_name,
                        EnableTerminationProtection=False,
                    )
                except ClientError as e:
                    if "Stack does not have termination protection enabled" not in str(e):
                        self.console.print(f"[yellow]⚠ Could not disable termination protection: {e}[/yellow]")

                if stack_status not in self.DELETABLE_STATUSES:
                    self.console.print(f"[yellow]Skipping stack '{stack_name}' (status: {stack_status})[/yellow]")
                    continue

                try:
                    self.client.delete_stack(StackName=stack_name)
                    waiter = self.client.get_waiter('stack_delete_complete')
                    waiter.wait(StackName=stack_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 240})
                except (ClientError, WaiterError):
                    # A blocked delete raises ClientError; the delete waiter raises WaiterError for
                    # BOTH a terminal DELETE_FAILED and a plain timeout (a healthy, still-in-progress
                    # delete that just exceeded the wait budget). Re-check the real status so we only
                    # escalate to force-delete a genuinely stuck stack — never abandon one that is
                    # still deleting.
                    try:
                        status = self.client.describe_stacks(StackName=stack_name)['Stacks'][0]['StackStatus']
                    except ClientError:
                        status = 'DELETE_COMPLETE'  # already gone
                    if status == 'DELETE_IN_PROGRESS':
                        self.console.print(f"[yellow]Stack '{stack_name}' still deleting after the wait budget — leaving it to finish (not force-deleting).[/yellow]")
                        continue
                    if status != 'DELETE_COMPLETE':
                        self.console.print("[yellow]Regular deletion failed, attempting force delete...[/yellow]")
                        self.client.delete_stack(StackName=stack_name, DeletionMode='FORCE_DELETE_STACK')
                        waiter = self.client.get_waiter('stack_delete_complete')
                        waiter.wait(StackName=stack_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 240})

                self.console.print(f"[green]✓ Deleted stack: {stack_name}[/green]")
            except (ClientError, WaiterError) as e:
                # Catch WaiterError too, so ONE stuck stack (e.g. a cert still in use by a
                # consumer removed later) is logged and skipped instead of aborting the whole
                # CloudFormation sweep. The retry pass at the end re-attempts it.
                self.console.print(f"[red]✗ Error deleting stack {stack_name}: {e}[/red]")

        self._delete_stack_sets()
        self.console.print("\n[bold green]CloudFormation cleanup completed[/bold green]")

    def _delete_stack_sets(self):
        self.console.print("\n[bold cyan]Listing CloudFormation stack sets...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_stack_sets').paginate(Status='ACTIVE'):
                for ss in page.get('Summaries', []):
                    name = ss.get('StackSetName')
                    perm = ss.get('PermissionModel', 'SELF_MANAGED')
                    try:
                        # Stack instances must be deleted first
                        try:
                            instances_paginator = self.client.get_paginator('list_stack_instances')
                            instance_pages = list(instances_paginator.paginate(StackSetName=name))
                            account_region_pairs = []
                            for ip in instance_pages:
                                for inst in ip.get('Summaries', []):
                                    account_region_pairs.append((inst.get('Account'), inst.get('Region')))
                            if account_region_pairs:
                                accounts = sorted({a for a, _ in account_region_pairs})
                                regions = sorted({r for _, r in account_region_pairs})
                                kwargs = {
                                    'StackSetName': name,
                                    'Regions': regions,
                                    'RetainStacks': False,
                                }
                                if perm == 'SERVICE_MANAGED':
                                    kwargs['DeploymentTargets'] = {'Accounts': accounts}
                                else:
                                    kwargs['Accounts'] = accounts
                                self.client.delete_stack_instances(**kwargs)
                        except ClientError as e:
                            self.console.print(f"[yellow]⚠ Could not delete instances of {name}: {e}[/yellow]")

                        self.client.delete_stack_set(StackSetName=name)
                        self.console.print(f"[green]✓ Deleted stack set: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting stack set {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list stack sets: {e}[/yellow]")
