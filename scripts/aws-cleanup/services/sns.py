# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class SNSCleanup(ServiceCleanup):
    name = 'sns'
    boto_client = 'sns'
    cli_options = []

    def run(self):
        self._cleanup_topics()
        self._cleanup_platform_applications()
        self.console.print("\n[bold green]SNS cleanup completed[/bold green]")

    def _cleanup_topics(self):
        self.console.print("[bold cyan]Listing SNS topics...[/bold cyan]")
        topics = []
        for page in self.client.get_paginator('list_topics').paginate():
            for topic in page.get('Topics', []):
                topics.append(topic)
                self.console.print(f"Found topic: {topic.get('TopicArn')}")

        if not topics:
            self.console.print("[yellow]No topics found[/yellow]")
            return

        for topic in topics:
            arn = topic.get('TopicArn')
            try:
                paginator = self.client.get_paginator('list_subscriptions_by_topic')
                for page in paginator.paginate(TopicArn=arn):
                    for sub in page.get('Subscriptions', []):
                        try:
                            self.client.unsubscribe(SubscriptionArn=sub['SubscriptionArn'])
                        except ClientError as e:
                            self.console.print(f"[yellow]⚠ Could not unsubscribe: {e}[/yellow]")

                self.client.delete_topic(TopicArn=arn)
                self.console.print(f"[green]✓ Deleted topic: {arn}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting topic {arn}: {e}[/red]")

    def _cleanup_platform_applications(self):
        self.console.print("\n[bold cyan]Listing SNS platform applications...[/bold cyan]")
        try:
            platforms = []
            for page in self.client.get_paginator('list_platform_applications').paginate():
                for platform in page.get('PlatformApplications', []):
                    platforms.append(platform)
                    self.console.print(f"Found platform: {platform.get('PlatformApplicationArn')}")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list platform applications: {e}[/yellow]")
            return

        if not platforms:
            self.console.print("[yellow]No platform applications found[/yellow]")
            return

        for platform in platforms:
            arn = platform.get('PlatformApplicationArn')
            try:
                paginator = self.client.get_paginator('list_endpoints_by_platform_application')
                for page in paginator.paginate(PlatformApplicationArn=arn):
                    for endpoint in page.get('Endpoints', []):
                        try:
                            self.client.delete_endpoint(EndpointArn=endpoint['EndpointArn'])
                        except ClientError as e:
                            self.console.print(f"[yellow]⚠ Could not delete endpoint: {e}[/yellow]")

                self.client.delete_platform_application(PlatformApplicationArn=arn)
                self.console.print(f"[green]✓ Deleted platform: {arn}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting platform {arn}: {e}[/red]")
