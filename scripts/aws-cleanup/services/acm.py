# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""ACM cleanup — public certificates and ACM Private Certificate Authorities.

PCA uses a separate ``acm-pca`` client. Deleting a CA requires it to first
be DISABLED, and uses a permanence-deletion window (7–30 days) similar to
KMS. We use 7 days (the minimum).
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class ACMCleanup(ServiceCleanup):
    name = 'acm'
    boto_client = 'acm'
    cli_options = []

    PCA_PERMANENT_DELETION_DAYS = 7

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        pca_real = session.client('acm-pca')
        self.pca = _DryRunClient(pca_real, 'acm-pca', console) if dry_run else pca_real

    def run(self):
        self._delete_public_certificates()
        self._delete_private_cas()
        self.console.print("\n[bold green]ACM cleanup completed[/bold green]")

    def _delete_public_certificates(self):
        self.console.print("[bold cyan]Listing ACM certificates...[/bold cyan]")
        certs = []
        for page in self.client.get_paginator('list_certificates').paginate():
            for cert in page.get('CertificateSummaryList', []):
                certs.append(cert)
                self.console.print(f"Found certificate: {cert.get('DomainName')} ({cert.get('CertificateArn')})")

        if not certs:
            self.console.print("[yellow]No certificates found[/yellow]")
            return

        for cert in certs:
            arn = cert.get('CertificateArn')
            try:
                self.client.delete_certificate(CertificateArn=arn)
                self.console.print(f"[green]✓ Deleted certificate: {cert.get('DomainName')}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting certificate {arn}: {e}[/red]")

    def _delete_private_cas(self):
        self.console.print("\n[bold cyan]Listing ACM PCA private certificate authorities...[/bold cyan]")
        try:
            for page in self.pca.get_paginator('list_certificate_authorities').paginate():
                for ca in page.get('CertificateAuthorities', []):
                    arn = ca.get('Arn')
                    status = ca.get('Status')
                    if status == 'DELETED':
                        continue
                    try:
                        if status == 'ACTIVE':
                            self.pca.update_certificate_authority(
                                CertificateAuthorityArn=arn, Status='DISABLED',
                            )
                        self.pca.delete_certificate_authority(
                            CertificateAuthorityArn=arn,
                            PermanentDeletionTimeInDays=self.PCA_PERMANENT_DELETION_DAYS,
                        )
                        self.console.print(f"[green]✓ Scheduled PCA for deletion: {arn}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting PCA {arn}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list private CAs: {e}[/yellow]")
