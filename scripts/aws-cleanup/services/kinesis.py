# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Kinesis cleanup — Data Streams + Firehose delivery streams.

Two boto3 clients live in one module here because users think of "Kinesis"
as a single thing.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class KinesisCleanup(ServiceCleanup):
    name = 'kinesis'
    boto_client = 'kinesis'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        def _wrap(real, name):
            return _DryRunClient(real, name, console) if dry_run else real
        self.firehose = _wrap(session.client('firehose'), 'firehose')
        self.video = _wrap(session.client('kinesisvideo'), 'kinesisvideo')
        self.flink = _wrap(session.client('kinesisanalyticsv2'), 'kinesisanalyticsv2')

    def run(self):
        self._delete_data_streams()
        self._delete_firehose_streams()
        self._delete_video_streams()
        self._delete_flink_applications()
        self.console.print("\n[bold green]Kinesis cleanup completed[/bold green]")

    def _delete_video_streams(self):
        self.console.print("\n[bold cyan]Listing Kinesis Video Streams...[/bold cyan]")
        try:
            response = self.video.list_streams()
            streams = response.get('StreamInfoList', [])
            while response.get('NextToken'):
                response = self.video.list_streams(NextToken=response['NextToken'])
                streams.extend(response.get('StreamInfoList', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list video streams: {e}[/yellow]")
            return

        for s in streams:
            name = s.get('StreamName')
            arn = s.get('StreamARN')
            try:
                self.video.delete_stream(StreamARN=arn)
                self.console.print(f"[green]✓ Deleted video stream: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting video stream {name}: {e}[/red]")

    def _delete_flink_applications(self):
        self.console.print("\n[bold cyan]Listing Managed Service for Apache Flink applications...[/bold cyan]")
        try:
            response = self.flink.list_applications()
            apps = response.get('ApplicationSummaries', [])
            while response.get('NextToken'):
                response = self.flink.list_applications(NextToken=response['NextToken'])
                apps.extend(response.get('ApplicationSummaries', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list Flink applications: {e}[/yellow]")
            return

        for app in apps:
            name = app.get('ApplicationName')
            try:
                detail = self.flink.describe_application(ApplicationName=name)
                create_ts = detail.get('ApplicationDetail', {}).get('CreateTimestamp')
                self.flink.delete_application(ApplicationName=name, CreateTimestamp=create_ts)
                self.console.print(f"[green]✓ Deleted Flink application: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting Flink application {name}: {e}[/red]")

    def _delete_data_streams(self):
        self.console.print("[bold cyan]Listing Kinesis Data Streams...[/bold cyan]")
        names = []
        try:
            for page in self.client.get_paginator('list_streams').paginate():
                for name in page.get('StreamNames', []):
                    names.append(name)
                    self.console.print(f"Found data stream: {name}")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list streams: {e}[/yellow]")
            return

        for name in names:
            try:
                self.client.delete_stream(StreamName=name, EnforceConsumerDeletion=True)
                self.console.print(f"[green]✓ Deleted data stream: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting data stream {name}: {e}[/red]")

    def _delete_firehose_streams(self):
        self.console.print("\n[bold cyan]Listing Kinesis Firehose delivery streams...[/bold cyan]")
        names = []
        try:
            response = self.firehose.list_delivery_streams()
            names.extend(response.get('DeliveryStreamNames', []))
            while response.get('HasMoreDeliveryStreams'):
                response = self.firehose.list_delivery_streams(
                    ExclusiveStartDeliveryStreamName=names[-1],
                )
                names.extend(response.get('DeliveryStreamNames', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list Firehose streams: {e}[/yellow]")
            return

        for name in names:
            self.console.print(f"Found Firehose stream: {name}")
            try:
                self.firehose.delete_delivery_stream(DeliveryStreamName=name)
                self.console.print(f"[green]✓ Deleted Firehose stream: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting Firehose stream {name}: {e}[/red]")
