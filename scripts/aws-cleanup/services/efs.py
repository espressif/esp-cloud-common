"""EFS cleanup — mount targets must be removed before the filesystem itself."""

import time

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class EFSCleanup(ServiceCleanup):
    name = 'efs'
    boto_client = 'efs'
    cli_options = []

    def run(self):
        self.console.print("[bold cyan]Listing EFS filesystems...[/bold cyan]")
        filesystems = []
        for page in self.client.get_paginator('describe_file_systems').paginate():
            for fs in page.get('FileSystems', []):
                filesystems.append(fs)
                self.console.print(f"Found filesystem: {fs.get('FileSystemId')}")

        if not filesystems:
            self.console.print("[yellow]No filesystems found[/yellow]")
            return

        for fs in filesystems:
            fs_id = fs.get('FileSystemId')
            try:
                self._delete_access_points(fs_id)
                self._delete_mount_targets(fs_id)
                self.client.delete_file_system(FileSystemId=fs_id)
                self.console.print(f"[green]✓ Deleted filesystem: {fs_id}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting filesystem {fs_id}: {e}[/red]")

        self.console.print("\n[bold green]EFS cleanup completed[/bold green]")

    def _delete_access_points(self, fs_id):
        try:
            response = self.client.describe_access_points(FileSystemId=fs_id)
            for ap in response.get('AccessPoints', []):
                ap_id = ap.get('AccessPointId')
                try:
                    self.client.delete_access_point(AccessPointId=ap_id)
                    self.console.print(f"[green]✓ Deleted access point: {ap_id}[/green]")
                except ClientError as e:
                    self.console.print(f"[yellow]⚠ Could not delete access point {ap_id}: {e}[/yellow]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list access points for {fs_id}: {e}[/yellow]")

    def _delete_mount_targets(self, fs_id):
        try:
            response = self.client.describe_mount_targets(FileSystemId=fs_id)
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list mount targets: {e}[/yellow]")
            return

        mt_ids = [mt.get('MountTargetId') for mt in response.get('MountTargets', [])]
        for mt_id in mt_ids:
            try:
                self.client.delete_mount_target(MountTargetId=mt_id)
                self.console.print(f"[green]✓ Deleted mount target: {mt_id}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting mount target {mt_id}: {e}[/red]")

        # Filesystem deletion fails if mount targets are still in 'deleting' state.
        # Poll briefly until they're gone. Skipped in dry-run (proxy short-circuits).
        if mt_ids and not self.dry_run:
            for _ in range(30):
                time.sleep(2)
                remaining = self.client.describe_mount_targets(FileSystemId=fs_id).get('MountTargets', [])
                if not remaining:
                    return
