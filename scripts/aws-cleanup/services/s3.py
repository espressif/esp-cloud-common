# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


class S3Cleanup(ServiceCleanup):
    name = 's3'
    boto_client = 's3'
    cli_options = [
        click.option(
            '--protect-bucket-prefix', 'protect_bucket_prefixes', multiple=True,
            help='S3 bucket name prefix to skip during cleanup. Repeatable. '
                 'Example: --protect-bucket-prefix my-deploys- --protect-bucket-prefix publish-',
        ),
    ]

    def run(self):
        protect = tuple(self.options.get('protect_bucket_prefixes') or ())

        self.console.print("[bold cyan]Listing S3 buckets...[/bold cyan]")
        buckets = []
        for bucket in self.client.list_buckets().get('Buckets', []):
            name = bucket.get('Name')
            if protect and name.startswith(protect):
                self.console.print(f"[yellow]Skipping protected bucket: {name}[/yellow]")
                continue
            buckets.append(bucket)
            self.console.print(f"Found bucket: {name}")

        if not buckets:
            self.console.print("[yellow]No buckets to delete[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Found {len(buckets)} buckets to delete[/bold cyan]")
        for bucket in buckets:
            name = bucket.get('Name')
            try:
                self.console.print(f"\n[bold]Processing bucket: {name}[/bold]")
                paginator = self.client.get_paginator('list_object_versions')
                for page in paginator.paginate(Bucket=name):
                    versions = []
                    for v in page.get('Versions', []) or []:
                        versions.append({'Key': v['Key'], 'VersionId': v['VersionId']})
                    for v in page.get('DeleteMarkers', []) or []:
                        versions.append({'Key': v['Key'], 'VersionId': v['VersionId']})
                    if versions:
                        self.client.delete_objects(Bucket=name, Delete={'Objects': versions})
                        self.console.print(f"[green]✓ Deleted {len(versions)} object versions[/green]")

                self.client.delete_bucket(Bucket=name)
                self.console.print(f"[green]✓ Deleted bucket: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting bucket {name}: {e}[/red]")

        self.console.print("\n[bold green]S3 cleanup completed[/bold green]")
