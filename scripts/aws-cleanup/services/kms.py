# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""KMS cleanup — schedules customer-managed CMKs for deletion.

KMS does not allow immediate deletion. ``schedule_key_deletion`` queues a key
for removal after a 7–30 day window (default 30; we use 7 — the minimum).
AWS-managed and AWS-owned keys are skipped: they cannot be deleted.
"""

import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


class KMSCleanup(ServiceCleanup):
    name = 'kms'
    boto_client = 'kms'
    cli_options = [
        click.option(
            '--kms-pending-window-days', 'kms_pending_window_days', type=int, default=7,
            show_default=True,
            help='Pending-deletion window for KMS keys (7–30 days). KMS does not '
                 'allow immediate deletion.',
        ),
    ]

    def run(self):
        window = self.options.get('kms_pending_window_days') or 7

        self.console.print("[bold cyan]Listing KMS keys...[/bold cyan]")
        candidates = []
        for page in self.client.get_paginator('list_keys').paginate():
            for key in page.get('Keys', []):
                key_id = key.get('KeyId')
                try:
                    meta = self.client.describe_key(KeyId=key_id).get('KeyMetadata', {})
                except ClientError:
                    continue
                if meta.get('KeyManager') != 'CUSTOMER':
                    continue
                if meta.get('KeyState') in ('PendingDeletion', 'PendingReplicaDeletion'):
                    continue
                candidates.append(meta)
                self.console.print(f"Found key: {key_id} (state: {meta.get('KeyState')})")

        if not candidates:
            self.console.print("[yellow]No customer-managed keys eligible for scheduling[/yellow]")
            return

        self.console.print(f"\n[bold cyan]Scheduling {len(candidates)} keys for deletion in {window} days[/bold cyan]")
        for meta in candidates:
            key_id = meta.get('KeyId')
            try:
                self.client.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=window)
                self.console.print(f"[green]✓ Scheduled key for deletion: {key_id}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error scheduling key {key_id}: {e}[/red]")

        self.console.print("\n[bold green]KMS cleanup completed[/bold green]")
